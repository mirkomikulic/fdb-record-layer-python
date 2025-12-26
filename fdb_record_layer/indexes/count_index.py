"""COUNT and SUM index maintainers for aggregate queries."""

from __future__ import annotations

import struct
from typing import TYPE_CHECKING, Any

from fdb_record_layer.cursors.base import ListCursor
from fdb_record_layer.indexes.maintainer import (
    IndexMaintainer,
    IndexScanRange,
    RecordLoader,
)

if TYPE_CHECKING:
    from fdb import Subspace, Transaction
    from google.protobuf.message import Message

    from fdb_record_layer.core.record import FDBStoredRecord
    from fdb_record_layer.cursors.base import RecordCursor
    from fdb_record_layer.metadata.index import Index
    from fdb_record_layer.metadata.record_metadata import RecordMetaData


class CountIndexMaintainer(IndexMaintainer):
    """Maintains a COUNT aggregate index.

    A COUNT index tracks the number of records matching each key.
    This enables efficient count queries without scanning all records.

    The index stores:
    - Key: (grouped_by_fields...)
    - Value: count as 8-byte little-endian integer

    Example:
        An index on "status" field would track count per status:
        - ("active",) -> 150
        - ("inactive",) -> 25
        - ("pending",) -> 10

    Use cases:
        - Get count of records by status
        - Get count of orders per customer
        - Get count of users by country
    """

    def __init__(
        self,
        index: Index,
        subspace: Subspace,
        meta_data: RecordMetaData,
    ) -> None:
        super().__init__(index, subspace, meta_data)

    async def update(
        self,
        tr: Transaction,
        record: Message,
        primary_key: tuple[Any, ...],
    ) -> None:
        """Increment the count for this record's key.

        Args:
            tr: The FDB transaction.
            record: The protobuf message.
            primary_key: The record's primary key.
        """
        # Get the grouping key from the record
        keys = self._index.root_expression.evaluate(record)

        for key in keys:
            count_key = self._subspace.pack(key)
            # Use atomic add to increment count
            tr.add(count_key, struct.pack("<q", 1))

    async def remove(
        self,
        tr: Transaction,
        record: Message,
        primary_key: tuple[Any, ...],
    ) -> None:
        """Decrement the count for this record's key.

        Args:
            tr: The FDB transaction.
            record: The protobuf message.
            primary_key: The record's primary key.
        """
        keys = self._index.root_expression.evaluate(record)

        for key in keys:
            count_key = self._subspace.pack(key)
            # Use atomic add with -1 to decrement count
            tr.add(count_key, struct.pack("<q", -1))

    async def scan(
        self,
        tr: Transaction,
        scan_range: IndexScanRange | None,
        continuation: bytes | None,
        limit: int,
        record_loader: RecordLoader,
    ) -> RecordCursor[FDBStoredRecord[Any]]:
        """Scan returns aggregate results, not individual records.

        For COUNT index, scanning returns the counts per key, not records.
        This method is not typically used directly - use get_count instead.
        """
        # COUNT indexes don't return records, return empty cursor
        return ListCursor([])

    def get_count(
        self,
        tr: Transaction,
        *key_values: Any,
    ) -> int:
        """Get the count for a specific key.

        Args:
            tr: The FDB transaction.
            key_values: The key values to look up.

        Returns:
            The count for this key.
        """
        count_key = self._subspace.pack(tuple(key_values))
        value = tr[count_key]

        if not value.present():
            return 0

        return struct.unpack("<q", bytes(value))[0]

    def get_count_range(
        self,
        tr: Transaction,
        scan_range: IndexScanRange | None = None,
    ) -> list[tuple[tuple[Any, ...], int]]:
        """Get counts for a range of keys.

        Args:
            tr: The FDB transaction.
            scan_range: Optional range to scan.

        Returns:
            List of (key, count) tuples.
        """
        if scan_range is None:
            # Full range
            start_key = self._subspace.range().start
            end_key = self._subspace.range().stop
        else:
            if scan_range.low is not None:
                start_key = self._subspace.pack(scan_range.low)
            else:
                start_key = self._subspace.range().start

            if scan_range.high is not None:
                end_key = self._subspace.pack(scan_range.high)
            else:
                end_key = self._subspace.range().stop

        results: list[tuple[tuple[Any, ...], int]] = []

        for key, value in tr.get_range(start_key, end_key):
            unpacked_key = self._subspace.unpack(key)
            count = struct.unpack("<q", bytes(value))[0]
            if count > 0:  # Skip zero counts
                results.append((unpacked_key, count))

        return results

    def get_total_count(self, tr: Transaction) -> int:
        """Get the total count across all keys.

        Args:
            tr: The FDB transaction.

        Returns:
            The sum of all counts.
        """
        total = 0
        start_key = self._subspace.range().start
        end_key = self._subspace.range().stop

        for _, value in tr.get_range(start_key, end_key):
            count = struct.unpack("<q", bytes(value))[0]
            total += count

        return total


