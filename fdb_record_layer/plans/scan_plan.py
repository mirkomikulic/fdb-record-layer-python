"""Full table scan plan."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, TypeVar

from fdb_record_layer.plans.base import (
    ExecutionContext,
    PlanComplexity,
    RecordQueryPlan,
)

if TYPE_CHECKING:
    from google.protobuf.message import Message

    from fdb_record_layer.core.record import FDBStoredRecord
    from fdb_record_layer.cursors.base import RecordCursor

M = TypeVar("M", bound="Message")


class ScanPlan(RecordQueryPlan[M]):
    """A plan that performs a full table scan.

    This is the fallback when no index can satisfy the query.
    All records of the specified type(s) are scanned.

    Attributes:
        record_types: The record types to scan.
    """

    def __init__(self, record_types: list[str]) -> None:
        """Initialize the scan plan.

        Args:
            record_types: The record types to scan.
        """
        self._record_types = record_types

    @property
    def record_types(self) -> list[str]:
        """Get the record types being scanned."""
        return self._record_types

    async def execute(
        self,
        context: ExecutionContext,
        continuation: bytes | None = None,
    ) -> RecordCursor[FDBStoredRecord[M]]:
        """Execute a full table scan.

        Args:
            context: The execution context.
            continuation: Optional continuation for resuming.

        Returns:
            A cursor over all records of the specified types.
        """
        from fdb_record_layer.cursors.base import (
            ListCursor,
        )

        store = context.store
        transaction = context.transaction

        # Get the records subspace for each type
        all_records: list[FDBStoredRecord[Any]] = []

        for record_type_name in self._record_types:
            if not store.meta_data.has_record_type(record_type_name):
                continue

            records_subspace = store._records_subspace[record_type_name]

            # Range scan all records in this subspace
            start_key = records_subspace.range().start
            end_key = records_subspace.range().stop

            # Use FDB range read
            for key, value in transaction.get_range(start_key, end_key):
                # Unpack the key to get primary key
                unpacked = records_subspace.unpack(key)

                # Load the record (handles deserialization internally)
                stored = store._load_record_sync(record_type_name, unpacked)
                if stored is not None:
                    all_records.append(stored)

        # Filter out None results
        all_records = [r for r in all_records if r is not None]

        return ListCursor(all_records)

    def explain(self, indent: int = 0) -> str:
        """Explain the scan plan."""
        prefix = " " * indent
        types_str = ", ".join(self._record_types)
        return f"{prefix}Scan([{types_str}])"

    def get_complexity(self) -> PlanComplexity:
        """Full scans are expensive."""
        return PlanComplexity(
            estimated_rows=100000,  # Unknown, assume large
            full_scans=1,
        )

    def has_full_scan(self) -> bool:
        """This is a full scan."""
        return True


class TypeScanPlan(RecordQueryPlan[M]):
    """A plan that scans a single record type.

    More efficient than ScanPlan when only one type is needed.

    Attributes:
        record_type: The record type to scan.
    """

    def __init__(self, record_type: str) -> None:
        """Initialize the type scan plan.

        Args:
            record_type: The record type to scan.
        """
        self._record_type = record_type

    @property
    def record_type(self) -> str:
        """Get the record type being scanned."""
        return self._record_type

    async def execute(
        self,
        context: ExecutionContext,
        continuation: bytes | None = None,
    ) -> RecordCursor[FDBStoredRecord[M]]:
        """Execute the type scan.

        Args:
            context: The execution context.
            continuation: Optional continuation for resuming.

        Returns:
            A cursor over all records of this type.
        """
        from fdb_record_layer.cursors.base import ListCursor

        store = context.store
        transaction = context.transaction

        if not store.meta_data.has_record_type(self._record_type):
            return ListCursor([])

        records_subspace = store._records_subspace[self._record_type]

        # Range scan all records
        start_key = records_subspace.range().start
        end_key = records_subspace.range().stop

        all_records: list[FDBStoredRecord[Any]] = []

        for key, value in transaction.get_range(start_key, end_key):
            unpacked = records_subspace.unpack(key)
            stored = store._load_record_sync(self._record_type, unpacked)
            if stored is not None:
                all_records.append(stored)

        return ListCursor(all_records)

    def explain(self, indent: int = 0) -> str:
        """Explain the type scan plan."""
        prefix = " " * indent
        return f"{prefix}TypeScan({self._record_type})"

    def get_complexity(self) -> PlanComplexity:
        """Type scans are still expensive."""
        return PlanComplexity(
            estimated_rows=50000,  # Assume moderate size
            full_scans=1,
        )

    def has_full_scan(self) -> bool:
        """This is a full scan of one type."""
        return True
