"""FDB Record Store - main interface for record operations."""

from __future__ import annotations

import asyncio
import logging
import time
from typing import TYPE_CHECKING, Any, Generic, TypeVar

from fdb.subspace_impl import Subspace

from fdb_record_layer.core.exceptions import (
    InvalidPrimaryKeyException,
    RecordTypeNotFoundException,
)
from fdb_record_layer.core.record import FDBStoredRecord
from fdb_record_layer.cursors.base import RecordCursor
from fdb_record_layer.indexes.maintainer import IndexMaintainer, IndexScanRange
from fdb_record_layer.indexes.value_index import ValueIndexMaintainer
from fdb_record_layer.metadata.index import IndexState
from fdb_record_layer.serialization.proto_serializer import (
    get_default_serializer,
)
from fdb_record_layer.serialization.serializer import RecordSerializer

# Module logger (after imports to satisfy linter)
_logger = logging.getLogger("fdb_record_layer.core.store")

if TYPE_CHECKING:
    from fdb import Transaction
    from google.protobuf.message import Message

    from fdb_record_layer.core.context import FDBRecordContext
    from fdb_record_layer.metadata.record_metadata import RecordMetaData

M = TypeVar("M", bound="Message")


class FDBRecordStore(Generic[M]):
    """Main interface for record operations.

    FDBRecordStore provides:
    - CRUD operations on records
    - Automatic index maintenance
    - Index-based queries

    Example:
        >>> async with db.open_context() as ctx:
        ...     store = FDBRecordStore(ctx, subspace, metadata)
        ...     await store.save_record(person)
        ...     record = await store.load_record("Person", (person_id,))
    """

    # Subspace layout
    RECORDS_KEY = 0
    INDEX_KEY = 1
    INDEX_STATE_KEY = 2
    INDEX_BUILD_KEY = 3
    RECORD_COUNT_KEY = 4

    def __init__(
        self,
        context: FDBRecordContext,
        subspace: Subspace,
        meta_data: RecordMetaData,
        serializer: RecordSerializer | None = None,
    ) -> None:
        """Initialize the record store.

        Args:
            context: The record context with transaction.
            subspace: The subspace for this store's data.
            meta_data: The record metadata defining types and indexes.
            serializer: Optional custom serializer. Defaults to protobuf.
        """
        self._context = context
        self._subspace = subspace
        self._meta_data = meta_data
        self._serializer = serializer or get_default_serializer()

        # Initialize subspaces
        self._records_subspace = subspace[self.RECORDS_KEY]
        self._index_subspace = subspace[self.INDEX_KEY]
        self._index_state_subspace = subspace[self.INDEX_STATE_KEY]
        self._index_build_subspace = subspace[self.INDEX_BUILD_KEY]
        self._record_count_subspace = subspace[self.RECORD_COUNT_KEY]

        # Initialize index maintainers
        self._index_maintainers: dict[str, IndexMaintainer] = {}
        self._init_index_maintainers()

    def _init_index_maintainers(self) -> None:
        """Initialize maintainers for all indexes."""
        for index in self._meta_data.indexes.values():
            maintainer = self._create_maintainer(index)
            self._index_maintainers[index.name] = maintainer

    def _create_maintainer(self, index: Any) -> IndexMaintainer:
        """Create the appropriate maintainer for an index type."""
        from fdb_record_layer.indexes.registry import get_default_registry

        index_subspace = self._index_subspace[index.name]
        registry = get_default_registry()

        try:
            return registry.create_maintainer(index, index_subspace, self._meta_data)
        except ValueError:
            # Fall back to VALUE index for unknown types
            return ValueIndexMaintainer(index, index_subspace, self._meta_data)

    @property
    def context(self) -> FDBRecordContext:
        """Get the record context."""
        return self._context

    @property
    def transaction(self) -> Transaction:
        """Get the underlying FDB transaction."""
        return self._context.transaction

    @property
    def meta_data(self) -> RecordMetaData:
        """Get the record metadata."""
        return self._meta_data

    # =========================================================================
    # CRUD Operations
    # =========================================================================

    async def save_record(
        self,
        record: M,
        record_type_name: str | None = None,
    ) -> FDBStoredRecord[M]:
        """Save a record, creating or updating as needed.

        This will:
        1. Compute the primary key from the record
        2. Load any existing record for index cleanup
        3. Serialize and store the record
        4. Update all applicable indexes

        Args:
            record: The protobuf message to save.
            record_type_name: Optional explicit record type name.
                             Defaults to the message's descriptor name.

        Returns:
            The stored record wrapper.

        Raises:
            RecordTypeNotFoundException: If the record type is unknown.
            InvalidPrimaryKeyException: If the primary key is invalid.
        """
        start_time = time.perf_counter()
        self._context.ensure_active()

        # Determine record type
        if record_type_name is None:
            record_type_name = record.DESCRIPTOR.name

        if not self._meta_data.has_record_type(record_type_name):
            raise RecordTypeNotFoundException(record_type_name)

        record_type = self._meta_data.get_record_type(record_type_name)

        # Compute primary key
        primary_key_values = record_type.primary_key.evaluate(record)
        if len(primary_key_values) != 1:
            raise InvalidPrimaryKeyException(
                f"Primary key must evaluate to exactly one value, got {len(primary_key_values)}"
            )
        primary_key = primary_key_values[0]

        # Load existing record for index cleanup
        old_record = await self._load_raw_record(record_type_name, primary_key)
        is_update = old_record is not None

        # Serialize and store
        record_key = self._records_subspace[record_type_name].pack(primary_key)
        record_bytes = self._serializer.serialize(record)
        self.transaction.set(record_key, record_bytes)

        # Update indexes
        await self._update_indexes(record_type, primary_key, old_record, record)

        duration_ms = (time.perf_counter() - start_time) * 1000
        _logger.debug(
            "Record saved",
            extra={
                "record_type": record_type_name,
                "primary_key": str(primary_key),
                "is_update": is_update,
                "size_bytes": len(record_bytes),
                "duration_ms": round(duration_ms, 2),
            },
        )

        return FDBStoredRecord(
            primary_key=primary_key,
            record=record,
            record_type=record_type,
        )

    async def load_record(
        self,
        record_type_name: str,
        primary_key: tuple[Any, ...],
    ) -> FDBStoredRecord[M] | None:
        """Load a record by primary key.

        Args:
            record_type_name: The record type name.
            primary_key: The primary key tuple.

        Returns:
            The stored record, or None if not found.

        Raises:
            RecordTypeNotFoundException: If the record type is unknown.
        """
        start_time = time.perf_counter()
        self._context.ensure_active()

        if not self._meta_data.has_record_type(record_type_name):
            raise RecordTypeNotFoundException(record_type_name)

        record_type = self._meta_data.get_record_type(record_type_name)

        # Load from database
        record_key = self._records_subspace[record_type_name].pack(primary_key)

        loop = asyncio.get_event_loop()
        # FDB returns a future-like Value object
        value = await loop.run_in_executor(None, lambda: self.transaction[record_key])

        if not value.present():
            duration_ms = (time.perf_counter() - start_time) * 1000
            _logger.debug(
                "Record not found",
                extra={
                    "record_type": record_type_name,
                    "primary_key": str(primary_key),
                    "duration_ms": round(duration_ms, 2),
                },
            )
            return None

        record_bytes = bytes(value)

        # Deserialize
        record = self._serializer.deserialize(record_bytes, record_type.descriptor)

        duration_ms = (time.perf_counter() - start_time) * 1000
        _logger.debug(
            "Record loaded",
            extra={
                "record_type": record_type_name,
                "primary_key": str(primary_key),
                "size_bytes": len(record_bytes),
                "duration_ms": round(duration_ms, 2),
            },
        )

        return FDBStoredRecord(
            primary_key=primary_key,
            record=record,  # type: ignore
            record_type=record_type,
        )

    async def load_records(
        self,
        record_type_name: str,
        primary_keys: list[tuple[Any, ...]],
    ) -> list[FDBStoredRecord[M] | None]:
        """Load multiple records efficiently by primary keys.

        Uses batched FDB reads to minimize N+1 query patterns.

        Args:
            record_type_name: The record type name.
            primary_keys: List of primary key tuples.

        Returns:
            List of stored records (None for records not found).

        Raises:
            RecordTypeNotFoundException: If the record type is unknown.
        """
        if not primary_keys:
            return []

        start_time = time.perf_counter()
        self._context.ensure_active()

        if not self._meta_data.has_record_type(record_type_name):
            raise RecordTypeNotFoundException(record_type_name)

        record_type = self._meta_data.get_record_type(record_type_name)

        # Batch load all records
        raw_records = await self._load_raw_records_batch(record_type_name, primary_keys)

        # Build result list in same order as primary_keys
        results: list[FDBStoredRecord[M] | None] = []
        found_count = 0
        for pk in primary_keys:
            record = raw_records.get(pk)
            if record is None:
                results.append(None)
            else:
                found_count += 1
                results.append(
                    FDBStoredRecord(
                        primary_key=pk,
                        record=record,  # type: ignore
                        record_type=record_type,
                    )
                )

        duration_ms = (time.perf_counter() - start_time) * 1000
        _logger.debug(
            "Batch load completed",
            extra={
                "record_type": record_type_name,
                "requested_count": len(primary_keys),
                "found_count": found_count,
                "duration_ms": round(duration_ms, 2),
            },
        )

        return results

    async def delete_record(
        self,
        record_type_name: str,
        primary_key: tuple[Any, ...],
    ) -> bool:
        """Delete a record by primary key.

        Args:
            record_type_name: The record type name.
            primary_key: The primary key tuple.

        Returns:
            True if a record was deleted, False if not found.

        Raises:
            RecordTypeNotFoundException: If the record type is unknown.
        """
        start_time = time.perf_counter()
        self._context.ensure_active()

        if not self._meta_data.has_record_type(record_type_name):
            raise RecordTypeNotFoundException(record_type_name)

        record_type = self._meta_data.get_record_type(record_type_name)

        # Load existing record for index cleanup
        old_record = await self._load_raw_record(record_type_name, primary_key)
        if old_record is None:
            _logger.debug(
                "Record not found for deletion",
                extra={
                    "record_type": record_type_name,
                    "primary_key": str(primary_key),
                },
            )
            return False

        # Delete record
        record_key = self._records_subspace[record_type_name].pack(primary_key)
        self.transaction.clear(record_key)

        # Update indexes (remove old entries)
        await self._update_indexes(record_type, primary_key, old_record, None)

        duration_ms = (time.perf_counter() - start_time) * 1000
        _logger.debug(
            "Record deleted",
            extra={
                "record_type": record_type_name,
                "primary_key": str(primary_key),
                "duration_ms": round(duration_ms, 2),
            },
        )

        return True

    async def record_exists(
        self,
        record_type_name: str,
        primary_key: tuple[Any, ...],
    ) -> bool:
        """Check if a record exists.

        Args:
            record_type_name: The record type name.
            primary_key: The primary key tuple.

        Returns:
            True if the record exists.
        """
        self._context.ensure_active()

        if not self._meta_data.has_record_type(record_type_name):
            raise RecordTypeNotFoundException(record_type_name)

        record_key = self._records_subspace[record_type_name].pack(primary_key)

        loop = asyncio.get_event_loop()
        value = await loop.run_in_executor(None, lambda: self.transaction[record_key])

        return value.present()

    # =========================================================================
    # Index Operations
    # =========================================================================

    async def scan_index(
        self,
        index_name: str,
        scan_range: IndexScanRange | None = None,
        continuation: bytes | None = None,
        limit: int = 0,
    ) -> RecordCursor[FDBStoredRecord[M]]:
        """Scan an index and return matching records.

        Args:
            index_name: The name of the index to scan.
            scan_range: Optional range to scan within.
            continuation: Optional continuation for resuming.
            limit: Maximum number of results (0 = unlimited).

        Returns:
            A cursor over matching records.
        """
        self._context.ensure_active()

        if index_name not in self._index_maintainers:
            from fdb_record_layer.core.exceptions import IndexNotFoundException

            raise IndexNotFoundException(index_name)

        maintainer = self._index_maintainers[index_name]

        def record_loader(rt_name: str, pk: tuple[Any, ...]) -> FDBStoredRecord[Any] | None:
            # Synchronous loader for use in scan
            return self._load_record_sync(rt_name, pk)

        return await maintainer.scan(
            self.transaction,
            scan_range,
            continuation,
            limit,
            record_loader,
        )

    def get_index_state(self, index_name: str) -> IndexState:
        """Get the state of an index.

        Args:
            index_name: The index name.

        Returns:
            The index state.
        """
        key = self._index_state_subspace.pack((index_name,))
        value = self.transaction[key]

        if not value.present():
            return IndexState.READABLE  # Default state

        return IndexState(bytes(value).decode())

    def set_index_state(self, index_name: str, state: IndexState) -> None:
        """Set the state of an index.

        Args:
            index_name: The index name.
            state: The new state.
        """
        key = self._index_state_subspace.pack((index_name,))
        self.transaction.set(key, state.value.encode())

    # =========================================================================
    # Internal Methods
    # =========================================================================

    async def _load_raw_record(
        self,
        record_type_name: str,
        primary_key: tuple[Any, ...],
    ) -> Message | None:
        """Load a record without wrapping in FDBStoredRecord."""
        record_type = self._meta_data.get_record_type(record_type_name)
        record_key = self._records_subspace[record_type_name].pack(primary_key)

        loop = asyncio.get_event_loop()

        # FDB returns a future-like Value object, need to wait for it
        def get_record_bytes() -> bytes | None:
            val = self.transaction[record_key]
            return bytes(val) if val.present() else None

        record_bytes = await loop.run_in_executor(None, get_record_bytes)

        if record_bytes is None:
            return None

        return self._serializer.deserialize(record_bytes, record_type.descriptor)

    async def _load_raw_records_batch(
        self,
        record_type_name: str,
        primary_keys: list[tuple[Any, ...]],
    ) -> dict[tuple[Any, ...], Message | None]:
        """Load multiple records efficiently using FDB futures.

        This reduces N+1 query patterns by batching reads.
        """
        if not primary_keys:
            return {}

        record_type = self._meta_data.get_record_type(record_type_name)

        # Create all FDB read futures first
        def batch_read() -> dict[tuple[Any, ...], bytes | None]:
            results: dict[tuple[Any, ...], bytes | None] = {}
            futures = {}

            # Start all reads (creates FDB futures)
            for pk in primary_keys:
                record_key = self._records_subspace[record_type_name].pack(pk)
                futures[pk] = self.transaction[record_key]

            # Wait for all reads to complete
            for pk, future in futures.items():
                if future.present():
                    results[pk] = bytes(future)
                else:
                    results[pk] = None

            return results

        loop = asyncio.get_event_loop()
        raw_results = await loop.run_in_executor(None, batch_read)

        # Deserialize all records
        results: dict[tuple[Any, ...], Message | None] = {}
        for pk, record_bytes in raw_results.items():
            if record_bytes is None:
                results[pk] = None
            else:
                results[pk] = self._serializer.deserialize(record_bytes, record_type.descriptor)

        return results

    def _load_record_sync(
        self,
        record_type_name: str,
        primary_key: tuple[Any, ...],
    ) -> FDBStoredRecord[Any] | None:
        """Synchronously load a record (for use in index scans)."""
        if not self._meta_data.has_record_type(record_type_name):
            return None

        record_type = self._meta_data.get_record_type(record_type_name)
        record_key = self._records_subspace[record_type_name].pack(primary_key)

        value = self.transaction[record_key]
        if not value.present():
            return None
        record_bytes = bytes(value)

        record = self._serializer.deserialize(record_bytes, record_type.descriptor)

        return FDBStoredRecord(
            primary_key=primary_key,
            record=record,
            record_type=record_type,
        )

    async def _update_indexes(
        self,
        record_type: Any,
        primary_key: tuple[Any, ...],
        old_record: Message | None,
        new_record: Message | None,
    ) -> None:
        """Update all applicable indexes for a record change."""
        indexes = self._meta_data.get_indexes_for_record_type(record_type.name)

        for index in indexes:
            # Check index state
            state = self.get_index_state(index.name)
            if state == IndexState.DISABLED:
                continue

            maintainer = self._index_maintainers[index.name]

            # Remove old entries
            if old_record is not None:
                await maintainer.remove(self.transaction, old_record, primary_key)

            # Add new entries
            if new_record is not None:
                await maintainer.update(self.transaction, new_record, primary_key)

    # =========================================================================
    # Query Operations
    # =========================================================================

    async def execute_query(
        self,
        query: Any,  # RecordQuery
        continuation: bytes | None = None,
        bindings: dict[str, Any] | None = None,
    ) -> RecordCursor[FDBStoredRecord[M]]:
        """Execute a query and return matching records.

        This is the main query entry point. It plans and executes
        the query using the heuristic planner.

        Args:
            query: The RecordQuery to execute.
            continuation: Optional continuation for pagination.
            bindings: Parameter bindings for parameterized queries.

        Returns:
            A cursor over matching records.

        Example:
            >>> from fdb_record_layer.query import Query, Field
            >>> query = Query.from_type("Person").where(
            ...     Field("age").greater_than(21)
            ... ).build()
            >>> cursor = await store.execute_query(query)
            >>> async for result in cursor:
            ...     print(result.get().record.name)
        """
        self._context.ensure_active()

        from fdb_record_layer.planner.heuristic import HeuristicPlanner
        from fdb_record_layer.plans.base import ExecutionContext

        # Create planner and plan the query
        planner = HeuristicPlanner(self._meta_data)
        plan = planner.plan(query)

        # Create execution context
        context = ExecutionContext(store=self, bindings=bindings)

        # Execute the plan
        return await plan.execute(context, continuation)

    def explain_query(self, query: Any) -> str:
        """Explain how a query would be executed.

        Args:
            query: The RecordQuery to explain.

        Returns:
            A human-readable explanation of the execution plan.

        Example:
            >>> query = Query.from_type("Person").where(
            ...     Field("age").greater_than(21)
            ... ).build()
            >>> print(store.explain_query(query))
            IndexScan(index=Person$age, has_range=true)
        """
        from fdb_record_layer.planner.heuristic import HeuristicPlanner

        planner = HeuristicPlanner(self._meta_data)
        return planner.explain(query)

    async def execute_query_with_plan(
        self,
        plan: Any,  # RecordQueryPlan
        continuation: bytes | None = None,
        bindings: dict[str, Any] | None = None,
    ) -> RecordCursor[FDBStoredRecord[M]]:
        """Execute a pre-planned query.

        Use this when you want to reuse a plan or use a custom plan.

        Args:
            plan: The execution plan.
            continuation: Optional continuation.
            bindings: Parameter bindings.

        Returns:
            A cursor over matching records.
        """
        self._context.ensure_active()

        from fdb_record_layer.plans.base import ExecutionContext

        context = ExecutionContext(store=self, bindings=bindings)
        return await plan.execute(context, continuation)

    # =========================================================================
    # Aggregate Index Operations
    # =========================================================================

    def get_count(self, index_name: str, *key_values: Any) -> int:
        """Get count from a COUNT index.

        Args:
            index_name: The COUNT index name.
            key_values: The grouping key values.

        Returns:
            The count for this key.
        """
        from fdb_record_layer.indexes.count_index import CountIndexMaintainer

        maintainer = self._index_maintainers.get(index_name)
        if maintainer is None or not isinstance(maintainer, CountIndexMaintainer):
            raise ValueError(f"'{index_name}' is not a COUNT index")
        return maintainer.get_count(self.transaction, *key_values)

    def get_sum(self, index_name: str, *key_values: Any) -> int:
        """Get sum from a SUM index.

        Args:
            index_name: The SUM index name.
            key_values: The grouping key values.

        Returns:
            The sum for this key.
        """
        from fdb_record_layer.indexes.count_index import SumIndexMaintainer

        maintainer = self._index_maintainers.get(index_name)
        if maintainer is None or not isinstance(maintainer, SumIndexMaintainer):
            raise ValueError(f"'{index_name}' is not a SUM index")
        return maintainer.get_sum(self.transaction, *key_values)

    def get_rank(self, index_name: str, score: Any) -> int:
        """Get rank of a score from a RANK index.

        Args:
            index_name: The RANK index name.
            score: The score to get rank of.

        Returns:
            The 0-indexed rank.
        """
        from fdb_record_layer.indexes.rank_index import RankIndexMaintainer

        maintainer = self._index_maintainers.get(index_name)
        if maintainer is None or not isinstance(maintainer, RankIndexMaintainer):
            raise ValueError(f"'{index_name}' is not a RANK index")
        return maintainer.get_rank(self.transaction, score)

    def get_by_rank(self, index_name: str, rank: int) -> FDBStoredRecord[M] | None:
        """Get record at a specific rank.

        Args:
            index_name: The RANK index name.
            rank: The 0-indexed rank.

        Returns:
            The record at that rank, or None.
        """
        from fdb_record_layer.indexes.rank_index import RankIndexMaintainer

        maintainer = self._index_maintainers.get(index_name)
        if maintainer is None or not isinstance(maintainer, RankIndexMaintainer):
            raise ValueError(f"'{index_name}' is not a RANK index")
        return maintainer.get_by_rank(self.transaction, rank, self._load_record_sync)

    def text_search(
        self,
        index_name: str,
        tokens: list[str],
        match_all: bool = True,
        limit: int = 100,
    ) -> list[FDBStoredRecord[M]]:
        """Search a TEXT index.

        Args:
            index_name: The TEXT index name.
            tokens: Tokens to search for.
            match_all: If True, all tokens must match. If False, any token.
            limit: Maximum results.

        Returns:
            List of matching records.
        """
        from fdb_record_layer.indexes.text_index import TextIndexMaintainer

        maintainer = self._index_maintainers.get(index_name)
        if maintainer is None or not isinstance(maintainer, TextIndexMaintainer):
            raise ValueError(f"'{index_name}' is not a TEXT index")

        if match_all:
            return maintainer.search_all_tokens(
                self.transaction, tokens, self._load_record_sync, limit
            )
        else:
            return maintainer.search_any_token(
                self.transaction, tokens, self._load_record_sync, limit
            )

    # =========================================================================
    # Bulk Operations
    # =========================================================================

    async def scan_records(
        self,
        record_type_name: str,
        limit: int = 0,
    ) -> RecordCursor[FDBStoredRecord[M]]:
        """Scan all records of a given type.

        Args:
            record_type_name: The record type to scan.
            limit: Maximum number of results (0 = unlimited).

        Returns:
            A cursor over all records of the given type.
        """
        from fdb_record_layer.cursors.base import ListCursor

        self._context.ensure_active()

        if not self._meta_data.has_record_type(record_type_name):
            raise RecordTypeNotFoundException(record_type_name)

        records_subspace = self._records_subspace[record_type_name]
        start_key = records_subspace.range().start
        end_key = records_subspace.range().stop

        all_records: list[FDBStoredRecord[M]] = []
        count = 0

        loop = asyncio.get_event_loop()

        def read_range() -> list[tuple[bytes, bytes]]:
            return list(self.transaction.get_range(start_key, end_key))

        items = await loop.run_in_executor(None, read_range)

        for key, _value in items:
            unpacked = records_subspace.unpack(key)
            stored = self._load_record_sync(record_type_name, unpacked)
            if stored is not None:
                all_records.append(stored)
                count += 1
                if limit > 0 and count >= limit:
                    break

        return ListCursor(all_records)

    async def save_records(self, records: list[M]) -> list[FDBStoredRecord[M]]:
        """Save multiple records efficiently.

        Uses batched reads to minimize N+1 query patterns.

        Args:
            records: The records to save.

        Returns:
            List of stored records.
        """
        if not records:
            return []

        start_time = time.perf_counter()
        self._context.ensure_active()

        # Group records by type and compute primary keys
        records_info: list[tuple[str, tuple[Any, ...], M, Any]] = []
        for record in records:
            record_type_name = record.DESCRIPTOR.name
            if not self._meta_data.has_record_type(record_type_name):
                raise RecordTypeNotFoundException(record_type_name)

            record_type = self._meta_data.get_record_type(record_type_name)
            primary_key_values = record_type.primary_key.evaluate(record)
            if len(primary_key_values) != 1:
                raise InvalidPrimaryKeyException("Primary key must evaluate to exactly one value")
            primary_key = primary_key_values[0]
            records_info.append((record_type_name, primary_key, record, record_type))

        # Batch load existing records (reduces N+1 queries)
        old_records: dict[tuple[str, tuple[Any, ...]], Any] = {}
        for record_type_name, primary_key, _, _ in records_info:
            key = (record_type_name, primary_key)
            old_records[key] = await self._load_raw_record(record_type_name, primary_key)

        # Batch write new records
        results = []
        for record_type_name, primary_key, record, record_type in records_info:
            old_record = old_records.get((record_type_name, primary_key))

            # Serialize and store
            record_key = self._records_subspace[record_type_name].pack(primary_key)
            record_bytes = self._serializer.serialize(record)
            self.transaction.set(record_key, record_bytes)

            # Update indexes
            await self._update_indexes(record_type, primary_key, old_record, record)

            results.append(
                FDBStoredRecord(
                    primary_key=primary_key,
                    record=record,
                    record_type=record_type,
                )
            )

        duration_ms = (time.perf_counter() - start_time) * 1000
        _logger.debug(
            "Batch save completed",
            extra={
                "record_count": len(records),
                "duration_ms": round(duration_ms, 2),
            },
        )

        return results

    async def delete_records(
        self,
        record_type_name: str,
        primary_keys: list[tuple[Any, ...]],
    ) -> int:
        """Delete multiple records efficiently.

        Uses batched reads to minimize N+1 query patterns.

        Args:
            record_type_name: The record type name.
            primary_keys: The primary keys to delete.

        Returns:
            Number of records deleted.
        """
        if not primary_keys:
            return 0

        start_time = time.perf_counter()
        self._context.ensure_active()

        if not self._meta_data.has_record_type(record_type_name):
            raise RecordTypeNotFoundException(record_type_name)

        record_type = self._meta_data.get_record_type(record_type_name)

        # Batch load existing records using optimized batch method
        old_records = await self._load_raw_records_batch(record_type_name, primary_keys)

        # Batch delete and update indexes
        deleted = 0
        for pk in primary_keys:
            old_record = old_records.get(pk)
            if old_record is None:
                continue

            # Delete record
            record_key = self._records_subspace[record_type_name].pack(pk)
            self.transaction.clear(record_key)

            # Update indexes (remove old entries)
            await self._update_indexes(record_type, pk, old_record, None)
            deleted += 1

        duration_ms = (time.perf_counter() - start_time) * 1000
        _logger.debug(
            "Batch delete completed",
            extra={
                "record_type": record_type_name,
                "requested_count": len(primary_keys),
                "deleted_count": deleted,
                "duration_ms": round(duration_ms, 2),
            },
        )

        return deleted


