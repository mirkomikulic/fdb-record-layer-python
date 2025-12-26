"""VALUE index maintainer implementation."""

from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING, Any

from fdb_record_layer.cursors.base import ListCursor, RecordCursor
from fdb_record_layer.cursors.result import RecordCursorContinuation
from fdb_record_layer.indexes.maintainer import IndexMaintainer, IndexScanRange, RecordLoader

if TYPE_CHECKING:
    from fdb import Subspace, Transaction
    from google.protobuf.message import Message

    from fdb_record_layer.core.record import FDBStoredRecord
    from fdb_record_layer.metadata.index import Index
    from fdb_record_layer.metadata.record_metadata import RecordMetaData


class ValueIndexMaintainer(IndexMaintainer):
    """Maintains standard VALUE indexes.

    A VALUE index maps index key values to primary keys, enabling
    efficient lookup and range queries on indexed fields.

    Index entry format:
        Key: (index_value..., record_type, primary_key...)
        Value: empty bytes
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
        """Add index entries for a record."""
        full_keys = self.get_index_key(record, primary_key)

        for full_key in full_keys:
            key_bytes = self._subspace.pack(full_key)
            # VALUE indexes store empty value - the key contains all info
            tr.set(key_bytes, b"")

    async def remove(
        self,
        tr: Transaction,
        record: Message,
        primary_key: tuple[Any, ...],
    ) -> None:
        """Remove index entries for a record."""
        full_keys = self.get_index_key(record, primary_key)

        for full_key in full_keys:
            key_bytes = self._subspace.pack(full_key)
            tr.clear(key_bytes)

    async def scan(
        self,
        tr: Transaction,
        scan_range: IndexScanRange | None,
        continuation: bytes | None,
        limit: int,
        record_loader: RecordLoader,
    ) -> RecordCursor[FDBStoredRecord[Any]]:
        """Scan the index and return matching records."""
        # Determine key range
        if scan_range:
            begin_key = self._get_range_begin(scan_range)
            end_key = self._get_range_end(scan_range)
        else:
            begin_key = self._subspace.range().start
            end_key = self._subspace.range().stop

        # Apply continuation
        if continuation:
            begin_key = continuation

        # Perform scan
        loop = asyncio.get_event_loop()
        fetch_limit = limit + 1 if limit else 0

        # FDB Python client is synchronous
        def do_scan() -> list[tuple[bytes, bytes]]:
            return list(tr.get_range(begin_key, end_key, limit=fetch_limit))

        entries = await loop.run_in_executor(None, do_scan)

        # Process results
        results: list[FDBStoredRecord[Any]] = []
        has_more = False
        last_key: bytes | None = None

        for i, (key, _value) in enumerate(entries):
            if limit and len(results) >= limit:
                has_more = True
                break

            # Unpack the key
            unpacked = self._subspace.unpack(key)

            # Extract components: (index_values..., record_type, primary_key...)
            index_columns = self._index.root_expression.get_column_size()
            record_type_name = unpacked[index_columns]
            primary_key = tuple(unpacked[index_columns + 1 :])

            # Load the record
            record = record_loader(record_type_name, primary_key)
            if record is not None:
                results.append(record)
                last_key = key

        # Create continuation
        next_continuation: RecordCursorContinuation | None = None
        if has_more and last_key is not None:
            # Continuation is the last key + 1 byte
            next_continuation = RecordCursorContinuation.from_bytes(last_key + b"\x00")

        return ListCursor(results, next_continuation)

    def _get_range_begin(self, scan_range: IndexScanRange) -> bytes:
        """Get the begin key for a scan range."""
        if scan_range.low is None:
            return self._subspace.range().start

        key_bytes = self._subspace.pack(scan_range.low)
        if not scan_range.low_inclusive:
            # Exclusive - add a byte to skip exact match
            key_bytes = key_bytes + b"\x00"
        return key_bytes

    def _get_range_end(self, scan_range: IndexScanRange) -> bytes:
        """Get the end key for a scan range."""
        if scan_range.high is None:
            return self._subspace.range().stop

        key_bytes = self._subspace.pack(scan_range.high)
        if scan_range.high_inclusive:
            # Inclusive - add 0xFF to include all with this prefix
            key_bytes = key_bytes + b"\xff"
        return key_bytes

    async def scan_entries(
        self,
        tr: Transaction,
        scan_range: IndexScanRange | None = None,
        limit: int = 0,
    ) -> list[tuple[tuple[Any, ...], str, tuple[Any, ...]]]:
        """Scan index entries without loading records.

        Returns tuples of (index_key, record_type, primary_key).

        Useful for index-only queries where the record data isn't needed.
        """
        # Determine key range
        if scan_range:
            begin_key = self._get_range_begin(scan_range)
            end_key = self._get_range_end(scan_range)
        else:
            begin_key = self._subspace.range().start
            end_key = self._subspace.range().stop

        loop = asyncio.get_event_loop()

        def do_scan() -> list[tuple[bytes, bytes]]:
            return list(tr.get_range(begin_key, end_key, limit=limit if limit else 0))

        entries = await loop.run_in_executor(None, do_scan)

        results = []
        index_columns = self._index.root_expression.get_column_size()

        for key, _value in entries:
            unpacked = self._subspace.unpack(key)
            index_key = tuple(unpacked[:index_columns])
            record_type_name = unpacked[index_columns]
            primary_key = tuple(unpacked[index_columns + 1 :])
            results.append((index_key, record_type_name, primary_key))

        return results
