"""Builder for RecordMetaData."""

from __future__ import annotations

from typing import TYPE_CHECKING

from fdb_record_layer.metadata.index import Index, IndexOptions, IndexType
from fdb_record_layer.metadata.record_metadata import RecordMetaData, RecordType

if TYPE_CHECKING:
    from google.protobuf.descriptor import Descriptor, FileDescriptor

    from fdb_record_layer.expressions.base import KeyExpression


class RecordMetaDataBuilder:
    """Fluent builder for constructing RecordMetaData.

    Example:
        >>> from my_proto_pb2 import DESCRIPTOR
        >>> from fdb_record_layer.expressions import field, concat
        >>>
        >>> metadata = (
        ...     RecordMetaDataBuilder(DESCRIPTOR)
        ...     .set_record_type("Person", primary_key=field("id"))
        ...     .add_index("Person", "email_idx", field("email"))
        ...     .add_index("Person", "name_age_idx", concat(field("name"), field("age")))
        ...     .build()
        ... )
    """

    def __init__(self, file_descriptor: FileDescriptor) -> None:
        """Initialize the builder with a protobuf FileDescriptor.

        Args:
            file_descriptor: The protobuf file descriptor containing message types.
        """
        self._file_descriptor = file_descriptor
        self._record_types: dict[str, RecordType] = {}
        self._indexes: dict[str, Index] = {}
        self._version = 1
        self._union_descriptor: Descriptor | None = None

    def set_version(self, version: int) -> RecordMetaDataBuilder:
        """Set the metadata version.

        Args:
            version: The version number.

        Returns:
            self for chaining.
        """
        self._version = version
        return self

    def set_record_type(
        self,
        name: str,
        primary_key: KeyExpression,
        since_version: int | None = None,
    ) -> RecordMetaDataBuilder:
        """Define a record type.

        Args:
            name: The record type name (must match a protobuf message name).
            primary_key: Key expression for the primary key.
            since_version: Optional version when this type was added.

        Returns:
            self for chaining.

        Raises:
            ValueError: If the message type is not found.
        """
        descriptor = self._find_message_type(name)
        if descriptor is None:
            raise ValueError(
                f"Message type '{name}' not found in file descriptor '{self._file_descriptor.name}'"
            )

        self._record_types[name] = RecordType(
            name=name,
            descriptor=descriptor,
            primary_key=primary_key,
            since_version=since_version if since_version is not None else self._version,
        )
        return self

    def add_index(
        self,
        record_type: str,
        index_name: str,
        root_expression: KeyExpression,
        index_type: IndexType = IndexType.VALUE,
        options: IndexOptions | None = None,
    ) -> RecordMetaDataBuilder:
        """Add an index for a specific record type.

        Args:
            record_type: The record type this index applies to.
            index_name: Unique name for the index.
            root_expression: Key expression defining what to index.
            index_type: The type of index.
            options: Optional index options.

        Returns:
            self for chaining.
        """
        if index_name in self._indexes:
            raise ValueError(f"Index '{index_name}' already exists")

        self._indexes[index_name] = Index(
            name=index_name,
            root_expression=root_expression,
            index_type=index_type,
            record_types=[record_type],
            options=options or IndexOptions(),
            added_version=self._version,
        )
        return self

    def add_multi_type_index(
        self,
        record_types: list[str],
        index_name: str,
        root_expression: KeyExpression,
        index_type: IndexType = IndexType.VALUE,
        options: IndexOptions | None = None,
    ) -> RecordMetaDataBuilder:
        """Add an index that applies to multiple record types.

        Args:
            record_types: List of record type names.
            index_name: Unique name for the index.
            root_expression: Key expression defining what to index.
            index_type: The type of index.
            options: Optional index options.

        Returns:
            self for chaining.
        """
        if index_name in self._indexes:
            raise ValueError(f"Index '{index_name}' already exists")

        self._indexes[index_name] = Index(
            name=index_name,
            root_expression=root_expression,
            index_type=index_type,
            record_types=record_types,
            options=options or IndexOptions(),
            added_version=self._version,
        )
        return self

    def add_universal_index(
        self,
        index_name: str,
        root_expression: KeyExpression,
        index_type: IndexType = IndexType.VALUE,
        options: IndexOptions | None = None,
    ) -> RecordMetaDataBuilder:
        """Add an index that applies to all record types.

        Args:
            index_name: Unique name for the index.
            root_expression: Key expression defining what to index.
            index_type: The type of index.
            options: Optional index options.

        Returns:
            self for chaining.
        """
        if index_name in self._indexes:
            raise ValueError(f"Index '{index_name}' already exists")

        self._indexes[index_name] = Index(
            name=index_name,
            root_expression=root_expression,
            index_type=index_type,
            record_types=None,  # Universal
            options=options or IndexOptions(),
            added_version=self._version,
        )
        return self

    def add_count_index(
        self,
        record_type: str,
        index_name: str,
        group_by: KeyExpression,
    ) -> RecordMetaDataBuilder:
        """Add a COUNT index for counting records by key.

        Args:
            record_type: The record type this index applies to.
            index_name: Unique name for the index.
            group_by: Key expression for grouping counts.

        Returns:
            self for chaining.

        Example:
            >>> # Count orders by status
            >>> builder.add_count_index("Order", "orders_by_status", field("status"))
        """
        return self.add_index(record_type, index_name, group_by, IndexType.COUNT)

    def add_sum_index(
        self,
        record_type: str,
        index_name: str,
        group_by: KeyExpression,
    ) -> RecordMetaDataBuilder:
        """Add a SUM index for summing a numeric field by key.

        Args:
            record_type: The record type this index applies to.
            index_name: Unique name for the index.
            group_by: Key expression for grouping sums.

        Returns:
            self for chaining.
        """
        return self.add_index(record_type, index_name, group_by, IndexType.SUM)

    def add_rank_index(
        self,
        record_type: str,
        index_name: str,
        score_expression: KeyExpression,
    ) -> RecordMetaDataBuilder:
        """Add a RANK index for leaderboard queries.

        Args:
            record_type: The record type this index applies to.
            index_name: Unique name for the index.
            score_expression: Key expression for the score/ranking field.

        Returns:
            self for chaining.

        Example:
            >>> # Rank players by score
            >>> builder.add_rank_index("Player", "player_scores", field("score"))
        """
        return self.add_index(record_type, index_name, score_expression, IndexType.RANK)

    def add_text_index(
        self,
        record_type: str,
        index_name: str,
        text_field: KeyExpression,
    ) -> RecordMetaDataBuilder:
        """Add a TEXT index for full-text search.

        Args:
            record_type: The record type this index applies to.
            index_name: Unique name for the index.
            text_field: Key expression for the text field to index.

        Returns:
            self for chaining.

        Example:
            >>> # Full-text search on description
            >>> builder.add_text_index("Product", "product_search", field("description"))
        """
        return self.add_index(record_type, index_name, text_field, IndexType.TEXT)

    def set_union_descriptor(self, name: str) -> RecordMetaDataBuilder:
        """Set the union message type that contains all record types.

        Args:
            name: The name of the union message type.

        Returns:
            self for chaining.
        """
        self._union_descriptor = self._find_message_type(name)
        return self

    def build(self) -> RecordMetaData:
        """Build the RecordMetaData.

        Returns:
            The constructed RecordMetaData.

        Raises:
            ValueError: If validation fails.
        """
        metadata = RecordMetaData(
            record_types=self._record_types.copy(),
            indexes=self._indexes.copy(),
            version=self._version,
            file_descriptor=self._file_descriptor,
            union_descriptor=self._union_descriptor,
        )

        # Validate
        errors = metadata.validate()
        if errors:
            raise ValueError(f"Invalid metadata: {'; '.join(errors)}")

        return metadata

    def _find_message_type(self, name: str) -> Descriptor | None:
        """Find a message type by name in the file descriptor."""
        # Check top-level messages
        if name in self._file_descriptor.message_types_by_name:
            return self._file_descriptor.message_types_by_name[name]

        # Check nested messages (simplified - only one level deep)
        for msg in self._file_descriptor.message_types_by_name.values():
            for nested in msg.nested_types:
                if nested.name == name:
                    return nested

        return None


def build_record_metadata(file_descriptor: FileDescriptor) -> RecordMetaDataBuilder:
    """Create a new RecordMetaDataBuilder.

    Args:
        file_descriptor: The protobuf file descriptor.

    Returns:
        A new builder.

    Example:
        >>> from my_proto_pb2 import DESCRIPTOR
        >>> metadata = build_record_metadata(DESCRIPTOR).set_record_type(...).build()
    """
    return RecordMetaDataBuilder(file_descriptor)