class SumIndexMaintainer(IndexMaintainer):
    """Maintains a SUM aggregate index.

    A SUM index tracks the sum of a numeric field grouped by key.
    This enables efficient sum queries without scanning all records.

    The index stores:
    - Key: (grouped_by_fields...)
    - Value: sum as 8-byte little-endian integer or float

    Example:
        An index on ("customer_id",) summing "total" field would track:
        - (1001,) -> 5000.00
        - (1002,) -> 3250.50

    The index definition should have:
    - root_expression: The grouping key
    - value_expression: The field to sum (stored in index options)
    """

    def __init__(
        self,
        index: Index,
        subspace: Subspace,
        meta_data: RecordMetaData,
        value_field: str | None = None,
    ) -> None:
        super().__init__(index, subspace, meta_data)
        # Get value field from index options or parameter
        self._value_field = value_field or index.options.__dict__.get("value_field", "value")

    def _get_value(self, record: Message) -> int:
        """Extract the numeric value from the record.

        Args:
            record: The protobuf message.

        Returns:
            The numeric value to add to the sum.
        """
        if hasattr(record, self._value_field):
            value = getattr(record, self._value_field)
            if isinstance(value, (int, float)):
                return int(value)  # Convert to int for atomic operations
        return 0

    async def update(
        self,
        tr: Transaction,
        record: Message,
        primary_key: tuple[Any, ...],
    ) -> None:
        """Add the record's value to the sum.

        Args:
            tr: The FDB transaction.
            record: The protobuf message.
            primary_key: The record's primary key.
        """
        keys = self._index.root_expression.evaluate(record)
        value = self._get_value(record)

        for key in keys:
            sum_key = self._subspace.pack(key)
            tr.add(sum_key, struct.pack("<q", value))

    async def remove(
        self,
        tr: Transaction,
        record: Message,
        primary_key: tuple[Any, ...],
    ) -> None:
        """Subtract the record's value from the sum.

        Args:
            tr: The FDB transaction.
            record: The protobuf message.
            primary_key: The record's primary key.
        """
        keys = self._index.root_expression.evaluate(record)
        value = self._get_value(record)

        for key in keys:
            sum_key = self._subspace.pack(key)
            tr.add(sum_key, struct.pack("<q", -value))

    async def scan(
        self,
        tr: Transaction,
        scan_range: IndexScanRange | None,
        continuation: bytes | None,
        limit: int,
        record_loader: RecordLoader,
    ) -> RecordCursor[FDBStoredRecord[Any]]:
        """Scan returns aggregate results, not individual records."""
        return ListCursor([])

    def get_sum(
        self,
        tr: Transaction,
        *key_values: Any,
    ) -> int:
        """Get the sum for a specific key.

        Args:
            tr: The FDB transaction.
            key_values: The key values to look up.

        Returns:
            The sum for this key.
        """
        sum_key = self._subspace.pack(tuple(key_values))
        value = tr[sum_key]

        if not value.present():
            return 0

        return struct.unpack("<q", bytes(value))[0]

    def get_sum_range(
        self,
        tr: Transaction,
        scan_range: IndexScanRange | None = None,
    ) -> list[tuple[tuple[Any, ...], int]]:
        """Get sums for a range of keys.

        Args:
            tr: The FDB transaction.
            scan_range: Optional range to scan.

        Returns:
            List of (key, sum) tuples.
        """
        if scan_range is None:
            start_key = self._subspace.range().start
            end_key = self._subspace.range().stop
        else:
            if scan_range.low is not None:
                start_key = self._subspace.pack(scan_range.low)
            else:
                start_key = self._subspace.range().start

            if scan_range.high is not None:
                end_key = self._subspace.pack(scan_range.high)
            else:
                end_key = self._subspace.range().stop

        results: list[tuple[tuple[Any, ...], int]] = []

        for key, value in tr.get_range(start_key, end_key):
            unpacked_key = self._subspace.unpack(key)
            sum_value = struct.unpack("<q", bytes(value))[0]
            results.append((unpacked_key, sum_value))

        return results

    def get_total_sum(self, tr: Transaction) -> int:
        """Get the total sum across all keys.

        Args:
            tr: The FDB transaction.

        Returns:
            The sum of all sums.
        """
        total = 0
        start_key = self._subspace.range().start
        end_key = self._subspace.range().stop

        for _, value in tr.get_range(start_key, end_key):
            sum_value = struct.unpack("<q", bytes(value))[0]
            total += sum_value

        return total


