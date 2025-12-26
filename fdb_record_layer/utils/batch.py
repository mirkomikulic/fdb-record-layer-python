"""Batch operations for efficient bulk data processing.

Provides utilities for batching reads, writes, and other operations
to maximize throughput while staying within FDB transaction limits.
"""

from __future__ import annotations

import asyncio
from collections.abc import Callable, Coroutine, Iterator
from dataclasses import dataclass, field
from typing import (
    Any,
    Generic,
    TypeVar,
)

T = TypeVar("T")
R = TypeVar("R")


@dataclass
class BatchConfig:
    """Configuration for batch operations.

    Attributes:
        batch_size: Maximum number of items per batch.
        max_batch_bytes: Maximum bytes per batch (FDB limit is ~10MB).
        max_concurrent_batches: Maximum concurrent batch operations.
        retry_limit: Maximum retries per batch on failure.
        inter_batch_delay: Delay between batches in seconds.
    """

    batch_size: int = 100
    max_batch_bytes: int = 1_000_000  # 1MB default, FDB limit is ~10MB
    max_concurrent_batches: int = 5
    retry_limit: int = 3
    inter_batch_delay: float = 0.0


@dataclass
class BatchResult(Generic[T]):
    """Result of a batch operation.

    Attributes:
        successful: Items that were successfully processed.
        failed: Items that failed with their error messages.
        total_processed: Total number of items attempted.
        total_succeeded: Number of successful items.
        total_failed: Number of failed items.
    """

    successful: list[T] = field(default_factory=list)
    failed: list[tuple[Any, str]] = field(default_factory=list)

    @property
    def total_processed(self) -> int:
        return len(self.successful) + len(self.failed)

    @property
    def total_succeeded(self) -> int:
        return len(self.successful)

    @property
    def total_failed(self) -> int:
        return len(self.failed)

    @property
    def success_rate(self) -> float:
        if self.total_processed == 0:
            return 1.0
        return self.total_succeeded / self.total_processed

    def merge(self, other: BatchResult[T]) -> BatchResult[T]:
        """Merge another batch result into this one."""
        return BatchResult(
            successful=self.successful + other.successful,
            failed=self.failed + other.failed,
        )


class BatchProcessor(Generic[T, R]):
    """Processes items in batches for efficient bulk operations.

    Example:
        >>> async def save_records(batch):
        ...     for record in batch:
        ...         await store.save_record(record)
        ...     return batch
        >>>
        >>> processor = BatchProcessor(save_records, BatchConfig(batch_size=50))
        >>> result = await processor.process(records)
        >>> print(f"Saved {result.total_succeeded} records")
    """

    def __init__(
        self,
        operation: Callable[[list[T]], Coroutine[Any, Any, list[R]]],
        config: BatchConfig | None = None,
    ) -> None:
        """Initialize the batch processor.

        Args:
            operation: Async function to process a batch of items.
            config: Batch configuration.
        """
        self._operation = operation
        self._config = config or BatchConfig()

    async def process(self, items: list[T]) -> BatchResult[R]:
        """Process all items in batches.

        Args:
            items: Items to process.

        Returns:
            Combined result of all batch operations.
        """
        if not items:
            return BatchResult()

        # Split into batches
        batches = list(self._split_into_batches(items))
        result = BatchResult[R]()

        # Process batches with concurrency limit
        semaphore = asyncio.Semaphore(self._config.max_concurrent_batches)

        async def process_with_semaphore(batch: list[T]) -> BatchResult[R]:
            async with semaphore:
                return await self._process_batch(batch)

        tasks = [process_with_semaphore(batch) for batch in batches]
        batch_results = await asyncio.gather(*tasks)

        for batch_result in batch_results:
            result = result.merge(batch_result)

        return result

    async def _process_batch(self, batch: list[T]) -> BatchResult[R]:
        """Process a single batch with retries."""
        last_error = None

        for attempt in range(self._config.retry_limit):
            try:
                results = await self._operation(batch)
                return BatchResult(successful=results)
            except Exception as e:
                last_error = str(e)
                if attempt < self._config.retry_limit - 1:
                    await asyncio.sleep(0.1 * (2**attempt))  # Exponential backoff

        # All retries failed
        return BatchResult(failed=[(item, last_error or "Unknown error") for item in batch])

    def _split_into_batches(self, items: list[T]) -> Iterator[list[T]]:
        """Split items into batches."""
        for i in range(0, len(items), self._config.batch_size):
            yield items[i : i + self._config.batch_size]


