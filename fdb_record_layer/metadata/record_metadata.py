"""Record metadata definitions."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from google.protobuf.descriptor import Descriptor, FileDescriptor

    from fdb_record_layer.expressions.base import KeyExpression
    from fdb_record_layer.metadata.index import FormerIndex, Index


@dataclass
class RecordType:
    """Metadata for a record type.

    A record type corresponds to a protobuf message type and defines:
    - The message descriptor
    - The primary key expression
    - Type-specific indexes

    Attributes:
        name: The name of the record type (matches protobuf message name).
        descriptor: The protobuf message Descriptor.
        primary_key: Key expression defining the primary key.
        since_version: Metadata version when this type was added.
        indexes: Type-specific indexes (not including universal indexes).
    """

    name: str
    descriptor: Descriptor
    primary_key: KeyExpression
    since_version: int = 0
    indexes: list[Index] = field(default_factory=list)

    def get_field_names(self) -> set[str]:
        """Get all field names in this record type."""
        return {f.name for f in self.descriptor.fields}

    def has_field(self, field_name: str) -> bool:
        """Check if a field exists in this record type."""
        return field_name in self.get_field_names()

    def validate_primary_key(self) -> list[str]:
        """Validate the primary key expression against the descriptor."""
        return self.primary_key.validate(self.descriptor)


@dataclass
class RecordMetaData:
    """Complete schema definition for a record store.

    RecordMetaData contains all the information needed to:
    - Serialize and deserialize records
    - Maintain indexes
    - Execute queries

    This is typically created using RecordMetaDataBuilder.

    Attributes:
        record_types: Map of record type name to RecordType.
        indexes: Map of index name to Index (all indexes).
        version: The metadata version number.
        file_descriptor: The protobuf FileDescriptor containing all types.
        union_descriptor: Optional union message containing all record types.
        former_indexes: Indexes that have been removed.
    """

    record_types: dict[str, RecordType] = field(default_factory=dict)
    indexes: dict[str, Index] = field(default_factory=dict)
    version: int = 1
    file_descriptor: FileDescriptor | None = None
    union_descriptor: Descriptor | None = None
    former_indexes: list[FormerIndex] = field(default_factory=list)

    def get_record_type(self, name: str) -> RecordType:
        """Get a record type by name.

        Args:
            name: The record type name.

        Returns:
            The RecordType.

        Raises:
            KeyError: If the record type is not found.
        """
        if name not in self.record_types:
            from fdb_record_layer.core.exceptions import RecordTypeNotFoundException

            raise RecordTypeNotFoundException(name)
        return self.record_types[name]

    def get_index(self, name: str) -> Index:
        """Get an index by name.

        Args:
            name: The index name.

        Returns:
            The Index.

        Raises:
            KeyError: If the index is not found.
        """
        if name not in self.indexes:
            from fdb_record_layer.core.exceptions import IndexNotFoundException

            raise IndexNotFoundException(name)
        return self.indexes[name]

    def get_indexes_for_record_type(self, record_type_name: str) -> list[Index]:
        """Get all indexes that apply to a record type.

        This includes both type-specific indexes and universal indexes.

        Args:
            record_type_name: The record type name.

        Returns:
            List of applicable indexes.
        """
        result: list[Index] = []
        for index in self.indexes.values():
            if index.applies_to_record_type(record_type_name):
                result.append(index)
        return result

    def get_record_type_names(self) -> set[str]:
        """Get all record type names."""
        return set(self.record_types.keys())

    def get_index_names(self) -> set[str]:
        """Get all index names."""
        return set(self.indexes.keys())

    def has_record_type(self, name: str) -> bool:
        """Check if a record type exists."""
        return name in self.record_types

    def has_index(self, name: str) -> bool:
        """Check if an index exists."""
        return name in self.indexes

    def validate(self) -> list[str]:
        """Validate the entire metadata.

        Returns:
            List of validation errors, empty if valid.
        """
        errors: list[str] = []

        # Validate each record type
        for record_type in self.record_types.values():
            errors.extend([f"{record_type.name}: {e}" for e in record_type.validate_primary_key()])

        # Validate each index
        for index in self.indexes.values():
            if index.record_types:
                for rt_name in index.record_types:
                    if rt_name not in self.record_types:
                        errors.append(
                            f"Index {index.name} references unknown record type: {rt_name}"
                        )
                    else:
                        rt = self.record_types[rt_name]
                        index_errors = index.root_expression.validate(rt.descriptor)
                        errors.extend([f"{index.name}: {e}" for e in index_errors])

        return errors