class FDBRecordStoreBuilder:
    """Builder for FDBRecordStore instances."""

    def __init__(self) -> None:
        self._context: FDBRecordContext | None = None
        self._subspace: Subspace | None = None
        self._meta_data: RecordMetaData | None = None
        self._serializer: RecordSerializer | None = None

    def set_context(self, context: FDBRecordContext) -> FDBRecordStoreBuilder:
        """Set the record context."""
        self._context = context
        return self

    def set_subspace(self, subspace: Subspace) -> FDBRecordStoreBuilder:
        """Set the subspace."""
        self._subspace = subspace
        return self

    def set_meta_data(self, meta_data: RecordMetaData) -> FDBRecordStoreBuilder:
        """Set the metadata."""
        self._meta_data = meta_data
        return self

    def set_serializer(self, serializer: RecordSerializer) -> FDBRecordStoreBuilder:
        """Set the serializer."""
        self._serializer = serializer
        return self

    def build(self) -> FDBRecordStore[Any]:
        """Build the record store."""
        if self._context is None:
            raise ValueError("Context is required")
        if self._subspace is None:
            raise ValueError("Subspace is required")
        if self._meta_data is None:
            raise ValueError("MetaData is required")

        return FDBRecordStore(
            context=self._context,
            subspace=self._subspace,
            meta_data=self._meta_data,
            serializer=self._serializer,
        )