class BatchWriter:
    """Batches write operations for efficient bulk inserts/updates.

    Accumulates writes and flushes them in batches when the batch
    is full or flush() is called.

    Example:
        >>> writer = BatchWriter(store, batch_size=100)
        >>> for record in records:
        ...     await writer.write(record)
        >>> await writer.flush()  # Ensure all writes complete
    """

    def __init__(
        self,
        store: Any,  # FDBRecordStore
        config: BatchConfig | None = None,
    ) -> None:
        """Initialize the batch writer.

        Args:
            store: The record store to write to.
            config: Batch configuration.
        """
        self._store = store
        self._config = config or BatchConfig()
        self._buffer: list[Any] = []
        self._total_written = 0

    async def write(self, record: Any) -> None:
        """Add a record to the write buffer.

        Automatically flushes when batch size is reached.

        Args:
            record: The record to write.
        """
        self._buffer.append(record)
        if len(self._buffer) >= self._config.batch_size:
            await self.flush()

    async def write_many(self, records: list[Any]) -> None:
        """Add multiple records to the write buffer.

        Args:
            records: Records to write.
        """
        for record in records:
            await self.write(record)

    async def flush(self) -> int:
        """Flush all buffered writes to the store.

        Returns:
            Number of records written.
        """
        if not self._buffer:
            return 0

        count = len(self._buffer)

        # Process in batches if buffer exceeds batch size
        while self._buffer:
            batch = self._buffer[: self._config.batch_size]
            self._buffer = self._buffer[self._config.batch_size :]

            for record in batch:
                if hasattr(self._store, "save_record"):
                    await self._store.save_record(record)

            self._total_written += len(batch)

            if self._config.inter_batch_delay > 0 and self._buffer:
                await asyncio.sleep(self._config.inter_batch_delay)

        return count

    @property
    def pending_count(self) -> int:
        """Get the number of pending writes."""
        return len(self._buffer)

    @property
    def total_written(self) -> int:
        """Get the total number of records written."""
        return self._total_written

    async def __aenter__(self) -> BatchWriter:
        return self

    async def __aexit__(self, exc_type: Any, exc_val: Any, exc_tb: Any) -> None:
        await self.flush()


class BatchReader:
    """Batches read operations for efficient bulk loading.

    Example:
        >>> reader = BatchReader(store, batch_size=100)
        >>> async for record in reader.read_all("Person"):
        ...     process(record)
    """

    def __init__(
        self,
        store: Any,  # FDBRecordStore
        config: BatchConfig | None = None,
    ) -> None:
        """Initialize the batch reader.

        Args:
            store: The record store to read from.
            config: Batch configuration.
        """
        self._store = store
        self._config = config or BatchConfig()

    async def read_by_keys(
        self,
        record_type: str,
        keys: list[tuple[Any, ...]],
    ) -> list[Any]:
        """Read multiple records by their primary keys.

        Args:
            record_type: The record type name.
            keys: List of primary key tuples.

        Returns:
            List of records (None for missing keys).
        """
        results: list[Any] = []

        for i in range(0, len(keys), self._config.batch_size):
            batch_keys = keys[i : i + self._config.batch_size]
            batch_results = []

            for key in batch_keys:
                if hasattr(self._store, "load_record"):
                    record = await self._store.load_record(record_type, key)
                    batch_results.append(record)
                else:
                    batch_results.append(None)

            results.extend(batch_results)

            if self._config.inter_batch_delay > 0:
                await asyncio.sleep(self._config.inter_batch_delay)

        return results

    async def read_all(
        self,
        record_type: str,
        limit: int | None = None,
    ) -> list[Any]:
        """Read all records of a type.

        Args:
            record_type: The record type name.
            limit: Maximum records to read.

        Returns:
            List of records.
        """
        if hasattr(self._store, "scan_records"):
            return await self._store.scan_records(record_type, limit=limit)
        return []


