"""Online index builder for background index construction.

The OnlineIndexBuilder allows building indexes on existing data without
blocking normal operations. It works by:
1. Setting the index to WRITE_ONLY state
2. Scanning existing records in batches across multiple transactions
3. Setting the index to READABLE state when complete
"""

from __future__ import annotations

import asyncio
import time
from collections.abc import Callable
from dataclasses import dataclass
from enum import Enum
from typing import TYPE_CHECKING, Any

from fdb_record_layer.metadata.index import IndexState

if TYPE_CHECKING:
    from fdb_record_layer.core.store import FDBRecordStore
    from fdb_record_layer.metadata.index import Index


class BuildState(str, Enum):
    """State of an index build."""

    NOT_STARTED = "not_started"
    IN_PROGRESS = "in_progress"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


@dataclass
class BuildProgress:
    """Progress of an index build operation."""

    index_name: str
    state: BuildState = BuildState.NOT_STARTED
    records_scanned: int = 0
    records_indexed: int = 0
    errors: int = 0
    batches_completed: int = 0
    start_time: float | None = None
    end_time: float | None = None
    last_primary_key: tuple | None = None
    error_message: str | None = None

    @property
    def duration_seconds(self) -> float:
        """Get the build duration in seconds."""
        if self.start_time is None:
            return 0.0
        end = self.end_time or time.time()
        return end - self.start_time

    @property
    def records_per_second(self) -> float:
        """Get the indexing rate."""
        duration = self.duration_seconds
        if duration == 0:
            return 0.0
        return self.records_indexed / duration

    def to_dict(self) -> dict:
        """Convert to dictionary for serialization."""
        return {
            "index_name": self.index_name,
            "state": self.state.value,
            "records_scanned": self.records_scanned,
            "records_indexed": self.records_indexed,
            "errors": self.errors,
            "batches_completed": self.batches_completed,
            "start_time": self.start_time,
            "end_time": self.end_time,
            "last_primary_key": self.last_primary_key,
            "error_message": self.error_message,
        }


@dataclass
class BuildConfig:
    """Configuration for index build."""

    # Number of records per transaction batch
    batch_size: int = 100

    # Maximum number of records to index (0 = unlimited)
    max_records: int = 0

    # Delay between batches (seconds) to reduce load
    inter_batch_delay: float = 0.0

    # Maximum retries per batch on conflict
    max_retries: int = 3

    # Whether to continue on errors or stop
    continue_on_error: bool = True

    # Progress callback
    progress_callback: Callable[[BuildProgress], None] | None = None


