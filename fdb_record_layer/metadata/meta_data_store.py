"""Persistent metadata storage in FoundationDB.

The FDBMetaDataStore provides persistent storage for RecordMetaData,
enabling schema versioning, atomic updates, and multi-tenant scenarios.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from enum import Enum
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from fdb.subspace_impl import Subspace

    from fdb_record_layer.metadata.record_metadata import RecordMetaData


class MetaDataKeySpace(bytes, Enum):
    """Key space prefixes for metadata storage."""

    HEADER = b"\x00"  # Metadata header (version, etc.)
    RECORD_TYPES = b"\x01"  # Record type definitions
    INDEXES = b"\x02"  # Index definitions
    FORMER_INDEXES = b"\x03"  # Removed indexes
    STORE_INFO = b"\x04"  # Store-level info


@dataclass
class MetaDataHeader:
    """Header containing metadata version and checksum."""

    version: int
    format_version: int = 1
    created_timestamp: float | None = None
    modified_timestamp: float | None = None

    def to_bytes(self) -> bytes:
        """Serialize header to bytes."""
        data = {
            "version": self.version,
            "format_version": self.format_version,
            "created_timestamp": self.created_timestamp,
            "modified_timestamp": self.modified_timestamp,
        }
        return json.dumps(data).encode("utf-8")

    @classmethod
    def from_bytes(cls, data: bytes) -> MetaDataHeader:
        """Deserialize header from bytes."""
        parsed = json.loads(data.decode("utf-8"))
        return cls(
            version=parsed["version"],
            format_version=parsed.get("format_version", 1),
            created_timestamp=parsed.get("created_timestamp"),
            modified_timestamp=parsed.get("modified_timestamp"),
        )


class MetaDataSerializer:
    """Serializes and deserializes RecordMetaData to/from FDB.

    Uses JSON for human-readable storage. For production, a more
    efficient binary format could be used.
    """

    @staticmethod
    def serialize_record_type(record_type: Any) -> bytes:
        """Serialize a RecordType to bytes."""
        data = {
            "name": record_type.name,
            "primary_key": MetaDataSerializer._serialize_key_expression(record_type.primary_key),
            "since_version": record_type.since_version,
            # Note: descriptor is not serialized - it comes from protobuf
        }
        return json.dumps(data).encode("utf-8")

    @staticmethod
    def serialize_index(index: Any) -> bytes:
        """Serialize an Index to bytes."""
        data = {
            "name": index.name,
            "root_expression": MetaDataSerializer._serialize_key_expression(index.root_expression),
            "index_type": index.index_type.value,
            "record_types": index.record_types,
            "options": index.options.to_dict() if hasattr(index.options, "to_dict") else {},
            "added_version": index.added_version,
            "last_modified_version": index.last_modified_version,
        }
        return json.dumps(data).encode("utf-8")

    @staticmethod
    def serialize_former_index(former_index: Any) -> bytes:
        """Serialize a FormerIndex to bytes."""
        data = {
            "name": former_index.name,
            "added_version": former_index.added_version,
            "removed_version": former_index.removed_version,
        }
        return json.dumps(data).encode("utf-8")

    @staticmethod
    def _serialize_key_expression(expr: Any) -> dict:
        """Serialize a KeyExpression to a dict."""
        from fdb_record_layer.expressions.concat import ConcatenateKeyExpression
        from fdb_record_layer.expressions.field import FieldKeyExpression
        from fdb_record_layer.expressions.nest import NestKeyExpression

        if isinstance(expr, FieldKeyExpression):
            fan_type = expr.fan_type
            fan_type_str = fan_type.value if hasattr(fan_type, "value") else str(fan_type)
            return {
                "type": "field",
                "field_name": expr.field_name,
                "fan_type": fan_type_str,
            }
        elif isinstance(expr, ConcatenateKeyExpression):
            return {
                "type": "concat",
                "children": [
                    MetaDataSerializer._serialize_key_expression(c) for c in expr.children
                ],
            }
        elif isinstance(expr, NestKeyExpression):
            return {
                "type": "nest",
                "parent_field": expr.parent_field,
                "child": MetaDataSerializer._serialize_key_expression(expr.child),
            }
        else:
            # Generic fallback
            return {"type": "unknown", "repr": repr(expr)}

    @staticmethod
    def deserialize_key_expression(data: dict) -> Any:
        """Deserialize a KeyExpression from a dict."""
        from fdb_record_layer.expressions.concat import ConcatenateKeyExpression
        from fdb_record_layer.expressions.field import FanType, FieldKeyExpression
        from fdb_record_layer.expressions.nest import NestKeyExpression

        expr_type = data.get("type")

        if expr_type == "field":
            fan_type_str = data.get("fan_type", "FanType.NONE")
            # Parse fan type
            if "CONCATENATE" in fan_type_str:
                fan_type = FanType.CONCATENATE
            elif "FAN_OUT" in fan_type_str:
                fan_type = FanType.FAN_OUT
            else:
                fan_type = FanType.NONE
            return FieldKeyExpression(field_name=data["field_name"], fan_type=fan_type)

        elif expr_type == "concat":
            children = [MetaDataSerializer.deserialize_key_expression(c) for c in data["children"]]
            return ConcatenateKeyExpression(children=children)

        elif expr_type == "nest":
            child = MetaDataSerializer.deserialize_key_expression(data["child"])
            return NestKeyExpression(parent_field=data["parent_field"], child=child)

        else:
            raise ValueError(f"Unknown expression type: {expr_type}")


class FDBMetaDataStore:
    """Persistent storage for RecordMetaData in FoundationDB.

    The metadata store handles:
    - Saving and loading metadata
    - Atomic metadata updates with version checking
    - Multi-version support for schema evolution

    Example:
        >>> store = FDBMetaDataStore(context, subspace)
        >>> await store.save_metadata(metadata)
        >>> loaded = await store.load_metadata(file_descriptor)
    """

    def __init__(self, subspace: Subspace) -> None:
        """Initialize the metadata store.

        Args:
            subspace: The FDB subspace for metadata storage.
        """
        self._subspace = subspace
        self._serializer = MetaDataSerializer()

    def _header_key(self) -> bytes:
        """Get the key for the metadata header."""
        return self._subspace.pack((MetaDataKeySpace.HEADER,))

    def _record_type_key(self, name: str) -> bytes:
        """Get the key for a record type."""
        return self._subspace.pack((MetaDataKeySpace.RECORD_TYPES, name))

    def _index_key(self, name: str) -> bytes:
        """Get the key for an index."""
        return self._subspace.pack((MetaDataKeySpace.INDEXES, name))

    def _former_index_key(self, name: str, removed_version: int) -> bytes:
        """Get the key for a former index."""
        return self._subspace.pack((MetaDataKeySpace.FORMER_INDEXES, name, removed_version))

    async def save_metadata(
        self,
        tr: Any,  # FDB transaction
        metadata: RecordMetaData,
        expected_version: int | None = None,
    ) -> None:
        """Save metadata to the store.

        Args:
            tr: FDB transaction.
            metadata: The metadata to save.
            expected_version: If set, only save if current version matches.

        Raises:
            MetaDataVersionMismatchError: If expected_version doesn't match.
        """
        import time

        # Check version if expected
        if expected_version is not None:
            current_header = await self._load_header(tr)
            if current_header is not None and current_header.version != expected_version:
                from fdb_record_layer.core.exceptions import MetaDataVersionMismatchError

                raise MetaDataVersionMismatchError(expected_version, current_header.version)

        # Create or update header
        existing_header = await self._load_header(tr)
        header = MetaDataHeader(
            version=metadata.version,
            created_timestamp=(
                existing_header.created_timestamp if existing_header else time.time()
            ),
            modified_timestamp=time.time(),
        )

        # Save header
        tr[self._header_key()] = header.to_bytes()

        # Clear existing record types and indexes
        record_types_range = self._subspace.range((MetaDataKeySpace.RECORD_TYPES,))
        tr.clear_range(record_types_range.start, record_types_range.stop)

        indexes_range = self._subspace.range((MetaDataKeySpace.INDEXES,))
        tr.clear_range(indexes_range.start, indexes_range.stop)

        # Save record types
        for name, record_type in metadata.record_types.items():
            tr[self._record_type_key(name)] = self._serializer.serialize_record_type(record_type)

        # Save indexes
        for name, index in metadata.indexes.items():
            tr[self._index_key(name)] = self._serializer.serialize_index(index)

        # Save former indexes
        for former_index in metadata.former_indexes:
            key = self._former_index_key(former_index.name, former_index.removed_version)
            tr[key] = self._serializer.serialize_former_index(former_index)

    async def load_metadata(
        self,
        tr: Any,  # FDB transaction
        file_descriptor: Any,  # FileDescriptor
    ) -> RecordMetaData | None:
        """Load metadata from the store.

        Args:
            tr: FDB transaction.
            file_descriptor: Protobuf file descriptor for type resolution.

        Returns:
            The loaded metadata, or None if not found.
        """
        from fdb_record_layer.metadata.index import FormerIndex, Index, IndexOptions, IndexType
        from fdb_record_layer.metadata.record_metadata import RecordMetaData, RecordType

        # Load header
        header = await self._load_header(tr)
        if header is None:
            return None

        # Load record types
        record_types: dict[str, RecordType] = {}
        record_types_range = self._subspace.range((MetaDataKeySpace.RECORD_TYPES,))

        async for key, value in tr.get_range(record_types_range.start, record_types_range.stop):
            data = json.loads(value.decode("utf-8"))
            name = data["name"]

            # Get descriptor from file_descriptor
            descriptor = None
            if file_descriptor and name in file_descriptor.message_types_by_name:
                descriptor = file_descriptor.message_types_by_name[name]

            if descriptor is not None:
                primary_key = self._serializer.deserialize_key_expression(data["primary_key"])
                record_types[name] = RecordType(
                    name=name,
                    descriptor=descriptor,
                    primary_key=primary_key,
                    since_version=data.get("since_version", 0),
                )

        # Load indexes
        indexes: dict[str, Index] = {}
        indexes_range = self._subspace.range((MetaDataKeySpace.INDEXES,))

        async for key, value in tr.get_range(indexes_range.start, indexes_range.stop):
            data = json.loads(value.decode("utf-8"))
            root_expression = self._serializer.deserialize_key_expression(data["root_expression"])
            indexes[data["name"]] = Index(
                name=data["name"],
                root_expression=root_expression,
                index_type=IndexType(data["index_type"]),
                record_types=data.get("record_types"),
                options=IndexOptions.from_dict(data.get("options", {})),
                added_version=data.get("added_version", 0),
                last_modified_version=data.get("last_modified_version", 0),
            )

        # Load former indexes
        former_indexes: list[FormerIndex] = []
        former_range = self._subspace.range((MetaDataKeySpace.FORMER_INDEXES,))

        async for key, value in tr.get_range(former_range.start, former_range.stop):
            data = json.loads(value.decode("utf-8"))
            former_indexes.append(
                FormerIndex(
                    name=data["name"],
                    added_version=data["added_version"],
                    removed_version=data["removed_version"],
                )
            )

        return RecordMetaData(
            record_types=record_types,
            indexes=indexes,
            version=header.version,
            file_descriptor=file_descriptor,
            former_indexes=former_indexes,
        )

    async def _load_header(self, tr: Any) -> MetaDataHeader | None:
        """Load the metadata header."""
        value = await tr.get(self._header_key())
        if value is None:
            return None
        return MetaDataHeader.from_bytes(bytes(value))

    async def get_version(self, tr: Any) -> int | None:
        """Get the current metadata version.

        Args:
            tr: FDB transaction.

        Returns:
            The version, or None if no metadata exists.
        """
        header = await self._load_header(tr)
        return header.version if header else None

    async def delete_metadata(self, tr: Any) -> None:
        """Delete all metadata from the store.

        Args:
            tr: FDB transaction.
        """
        range_obj = self._subspace.range()
        tr.clear_range(range_obj.start, range_obj.stop)


class CachedMetaDataStore:
    """Wrapper that adds caching to FDBMetaDataStore.

    Caches the loaded metadata to avoid repeated reads. The cache is
    invalidated when version changes.
    """

    def __init__(self, store: FDBMetaDataStore) -> None:
        self._store = store
        self._cached_metadata: RecordMetaData | None = None
        self._cached_version: int | None = None

    async def get_metadata(self, tr: Any, file_descriptor: Any) -> RecordMetaData | None:
        """Get metadata, using cache if available.

        Args:
            tr: FDB transaction.
            file_descriptor: Protobuf file descriptor.

        Returns:
            The metadata, or None if not found.
        """
        # Check if cache is valid
        current_version = await self._store.get_version(tr)

        if self._cached_metadata is not None and self._cached_version == current_version:
            return self._cached_metadata

        # Load fresh
        metadata = await self._store.load_metadata(tr, file_descriptor)
        if metadata is not None:
            self._cached_metadata = metadata
            self._cached_version = metadata.version

        return metadata

    def invalidate(self) -> None:
        """Invalidate the cache."""
        self._cached_metadata = None
        self._cached_version = None
