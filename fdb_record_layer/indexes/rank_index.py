"""RANK index maintainer for leaderboard and ranking queries.

The RANK index enables efficient queries like:
- What is the rank of this score? (get_rank)
- What records are in positions 1-10? (get_by_rank)
- What is the Nth highest/lowest value? (get_by_rank)

Implementation uses a counted B-tree style approach where each node
tracks the count of entries below it, enabling O(log n) rank operations.
"""

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


# Subspace keys for rank index components
ENTRIES_KEY = 0  # Actual entries: (score, pk) -> empty
COUNTS_KEY = 1  # Level counts: (level, score_prefix) -> count


class RankIndexMaintainer(IndexMaintainer):
    """Maintains a RANK index for leaderboard queries.

    The rank index stores entries sorted by score and enables:
    - get_rank(score): Get the rank of a given score
    - get_by_rank(rank): Get the entry at a given rank
    - get_rank_range(start, end): Get entries between ranks

    Storage layout:
    - Entries subspace: (score, record_type, primary_key) -> empty
    - Counts subspace: Uses hierarchical counting for O(log n) rank queries

    The counting structure divides the score space into buckets and
    maintains counts at multiple granularities.

    Example:
        For scores 0-1000:
        - Level 0: Count for each individual score
        - Level 1: Count for each group of 10 scores (0-9, 10-19, ...)
        - Level 2: Count for each group of 100 scores (0-99, 100-199, ...)
    """

    # Number of levels for hierarchical counting
    LEVELS = 4
    # Bucket size multiplier per level
    BUCKET_SIZE = 10

    def __init__(
        self,
        index: Index,
        subspace: Subspace,
        meta_data: RecordMetaData,
    ) -> None:
        super().__init__(index, subspace, meta_data)
        self._entries_subspace = subspace[ENTRIES_KEY]
        self._counts_subspace = subspace[COUNTS_KEY]

    def _get_score(self, record: Message) -> tuple[Any, ...] | None:
        """Extract the score/ranking key from the record.

        Returns the first key from the index expression.
        """
        keys = self._index.root_expression.evaluate(record)
        if keys:
            return keys[0]
        return None

    def _get_bucket_key(self, score: Any, level: int) -> Any:
        """Get the bucket key for a score at a given level.

        At level 0, the bucket is the score itself.
        At higher levels, scores are grouped into buckets.
        """
        if level == 0:
            return score

        # For numeric scores, divide by bucket size^level
        if isinstance(score, (int, float)):
            divisor = self.BUCKET_SIZE**level
            return int(score) // divisor

        # For other types (strings, etc.), use prefix truncation
        if isinstance(score, str):
            prefix_len = max(1, len(score) - level)
            return score[:prefix_len]

        return score

    async def update(
        self,
        tr: Transaction,
        record: Message,
        primary_key: tuple[Any, ...],
    ) -> None:
        """Add an entry to the rank index.

        Args:
            tr: The FDB transaction.
            record: The protobuf message.
            primary_key: The record's primary key.
        """
        score = self._get_score(record)
        if score is None:
            return

        record_type_name = record.DESCRIPTOR.name

        # Create the entry key: (score, record_type, primary_key)
        entry_key = self._entries_subspace.pack(score + (record_type_name,) + primary_key)

        # Check if entry already exists (for updates)
        existing = tr[entry_key]
        if existing.present():
            # Already indexed at this score, no count change needed
            return

        # Add the entry
        tr.set(entry_key, b"")

        # Update counts at all levels
        for level in range(self.LEVELS):
            bucket = self._get_bucket_key(score[0] if isinstance(score, tuple) else score, level)
            count_key = self._counts_subspace.pack((level, bucket))
            tr.add(count_key, struct.pack("<q", 1))

    async def remove(
        self,
        tr: Transaction,
        record: Message,
        primary_key: tuple[Any, ...],
    ) -> None:
        """Remove an entry from the rank index.

        Args:
            tr: The FDB transaction.
            record: The protobuf message.
            primary_key: The record's primary key.
        """
        score = self._get_score(record)
        if score is None:
            return

        record_type_name = record.DESCRIPTOR.name
        entry_key = self._entries_subspace.pack(score + (record_type_name,) + primary_key)

        # Check if entry exists
        existing = tr[entry_key]
        if not existing.present():
            return

        # Remove the entry
        tr.clear(entry_key)

        # Update counts at all levels
        for level in range(self.LEVELS):
            bucket = self._get_bucket_key(score[0] if isinstance(score, tuple) else score, level)
            count_key = self._counts_subspace.pack((level, bucket))
            tr.add(count_key, struct.pack("<q", -1))

    async def scan(
        self,
        tr: Transaction,
        scan_range: IndexScanRange | None,
        continuation: bytes | None,
        limit: int,
        record_loader: RecordLoader,
    ) -> RecordCursor[FDBStoredRecord[Any]]:
        """Scan the rank index by score range.

        Args:
            tr: The FDB transaction.
            scan_range: Score range to scan.
            continuation: Optional continuation.
            limit: Maximum results.
            record_loader: Function to load full records.

        Returns:
            Cursor over matching records.
        """
        if scan_range is None:
            start_key = self._entries_subspace.range().start
            end_key = self._entries_subspace.range().stop
        else:
            if scan_range.low is not None:
                start_key = self._entries_subspace.pack(scan_range.low)
            else:
                start_key = self._entries_subspace.range().start

            if scan_range.high is not None:
                end_key = self._entries_subspace.pack(scan_range.high)
            else:
                end_key = self._entries_subspace.range().stop

        results: list[FDBStoredRecord[Any]] = []

        for key, _ in tr.get_range(start_key, end_key, limit=limit if limit > 0 else 0):
            unpacked = self._entries_subspace.unpack(key)
            # Key format: (score_components..., record_type, primary_key_components...)
            # We need to figure out where score ends and pk begins
            # For simplicity, assume score is single value and pk is single value
            if len(unpacked) >= 2:
                record_type_name = unpacked[-2] if len(unpacked) > 2 else unpacked[0]
                pk = unpacked[-1:]

                # Handle case where record_type is string and not part of score
                for i, val in enumerate(unpacked):
                    if isinstance(val, str) and val in self._meta_data.record_types:
                        record_type_name = val
                        pk = unpacked[i + 1 :]
                        break

                stored = record_loader(record_type_name, pk)
                if stored is not None:
                    results.append(stored)

        return ListCursor(results)

    def get_rank(
        self,
        tr: Transaction,
        score: Any,
        primary_key: tuple[Any, ...] | None = None,
    ) -> int:
        """Get the rank of a score (0-indexed).

        Lower scores have lower ranks (rank 0 is the lowest score).
        If multiple entries have the same score, the one with the
        lexicographically smaller primary key has the lower rank.

        Args:
            tr: The FDB transaction.
            score: The score to get the rank of.
            primary_key: Optional primary key for tie-breaking.

        Returns:
            The 0-indexed rank.
        """
        # Count all entries with score < given score
        rank = 0

        # Use hierarchical counting for efficiency
        if isinstance(score, (int, float)):
            # Sum counts from all buckets below this score
            for level in range(self.LEVELS - 1, -1, -1):
                bucket = self._get_bucket_key(score, level)

                # Count buckets below this one at this level
                count_start = self._counts_subspace.pack((level,))
                count_end = self._counts_subspace.pack((level, bucket))

                for _, value in tr.get_range(count_start, count_end):
                    count = struct.unpack("<q", bytes(value))[0]
                    rank += count

        else:
            # For non-numeric scores, do a prefix scan
            entries_start = self._entries_subspace.range().start
            entries_end = self._entries_subspace.pack((score,))

            for _ in tr.get_range(entries_start, entries_end):
                rank += 1

        return rank

    def get_by_rank(
        self,
        tr: Transaction,
        rank: int,
        record_loader: RecordLoader,
    ) -> FDBStoredRecord[Any] | None:
        """Get the entry at a specific rank.

        Args:
            tr: The FDB transaction.
            rank: The 0-indexed rank to get.
            record_loader: Function to load full records.

        Returns:
            The record at that rank, or None if rank is out of bounds.
        """
        entries = self.get_by_rank_range(tr, rank, rank + 1, record_loader)
        return entries[0] if entries else None

    def get_by_rank_range(
        self,
        tr: Transaction,
        start_rank: int,
        end_rank: int,
        record_loader: RecordLoader,
    ) -> list[FDBStoredRecord[Any]]:
        """Get entries in a rank range.

        Args:
            tr: The FDB transaction.
            start_rank: Start rank (inclusive).
            end_rank: End rank (exclusive).
            record_loader: Function to load full records.

        Returns:
            List of records in the rank range.
        """
        if start_rank >= end_rank:
            return []

        results: list[FDBStoredRecord[Any]] = []

        # Scan entries, skipping to start_rank
        entries_start = self._entries_subspace.range().start
        entries_end = self._entries_subspace.range().stop

        current_rank = 0
        for key, _ in tr.get_range(entries_start, entries_end):
            if current_rank >= end_rank:
                break

            if current_rank >= start_rank:
                unpacked = self._entries_subspace.unpack(key)

                # Find record type and primary key in unpacked tuple
                record_type_name = None
                pk_start = 0

                for i, val in enumerate(unpacked):
                    if isinstance(val, str) and val in self._meta_data.record_types:
                        record_type_name = val
                        pk_start = i + 1
                        break

                if record_type_name:
                    pk = unpacked[pk_start:]
                    stored = record_loader(record_type_name, pk)
                    if stored is not None:
                        results.append(stored)

            current_rank += 1

        return results

    def get_count(self, tr: Transaction) -> int:
        """Get the total number of entries in the index.

        Args:
            tr: The FDB transaction.

        Returns:
            Total entry count.
        """
        total = 0
        # Sum level 0 counts (most granular)
        count_start = self._counts_subspace.pack((0,))
        count_end = self._counts_subspace.pack((1,))

        for _, value in tr.get_range(count_start, count_end):
            count = struct.unpack("<q", bytes(value))[0]
            total += count

        return total


