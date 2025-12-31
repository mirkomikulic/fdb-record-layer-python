"""Java-compatible metadata storage.

Stores record metadata using the same protobuf format as the Java
Record Layer, enabling schema interchange between Java and Python.

Key features:
- Protobuf-based serialization matching Java format
- Integer subspace keys for indexes (not string names)
- Automatic subspace key counter management
"""

from __future__ import annotations

import struct
from typing import TYPE_CHECKING, Any

from fdb_record_layer.compat.proto import (
    FanType,
)
from fdb_record_layer.compat.proto import (
    Field as FieldProto,
)
from fdb_record_layer.compat.proto import (
    KeyExpression as KeyExpressionProto,
)
from fdb_record_layer.compat.proto import (
    MetaData as MetaDataProto,
)
from fdb_record_layer.compat.proto import (
    Nesting as NestingProto,
)
from fdb_record_layer.compat.proto import (
    Then as ThenProto,
)
from fdb_record_layer.expressions.base import KeyExpression
from fdb_record_layer.expressions.concat import ConcatenateKeyExpression
from fdb_record_layer.expressions.field import FieldKeyExpression
from fdb_record_layer.expressions.nest import NestKeyExpression
from fdb_record_layer.metadata.index import Index, IndexType
from fdb_record_layer.metadata.record_metadata import RecordMetaData, RecordType

if TYPE_CHECKING:
    from fdb import Transaction
    from fdb.subspace_impl import Subspace


# Subspace key for metadata storage
METADATA_KEY = b"M"


def key_expression_to_proto(expr: KeyExpression) -> KeyExpressionProto:
    """Convert a KeyExpression to protobuf format."""
    proto = KeyExpressionProto()

    if isinstance(expr, FieldKeyExpression):
        field_proto = FieldProto()
        field_proto.field_name = expr.field_name
        # Map fan type
        fan_type = getattr(expr, "fan_type", None)
        if fan_type:
            if fan_type.name == "FAN_OUT":
                field_proto.fan_type = FanType.FAN_OUT
            elif fan_type.name == "CONCATENATE":
                field_proto.fan_type = FanType.CONCATENATE
            else:
                field_proto.fan_type = FanType.SCALAR
        else:
            field_proto.fan_type = FanType.SCALAR
        proto.field.CopyFrom(field_proto)

    elif isinstance(expr, ConcatenateKeyExpression):
        then_proto = ThenProto()
        for child in expr.children:
            child_proto = key_expression_to_proto(child)
            then_proto.children.append(child_proto)
        proto.then.CopyFrom(then_proto)

    elif isinstance(expr, NestKeyExpression):
        nesting_proto = NestingProto()
        nesting_proto.parent = expr.parent_field
        if expr.child:
            nesting_proto.child.CopyFrom(key_expression_to_proto(expr.child))
        proto.nesting.CopyFrom(nesting_proto)

    return proto


def proto_to_key_expression(proto: KeyExpressionProto) -> KeyExpression:
    """Convert a protobuf KeyExpression to our format."""
    from fdb_record_layer.expressions.base import FanType as OurFanType

    which = proto.WhichOneof("expression")

    if which == "field":
        field = proto.field
        fan_type = OurFanType.NONE
        if field.fan_type == FanType.FAN_OUT:
            fan_type = OurFanType.FAN_OUT
        elif field.fan_type == FanType.CONCATENATE:
            fan_type = OurFanType.CONCATENATE
        return FieldKeyExpression(field.field_name, fan_type)

    elif which == "then":
        children = [proto_to_key_expression(c) for c in proto.then.children]
        return ConcatenateKeyExpression(children)

    elif which == "nesting":
        child = None
        if proto.nesting.HasField("child"):
            child = proto_to_key_expression(proto.nesting.child)
        return NestKeyExpression(proto.nesting.parent, child)  # type: ignore[arg-type]

    elif which == "empty":
        from fdb_record_layer.expressions.base import EmptyKeyExpression

        return EmptyKeyExpression()

    elif which == "record_type_key":
        from fdb_record_layer.expressions.record_type import RecordTypeKeyExpression

        return RecordTypeKeyExpression()

    else:
        # Default to empty
        from fdb_record_layer.expressions.base import EmptyKeyExpression

        return EmptyKeyExpression()