class MinMaxIndexMaintainer(IndexMaintainer):
    """Maintains MIN_EVER or MAX_EVER aggregate indexes.

    These indexes track the minimum or maximum value ever seen,
    even after records are deleted. Useful for high watermarks.

    Note: These values only increase (for MAX) or decrease (for MIN).
    Deleting a record doesn't change the stored value.
    """

    def __init__(
        self,
        index: Index,
        subspace: Subspace,
        meta_data: RecordMetaData,
        track_max: bool = True,
        value_field: str | None = None,
    ) -> None:
        super().__init__(index, subspace, meta_data)
        self._track_max = track_max
        self._value_field = value_field or "value"

    def _get_value(self, record: Message) -> int | None:
        """Extract the numeric value from the record."""
        if hasattr(record, self._value_field):
            value = getattr(record, self._value_field)
            if isinstance(value, (int, float)):
                return int(value)
        return None

    async def update(
        self,
        tr: Transaction,
        record: Message,
        primary_key: tuple[Any, ...],
    ) -> None:
        """Update min/max if this record's value is more extreme."""
        keys = self._index.root_expression.evaluate(record)
        value = self._get_value(record)

        if value is None:
            return

        for key in keys:
            minmax_key = self._subspace.pack(key)
            current = tr[minmax_key]

            should_update = False
            if not current.present():
                should_update = True
            else:
                current_value = struct.unpack("<q", bytes(current))[0]
                if self._track_max:
                    should_update = value > current_value
                else:
                    should_update = value < current_value

            if should_update:
                tr.set(minmax_key, struct.pack("<q", value))

    async def remove(
        self,
        tr: Transaction,
        record: Message,
        primary_key: tuple[Any, ...],
    ) -> None:
        """MIN_EVER and MAX_EVER don't change on record deletion."""
        # Intentionally do nothing - these track "ever" values
        pass

    async def scan(
        self,
        tr: Transaction,
        scan_range: IndexScanRange | None,
        continuation: bytes | None,
        limit: int,
        record_loader: RecordLoader,
    ) -> RecordCursor[FDBStoredRecord[Any]]:
        """Scan returns aggregate results, not individual records."""
        return ListCursor([])

    def get_value(
        self,
        tr: Transaction,
        *key_values: Any,
    ) -> int | None:
        """Get the min/max value for a specific key.

        Args:
            tr: The FDB transaction.
            key_values: The key values to look up.

        Returns:
            The min or max value, or None if no value exists.
        """
        minmax_key = self._subspace.pack(tuple(key_values))
        value = tr[minmax_key]

        if not value.present():
            return None

        return struct.unpack("<q", bytes(value))[0]