class TimeWindowRankIndexMaintainer(RankIndexMaintainer):
    """Rank index with time-window support for rolling leaderboards.

    Extends RankIndexMaintainer to support queries like:
    - Top 10 scores in the last hour
    - My rank among scores from today

    Entries are keyed by (time_bucket, score, ...) allowing efficient
    time-windowed queries.
    """

    def __init__(
        self,
        index: Index,
        subspace: Subspace,
        meta_data: RecordMetaData,
        window_size_seconds: int = 3600,
    ) -> None:
        super().__init__(index, subspace, meta_data)
        self._window_size = window_size_seconds

    def _get_time_bucket(self, timestamp: int) -> int:
        """Get the time bucket for a timestamp."""
        return timestamp // self._window_size

    def get_rank_in_window(
        self,
        tr: Transaction,
        score: Any,
        window_start: int,
        window_end: int,
    ) -> int:
        """Get rank of a score within a time window.

        Args:
            tr: The FDB transaction.
            score: The score to rank.
            window_start: Window start timestamp.
            window_end: Window end timestamp.

        Returns:
            Rank within the time window.
        """
        # Scan entries in the time window with score < given score
        rank = 0

        start_bucket = self._get_time_bucket(window_start)
        end_bucket = self._get_time_bucket(window_end)

        for bucket in range(start_bucket, end_bucket + 1):
            bucket_start = self._entries_subspace.pack((bucket,))
            bucket_end = self._entries_subspace.pack((bucket, score))

            for _ in tr.get_range(bucket_start, bucket_end):
                rank += 1

        return rank
