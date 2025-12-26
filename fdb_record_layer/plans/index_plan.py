"""Index scan execution plan."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, TypeVar

from fdb_record_layer.indexes.maintainer import IndexScanRange
from fdb_record_layer.planner.scan_comparisons import (
    IndexScanBounds,
    ScanComparisons,
)
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


class IndexScanPlan(RecordQueryPlan[M]):
    """A plan that uses an index to scan records.

    This is the preferred plan when an index can satisfy the query
    predicates. Much more efficient than a full table scan.

    Attributes:
        index_name: The name of the index to use.
        scan_comparisons: The comparisons for the scan bounds.
        reverse: Whether to scan in reverse order.
    """

    def __init__(
        self,
        index_name: str,
        scan_comparisons: ScanComparisons | None = None,
        reverse: bool = False,
    ) -> None:
        """Initialize the index scan plan.

        Args:
            index_name: The name of the index to use.
            scan_comparisons: Comparisons defining scan bounds.
            reverse: Whether to scan in reverse order.
        """
        self._index_name = index_name
        self._scan_comparisons = scan_comparisons or ScanComparisons()
        self._reverse = reverse

    @property
    def index_name(self) -> str:
        """Get the index name."""
        return self._index_name

    @property
    def scan_comparisons(self) -> ScanComparisons:
        """Get the scan comparisons."""
        return self._scan_comparisons

    @property
    def reverse(self) -> bool:
        """Check if reverse scan."""
        return self._reverse

    async def execute(
        self,
        context: ExecutionContext,
        continuation: bytes | None = None,
    ) -> RecordCursor[FDBStoredRecord[M]]:
        """Execute the index scan.

        Args:
            context: The execution context.
            continuation: Optional continuation for resuming.

        Returns:
            A cursor over matching records.
        """
        store = context.store
        bindings = context.bindings

        # Convert scan comparisons to IndexScanRange
        bounds = IndexScanBounds.from_scan_comparisons(self._scan_comparisons, bindings)

        scan_range = self._bounds_to_scan_range(bounds)

        # Use the store's scan_index method
        return await store.scan_index(
            self._index_name,
            scan_range=scan_range,
            continuation=continuation,
        )

    def _bounds_to_scan_range(self, bounds: IndexScanBounds) -> IndexScanRange:
        """Convert IndexScanBounds to IndexScanRange.

        Args:
            bounds: The index scan bounds.

        Returns:
            An IndexScanRange for the index maintainer.
        """
        from fdb_record_layer.planner.scan_comparisons import ScanBoundType

        # Start with prefix
        low: list[Any] = list(bounds.prefix)
        high: list[Any] = list(bounds.prefix)

        # Add range bounds if present
        if not bounds.range.low.is_unbounded():
            low.append(bounds.range.low.value)

        if not bounds.range.high.is_unbounded():
            high.append(bounds.range.high.value)

        # Determine inclusivity
        low_inclusive = (
            bounds.range.low.is_unbounded()
            or bounds.range.low.bound_type == ScanBoundType.INCLUSIVE
        )
        high_inclusive = (
            bounds.range.high.is_unbounded()
            or bounds.range.high.bound_type == ScanBoundType.INCLUSIVE
        )

        return IndexScanRange(
            low=tuple(low) if low else None,
            high=tuple(high) if high else None,
            low_inclusive=low_inclusive,
            high_inclusive=high_inclusive,
        )

    def explain(self, indent: int = 0) -> str:
        """Explain the index scan plan."""
        prefix = " " * indent
        details = [f"index={self._index_name}"]

        if self._scan_comparisons.equality_comparisons:
            eq_count = len(self._scan_comparisons.equality_comparisons)
            details.append(f"eq_count={eq_count}")

        if self._scan_comparisons.inequality_comparisons:
            details.append("has_range=true")

        if self._reverse:
            details.append("reverse=true")

        return f"{prefix}IndexScan({', '.join(details)})"

    def get_complexity(self) -> PlanComplexity:
        """Index scans are efficient."""
        # Estimate based on scan type
        if self._scan_comparisons.is_equality_only():
            # Point lookup - very efficient
            estimated = 10
        elif self._scan_comparisons.has_inequality():
            # Range scan - moderately efficient
            estimated = 1000
        else:
            # Full index scan - still better than table scan
            estimated = 10000

        return PlanComplexity(
            estimated_rows=estimated,
            index_scans=1,
        )

    def uses_index(self, index_name: str) -> bool:
        """Check if this plan uses the specified index."""
        return self._index_name == index_name

    def get_used_indexes(self) -> set[str]:
        """Get the index used by this plan."""
        return {self._index_name}


class CoveringIndexScanPlan(IndexScanPlan[M]):
    """An index scan that returns all needed fields from the index.

    A covering index scan doesn't need to fetch the full record
    because all required fields are in the index key or value.

    This is more efficient than a regular index scan followed by
    record fetch.
    """

    def __init__(
        self,
        index_name: str,
        scan_comparisons: ScanComparisons | None = None,
        reverse: bool = False,
        projected_fields: list[str] | None = None,
    ) -> None:
        """Initialize the covering index scan.

        Args:
            index_name: The name of the index.
            scan_comparisons: Comparisons for scan bounds.
            reverse: Whether to scan in reverse.
            projected_fields: Fields available from the index.
        """
        super().__init__(index_name, scan_comparisons, reverse)
        self._projected_fields = projected_fields or []

    def explain(self, indent: int = 0) -> str:
        """Explain the covering scan."""
        base = super().explain(indent)
        return base.replace("IndexScan", "CoveringIndexScan")

    def get_complexity(self) -> PlanComplexity:
        """Covering scans are more efficient."""
        base_complexity = super().get_complexity()
        # Reduce estimated rows since we don't fetch records
        return PlanComplexity(
            estimated_rows=base_complexity.estimated_rows // 2,
            index_scans=1,
        )


class IndexScanPlanBuilder:
    """Builder for IndexScanPlan instances."""

    def __init__(self, index_name: str) -> None:
        self._index_name = index_name
        self._scan_comparisons = ScanComparisons()
        self._reverse = False

    def with_comparisons(self, comparisons: ScanComparisons) -> IndexScanPlanBuilder:
        """Set the scan comparisons."""
        self._scan_comparisons = comparisons
        return self

    def reverse(self, is_reverse: bool = True) -> IndexScanPlanBuilder:
        """Set reverse scan order."""
        self._reverse = is_reverse
        return self

    def build(self) -> IndexScanPlan[Any]:
        """Build the index scan plan."""
        return IndexScanPlan(
            index_name=self._index_name,
            scan_comparisons=self._scan_comparisons,
            reverse=self._reverse,
        )
