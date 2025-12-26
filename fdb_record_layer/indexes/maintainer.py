"""Index maintainer base class and protocols."""

from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import Callable
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from fdb import Subspace, Transaction
    from google.protobuf.message import Message

    from fdb_record_layer.core.record import FDBStoredRecord
    from fdb_record_layer.cursors.base import RecordCursor
    from fdb_record_layer.metadata.index import Index
    from fdb_record_layer.metadata.record_metadata import RecordMetaData


@dataclass
class IndexScanRange:
    """Defines a range for scanning an index.

    Attributes:
        low: The lower bound of the range (inclusive by default).
        high: The upper bound of the range (exclusive by default).
        low_inclusive: Whether the low bound is inclusive.
        high_inclusive: Whether the high bound is inclusive.
    """

    low: tuple[Any, ...] | None = None
    high: tuple[Any, ...] | None = None
    low_inclusive: bool = True
    high_inclusive: bool = False

    @classmethod
    def equals(cls, *values: Any) -> IndexScanRange:
        """Create a range for an exact match.

        Args:
            *values: The values to match.

        Returns:
            An IndexScanRange for equality.
        """
        key = tuple(values)
        return cls(low=key, high=key, low_inclusive=True, high_inclusive=True)

    @classmethod
    def prefix(cls, *values: Any) -> IndexScanRange:
        """Create a range for a prefix match.

        Args:
            *values: The prefix values.

        Returns:
            An IndexScanRange for the prefix.
        """
        return cls(low=tuple(values), high=None)

    @classmethod
    def greater_than(cls, *values: Any, inclusive: bool = False) -> IndexScanRange:
        """Create a range for greater than.

        Args:
            *values: The bound values.
            inclusive: Whether to include the bound.

        Returns:
            An IndexScanRange for greater than.
        """
        return cls(low=tuple(values), low_inclusive=inclusive)

    @classmethod
    def less_than(cls, *values: Any, inclusive: bool = False) -> IndexScanRange:
        """Create a range for less than.

        Args:
            *values: The bound values.
            inclusive: Whether to include the bound.

        Returns:
            An IndexScanRange for less than.
        """
        return cls(high=tuple(values), high_inclusive=inclusive)

    @classmethod
    def between(
        cls,
        low: tuple[Any, ...],
        high: tuple[Any, ...],
        low_inclusive: bool = True,
        high_inclusive: bool = False,
    ) -> IndexScanRange:
        """Create a range between two bounds.

        Args:
            low: The lower bound.
            high: The upper bound.
            low_inclusive: Whether the low bound is inclusive.
            high_inclusive: Whether the high bound is inclusive.

        Returns:
            An IndexScanRange for the range.
        """
        return cls(
            low=low,
            high=high,
            low_inclusive=low_inclusive,
            high_inclusive=high_inclusive,
        )


# Type alias for record loader function
RecordLoader = Callable[
    [str, tuple[Any, ...]],
    "FDBStoredRecord[Any] | None",
]


class IndexMaintainer(ABC):
    """Abstract base for index maintenance.

    An IndexMaintainer is responsible for:
    - Adding index entries when records are created/updated
    - Removing index entries when records are deleted/updated
    - Scanning the index for query execution

    Each index type (VALUE, COUNT, RANK, etc.) has its own maintainer.
    """

    def __init__(
        self,
        index: Index,
        subspace: Subspace,
        meta_data: RecordMetaData,
    ) -> None:
        """Initialize the maintainer.

        Args:
            index: The index metadata.
            subspace: The subspace for storing index data.
            meta_data: The record metadata.
        """
        self._index = index
        self._subspace = subspace
        self._meta_data = meta_data

    @property
    def index(self) -> Index:
        """Get the index metadata."""
        return self._index

    @property
    def subspace(self) -> Subspace:
        """Get the index subspace."""
        return self._subspace

    @abstractmethod
    async def update(
        self,
        tr: Transaction,
        record: Message,
        primary_key: tuple[Any, ...],
    ) -> None:
        """Add index entries for a record.

        Called when a record is created or updated.

        Args:
            tr: The FDB transaction.
            record: The protobuf message.
            primary_key: The record's primary key.
        """
        pass

    @abstractmethod
    async def remove(
        self,
        tr: Transaction,
        record: Message,
        primary_key: tuple[Any, ...],
    ) -> None:
        """Remove index entries for a record.

        Called when a record is deleted or updated (before adding new entries).

        Args:
            tr: The FDB transaction.
            record: The protobuf message.
            primary_key: The record's primary key.
        """
        pass

    @abstractmethod
    async def scan(
        self,
        tr: Transaction,
        scan_range: IndexScanRange | None,
        continuation: bytes | None,
        limit: int,
        record_loader: RecordLoader,
    ) -> RecordCursor[FDBStoredRecord[Any]]:
        """Scan the index and return matching records.

        Args:
            tr: The FDB transaction.
            scan_range: The range to scan.
            continuation: Optional continuation for resuming.
            limit: Maximum number of results (0 = unlimited).
            record_loader: Function to load records from primary keys.

        Returns:
            A cursor over matching records.
        """
        pass

    def get_index_key(
        self,
        record: Message,
        primary_key: tuple[Any, ...],
    ) -> list[tuple[Any, ...]]:
        """Compute the index keys for a record.

        Args:
            record: The protobuf message.
            primary_key: The record's primary key.

        Returns:
            List of index key tuples.
        """
        index_keys = self._index.root_expression.evaluate(record)
        record_type_name = record.DESCRIPTOR.name

        # Append record type and primary key to each index key
        result = []
        for index_key in index_keys:
            full_key = index_key + (record_type_name,) + primary_key
            result.append(full_key)
        return result