class OnlineIndexBuilder:
    """Builds indexes online without blocking operations.

    The builder operates in phases:
    1. Mark index as WRITE_ONLY (new writes update the index)
    2. Scan existing records in batches, adding them to the index
    3. Mark index as READABLE when complete

    Example:
        >>> builder = OnlineIndexBuilder(store, "Person$email")
        >>> progress = await builder.build()
        >>> print(f"Indexed {progress.records_indexed} records")
    """

    def __init__(
        self,
        store: FDBRecordStore,
        index_name: str,
        config: BuildConfig | None = None,
    ) -> None:
        """Initialize the index builder.

        Args:
            store: The record store containing the index.
            index_name: Name of the index to build.
            config: Build configuration.
        """
        self._store = store
        self._index_name = index_name
        self._config = config or BuildConfig()
        self._progress = BuildProgress(index_name=index_name)
        self._cancelled = False

    @property
    def progress(self) -> BuildProgress:
        """Get the current build progress."""
        return self._progress

    def cancel(self) -> None:
        """Cancel the build operation."""
        self._cancelled = True

    async def build(self) -> BuildProgress:
        """Build the index.

        Returns:
            BuildProgress with final status.
        """
        self._progress.state = BuildState.IN_PROGRESS
        self._progress.start_time = time.time()

        try:
            # Get the index
            index = self._store.meta_data.get_index(self._index_name)

            # Set index to WRITE_ONLY
            await self._set_index_state_write_only()

            # Build the index in batches
            await self._build_index(index)

            # Set index to READABLE
            if not self._cancelled:
                await self._set_index_state_readable()
                self._progress.state = BuildState.COMPLETED
            else:
                self._progress.state = BuildState.CANCELLED

        except Exception as e:
            self._progress.state = BuildState.FAILED
            self._progress.error_message = str(e)
            raise

        finally:
            self._progress.end_time = time.time()

        return self._progress

    async def _set_index_state_write_only(self) -> None:
        """Set the index to WRITE_ONLY state.

        This persists the state to FDB so the index won't be used for queries
        until the build is complete.
        """
        self._store.set_index_state(self._index_name, IndexState.WRITE_ONLY)
        await self._store._context.commit()
        # Re-open transaction for next operations
        self._store._context.ensure_active()

    async def _set_index_state_readable(self) -> None:
        """Set the index to READABLE state.

        This marks the index as ready for queries after a successful build.
        """
        self._store.set_index_state(self._index_name, IndexState.READABLE)
        await self._store._context.commit()

    async def _build_index(self, index: Index) -> None:
        """Build the index by scanning records."""
        record_types = index.record_types or list(self._store.meta_data.record_types.keys())
        continuation: bytes | None = None

        while not self._cancelled:
            # Process one batch
            batch_result = await self._build_batch(index, record_types, continuation)

            self._progress.batches_completed += 1
            self._progress.records_scanned += batch_result.records_scanned
            self._progress.records_indexed += batch_result.records_indexed
            self._progress.errors += batch_result.errors
            self._progress.last_primary_key = batch_result.last_key

            # Report progress
            if self._config.progress_callback:
                self._config.progress_callback(self._progress)

            # Check if done
            if not batch_result.has_more:
                break

            continuation = batch_result.continuation

            # Check max records limit
            if (
                self._config.max_records > 0
                and self._progress.records_scanned >= self._config.max_records
            ):
                break

            # Inter-batch delay
            if self._config.inter_batch_delay > 0:
                await asyncio.sleep(self._config.inter_batch_delay)

    async def _build_batch(
        self,
        index: Index,
        record_types: list[str],
        continuation: bytes | None,
    ) -> BatchResult:
        """Build one batch of records.

        Creates a new transaction for each batch to avoid long-running
        transactions and allow proper retry handling.
        """
        from fdb_record_layer.core.context import FDBRecordContext

        result = BatchResult()
        retries = 0

        while retries <= self._config.max_retries:
            # Create a new context for this batch
            ctx = FDBRecordContext(database=self._store._context.database)

            try:
                tr = ctx.transaction

                # Scan records using the store's scan functionality
                records = await self._scan_records(
                    tr, record_types, continuation, self._config.batch_size
                )

                for record_info in records:
                    result.records_scanned += 1
                    result.last_key = record_info.primary_key

                    try:
                        # Add to index
                        await self._index_record(tr, index, record_info)
                        result.records_indexed += 1
                    except Exception:
                        result.errors += 1
                        if not self._config.continue_on_error:
                            raise

                # Set continuation for next batch
                if records:
                    result.continuation = self._encode_continuation(records[-1].primary_key)
                    result.has_more = len(records) >= self._config.batch_size
                else:
                    result.has_more = False

                # Commit the transaction
                await ctx.commit()

                # Batch completed successfully
                break

            except Exception:
                retries += 1
                if retries > self._config.max_retries:
                    raise
                await asyncio.sleep(0.1 * retries)  # Exponential backoff

            finally:
                # Always close the context
                ctx.close()

        return result

    async def _scan_records(
        self,
        tr: Any,
        record_types: list[str],
        continuation: bytes | None,
        limit: int,
    ) -> list[RecordInfo]:
        """Scan records from the store."""
        records = []

        # Decode continuation to get starting key
        start_key = None
        if continuation:
            start_key = self._decode_continuation(continuation)

        # This is a simplified implementation
        # In production, we'd use the store's scan functionality
        for record_type in record_types:
            # Get all records of this type
            cursor = await self._store.scan_records(record_type)
            async for stored_record in cursor:
                pk = stored_record.primary_key

                # Skip if before continuation
                if start_key and pk <= start_key:
                    continue

                records.append(
                    RecordInfo(
                        record_type=record_type,
                        primary_key=pk,
                        record=stored_record.record,
                    )
                )

                if len(records) >= limit:
                    return records

        return records

    async def _index_record(self, tr: Any, index: Index, record_info: RecordInfo) -> None:
        """Add a single record to the index."""
        maintainer = self._store._index_maintainers.get(self._index_name)
        if maintainer:
            await maintainer.update(
                tr,
                record_info.record,
                record_info.primary_key,
            )

    def _encode_continuation(self, primary_key: tuple) -> bytes:
        """Encode a primary key as continuation."""
        import json

        return json.dumps(primary_key).encode("utf-8")

    def _decode_continuation(self, continuation: bytes) -> tuple:
        """Decode a continuation to a primary key."""
        import json

        return tuple(json.loads(continuation.decode("utf-8")))