def index_type_to_string(index_type: IndexType) -> str:
    """Convert IndexType enum to Java string format."""
    mapping = {
        IndexType.VALUE: "VALUE",
        IndexType.COUNT: "COUNT",
        IndexType.SUM: "SUM",
        IndexType.MIN_EVER: "MIN_EVER",
        IndexType.MAX_EVER: "MAX_EVER",
        IndexType.RANK: "RANK",
        IndexType.TEXT: "TEXT",
        IndexType.VERSION: "VERSION",
    }
    return mapping.get(index_type, "VALUE")


def string_to_index_type(type_str: str) -> IndexType:
    """Convert Java string format to IndexType enum."""
    mapping = {
        "VALUE": IndexType.VALUE,
        "COUNT": IndexType.COUNT,
        "SUM": IndexType.SUM,
        "MIN_EVER": IndexType.MIN_EVER,
        "MAX_EVER": IndexType.MAX_EVER,
        "RANK": IndexType.RANK,
        "TEXT": IndexType.TEXT,
        "VERSION": IndexType.VERSION,
    }
    return mapping.get(type_str, IndexType.VALUE)


class JavaCompatibleMetaDataStore:
    """Stores metadata in Java-compatible protobuf format.

    This ensures metadata can be read by Java applications and vice versa.
    """

    def __init__(self, subspace: Subspace):
        """Initialize metadata store.

        Args:
            subspace: Subspace for metadata storage (typically INDEX_SECONDARY_SPACE)
        """
        self._subspace = subspace
        self._subspace_key_counter = 0

    def metadata_to_proto(self, metadata: RecordMetaData) -> MetaDataProto:
        """Convert RecordMetaData to protobuf format."""
        proto = MetaDataProto()

        # Version
        proto.version = metadata.version

        # Record types
        for rt in metadata.record_types.values():
            rt_proto = proto.record_types.add()
            rt_proto.name = rt.name
            if rt.primary_key:
                rt_proto.primary_key.CopyFrom(key_expression_to_proto(rt.primary_key))
            if hasattr(rt, "since_version") and rt.since_version:
                rt_proto.since_version = rt.since_version

        # Indexes with subspace key assignment
        for index in metadata.indexes.values():
            idx_proto = proto.indexes.add()
            idx_proto.name = index.name
            idx_proto.type = index_type_to_string(index.index_type)

            # Record types
            if index.record_types:
                for rt_name in index.record_types:
                    idx_proto.record_type.append(rt_name)

            # Root expression
            if index.root_expression:
                idx_proto.root_expression.CopyFrom(key_expression_to_proto(index.root_expression))

            # Subspace key - use existing or assign new
            if hasattr(index, "subspace_key") and index.subspace_key is not None:
                if isinstance(index.subspace_key, int):
                    idx_proto.subspace_key = struct.pack(">q", index.subspace_key)
                elif isinstance(index.subspace_key, bytes):
                    idx_proto.subspace_key = index.subspace_key
                else:
                    # Generate from name hash
                    idx_proto.subspace_key = struct.pack(">q", self._next_subspace_key())
            else:
                idx_proto.subspace_key = struct.pack(">q", self._next_subspace_key())

            # Version info
            if hasattr(index, "added_version") and index.added_version:
                idx_proto.added_version = index.added_version
            if hasattr(index, "last_modified_version") and index.last_modified_version:
                idx_proto.last_modified_version = index.last_modified_version

        # Former indexes
        if hasattr(metadata, "former_indexes"):
            for former in metadata.former_indexes:
                former_proto = proto.former_indexes.add()
                if hasattr(former, "subspace_key"):
                    if isinstance(former.subspace_key, int):
                        former_proto.subspace_key = struct.pack(">q", former.subspace_key)
                    else:
                        former_proto.subspace_key = former.subspace_key
                if hasattr(former, "former_name"):
                    former_proto.former_name = former.former_name
                if hasattr(former, "added_version"):
                    former_proto.added_version = former.added_version
                if hasattr(former, "removed_version"):
                    former_proto.removed_version = former.removed_version

        # Settings
        proto.split_long_records = getattr(metadata, "split_long_records", True)
        proto.store_record_versions = getattr(metadata, "store_record_versions", True)
        proto.subspace_key_counter = self._subspace_key_counter
        proto.uses_subspace_key_counter = True

        return proto

    def proto_to_metadata(
        self, proto: MetaDataProto, file_descriptor: Any = None
    ) -> RecordMetaData:
        """Convert protobuf to RecordMetaData."""
        record_types = {}
        indexes = {}

        # Record types
        for rt_proto in proto.record_types:
            primary_key = None
            if rt_proto.HasField("primary_key"):
                primary_key = proto_to_key_expression(rt_proto.primary_key)

            rt = RecordType(
                name=rt_proto.name,
                descriptor=None,  # type: ignore[arg-type]  # Will be set from file_descriptor if available
                primary_key=primary_key,  # type: ignore[arg-type]
            )
            if rt_proto.since_version:
                rt.since_version = rt_proto.since_version
            record_types[rt.name] = rt

        # Indexes
        for idx_proto in proto.indexes:
            root_expr = None
            if idx_proto.HasField("root_expression"):
                root_expr = proto_to_key_expression(idx_proto.root_expression)

            # Parse subspace key
            subspace_key = None
            if idx_proto.subspace_key:
                if len(idx_proto.subspace_key) == 8:
                    subspace_key = struct.unpack(">q", idx_proto.subspace_key)[0]
                else:
                    subspace_key = idx_proto.subspace_key

            index = Index(
                name=idx_proto.name,
                root_expression=root_expr,  # type: ignore[arg-type]
                index_type=string_to_index_type(idx_proto.type),
                record_types=list(idx_proto.record_type),
            )
            index.subspace_key = subspace_key
            if idx_proto.added_version:
                index.added_version = idx_proto.added_version
            if idx_proto.last_modified_version:
                index.last_modified_version = idx_proto.last_modified_version

            indexes[index.name] = index

        # Update subspace key counter
        self._subspace_key_counter = proto.subspace_key_counter

        return RecordMetaData(
            version=proto.version,
            record_types=record_types,
            indexes=indexes,
            file_descriptor=file_descriptor,
        )

    def _next_subspace_key(self) -> int:
        """Get next subspace key and increment counter."""
        key = self._subspace_key_counter
        self._subspace_key_counter += 1
        return key

    async def save(self, tr: Transaction, metadata: RecordMetaData) -> None:
        """Save metadata to FDB."""
        proto = self.metadata_to_proto(metadata)
        key = self._subspace.pack((METADATA_KEY,))
        tr.set(key, proto.SerializeToString())

    async def load(self, tr: Transaction) -> RecordMetaData | None:
        """Load metadata from FDB."""
        import asyncio

        key = self._subspace.pack((METADATA_KEY,))

        loop = asyncio.get_event_loop()
        value = await loop.run_in_executor(None, lambda: tr[key])

        if not value.present():
            return None

        proto = MetaDataProto()
        proto.ParseFromString(bytes(value))
        return self.proto_to_metadata(proto)


def assign_subspace_keys(metadata: RecordMetaData) -> RecordMetaData:
    """Assign integer subspace keys to all indexes.

    This ensures indexes use integer keys instead of string names,
    matching the Java format.
    """
    counter = 0

    for index in metadata.indexes.values():
        if not hasattr(index, "subspace_key") or index.subspace_key is None:
            index.subspace_key = counter
            counter += 1

    return metadata