class Pipeline:
    """Pipelines multiple operations for better throughput.

    Allows overlapping reads and writes to maximize throughput
    by keeping the database busy while processing.

    Example:
        >>> pipeline = Pipeline()
        >>> pipeline.add_stage("read", read_records)
        >>> pipeline.add_stage("transform", transform_records)
        >>> pipeline.add_stage("write", write_records)
        >>> await pipeline.execute(record_ids)
    """

    def __init__(self, max_in_flight: int = 10) -> None:
        """Initialize the pipeline.

        Args:
            max_in_flight: Maximum concurrent operations.
        """
        self._stages: list[tuple[str, Callable]] = []
        self._max_in_flight = max_in_flight

    def add_stage(
        self,
        name: str,
        operation: Callable[[Any], Coroutine[Any, Any, Any]],
    ) -> Pipeline:
        """Add a stage to the pipeline.

        Args:
            name: Stage name for logging.
            operation: Async function for this stage.

        Returns:
            Self for chaining.
        """
        self._stages.append((name, operation))
        return self

    async def execute(self, items: list[Any]) -> list[Any]:
        """Execute the pipeline on items.

        Args:
            items: Input items.

        Returns:
            Processed items.
        """
        if not self._stages:
            return items

        current = items
        for name, operation in self._stages:
            semaphore = asyncio.Semaphore(self._max_in_flight)

            async def run_with_limit(item: Any) -> Any:
                async with semaphore:
                    return await operation(item)

            tasks = [run_with_limit(item) for item in current]
            current = await asyncio.gather(*tasks)

        return list(current)


@dataclass
class WriteBuffer:
    """A simple write buffer for accumulating changes.

    Useful for transaction batching where you want to accumulate
    changes and commit them together.
    """

    _inserts: list[Any] = field(default_factory=list)
    _updates: list[tuple[Any, dict[str, Any]]] = field(default_factory=list)
    _deletes: list[tuple[str, tuple[Any, ...]]] = field(default_factory=list)

    def insert(self, record: Any) -> None:
        """Buffer an insert."""
        self._inserts.append(record)

    def update(self, record: Any, changes: dict[str, Any]) -> None:
        """Buffer an update."""
        self._updates.append((record, changes))

    def delete(self, record_type: str, primary_key: tuple[Any, ...]) -> None:
        """Buffer a delete."""
        self._deletes.append((record_type, primary_key))

    def clear(self) -> None:
        """Clear the buffer."""
        self._inserts.clear()
        self._updates.clear()
        self._deletes.clear()

    @property
    def insert_count(self) -> int:
        return len(self._inserts)

    @property
    def update_count(self) -> int:
        return len(self._updates)

    @property
    def delete_count(self) -> int:
        return len(self._deletes)

    @property
    def total_count(self) -> int:
        return self.insert_count + self.update_count + self.delete_count

    @property
    def is_empty(self) -> bool:
        return self.total_count == 0

    async def apply(self, store: Any) -> int:
        """Apply all buffered changes to a store.

        Args:
            store: The record store.

        Returns:
            Total number of operations applied.
        """
        count = 0

        for record in self._inserts:
            if hasattr(store, "save_record"):
                await store.save_record(record)
                count += 1

        for record, changes in self._updates:
            if hasattr(store, "save_record"):
                for key, value in changes.items():
                    setattr(record, key, value)
                await store.save_record(record)
                count += 1

        for record_type, primary_key in self._deletes:
            if hasattr(store, "delete_record"):
                await store.delete_record(record_type, primary_key)
                count += 1

        self.clear()
        return count
