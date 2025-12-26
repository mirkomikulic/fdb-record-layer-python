"""Record wrapper types for stored records."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, Generic, TypeVar

if TYPE_CHECKING:
    from google.protobuf.message import Message

    from fdb_record_layer.metadata.record_metadata import RecordType

# Type variable for the record message type
M = TypeVar("M", bound="Message")


@dataclass(frozen=True)
class FDBStoredRecord(Generic[M]):
    """A record that has been stored in or loaded from the database.

    This wrapper provides:
    - The primary key used to store the record
    - The record type metadata
    - The actual protobuf message
    - Optional version information

    Attributes:
        primary_key: The tuple of primary key values for this record.
        record: The protobuf message containing the record data.
        record_type: The RecordType metadata for this record.
        version: Optional version stamp from FDB for optimistic concurrency.
    """

    primary_key: tuple[Any, ...]
    record: M
    record_type: RecordType
    version: int | None = None

    @property
    def record_type_name(self) -> str:
        """Get the name of the record type."""
        return self.record_type.name

    def get_field(self, field_name: str) -> Any:
        """Get a field value from the record.

        Args:
            field_name: The name of the field to get.

        Returns:
            The field value, or None if not set.
        """
        if hasattr(self.record, field_name):
            return getattr(self.record, field_name)
        return None

    def has_field(self, field_name: str) -> bool:
        """Check if the record has a field set.

        Args:
            field_name: The name of the field to check.

        Returns:
            True if the field exists and is set.
        """
        return hasattr(self.record, field_name) and self.record.HasField(field_name)


@dataclass(frozen=True)
class FDBQueriedRecord(Generic[M]):
    """A record returned from a query, possibly with additional context.

    This extends FDBStoredRecord with query-specific information like
    which index was used to find it.

    Attributes:
        stored_record: The underlying stored record.
        index_name: The name of the index used to find this record, if any.
        index_entry: The index key values that matched, if any.
    """

    stored_record: FDBStoredRecord[M]
    index_name: str | None = None
    index_entry: tuple[Any, ...] | None = None

    @property
    def primary_key(self) -> tuple[Any, ...]:
        """Get the primary key."""
        return self.stored_record.primary_key

    @property
    def record(self) -> M:
        """Get the record message."""
        return self.stored_record.record

    @property
    def record_type(self) -> RecordType:
        """Get the record type metadata."""
        return self.stored_record.record_type

    @property
    def record_type_name(self) -> str:
        """Get the record type name."""
        return self.stored_record.record_type_name


@dataclass(frozen=True)
class IndexEntry:
    """An entry in an index pointing to a record.

    Attributes:
        index_name: The name of the index.
        key: The index key values.
        primary_key: The primary key of the referenced record.
        record_type_name: The name of the record type.
        value: Optional value stored with the index entry (for aggregate indexes).
    """

    index_name: str
    key: tuple[Any, ...]
    primary_key: tuple[Any, ...]
    record_type_name: str
    value: bytes | None = None