@dataclass
class RecordInfo:
    """Information about a record for indexing."""

    record_type: str
    primary_key: tuple
    record: Any


@dataclass
class BatchResult:
    """Result of processing one batch."""

    records_scanned: int = 0
    records_indexed: int = 0
    errors: int = 0
    has_more: bool = False
    continuation: bytes | None = None
    last_key: tuple | None = None


class IndexStateManager:
    """Manages index states during online operations.

    Tracks which indexes are in what state and provides safe
    transitions between states. States are persisted to FDB.
    """

    def __init__(self, store: FDBRecordStore) -> None:
        self._store = store

    def get_state(self, index_name: str) -> IndexState:
        """Get the current state of an index from FDB."""
        return self._store.get_index_state(index_name)

    def set_state(self, index_name: str, state: IndexState) -> None:
        """Set the state of an index in FDB.

        Args:
            index_name: The index name.
            state: The new state.
        """
        self._store.set_index_state(index_name, state)

    async def mark_write_only(self, index_name: str) -> None:
        """Mark an index as write-only and commit."""
        self.set_state(index_name, IndexState.WRITE_ONLY)
        await self._store._context.commit()
        self._store._context.ensure_active()

    async def mark_readable(self, index_name: str) -> None:
        """Mark an index as readable and commit."""
        self.set_state(index_name, IndexState.READABLE)
        await self._store._context.commit()

    async def mark_disabled(self, index_name: str) -> None:
        """Mark an index as disabled and commit."""
        self.set_state(index_name, IndexState.DISABLED)
        await self._store._context.commit()

    def is_readable(self, index_name: str) -> bool:
        """Check if an index is readable."""
        return self.get_state(index_name) == IndexState.READABLE

    def is_write_only(self, index_name: str) -> bool:
        """Check if an index is write-only."""
        return self.get_state(index_name) == IndexState.WRITE_ONLY

    def is_disabled(self, index_name: str) -> bool:
        """Check if an index is disabled."""
        return self.get_state(index_name) == IndexState.DISABLED


async def build_index(
    store: FDBRecordStore,
    index_name: str,
    batch_size: int = 100,
    progress_callback: Callable[[BuildProgress], None] | None = None,
) -> BuildProgress:
    """Convenience function to build an index.

    Args:
        store: The record store.
        index_name: Name of the index to build.
        batch_size: Records per batch.
        progress_callback: Optional progress callback.

    Returns:
        Final build progress.
    """
    config = BuildConfig(
        batch_size=batch_size,
        progress_callback=progress_callback,
    )
    builder = OnlineIndexBuilder(store, index_name, config)
    return await builder.build()
