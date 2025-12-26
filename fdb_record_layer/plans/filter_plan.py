"""Filter execution plan for post-scan predicate evaluation."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, TypeVar

from fdb_record_layer.plans.base import (
    ExecutionContext,
    PlanComplexity,
    RecordQueryPlan,
    RecordQueryPlanWithChild,
)

if TYPE_CHECKING:
    from google.protobuf.message import Message

    from fdb_record_layer.core.record import FDBStoredRecord
    from fdb_record_layer.cursors.base import RecordCursor
    from fdb_record_layer.query.components import QueryComponent

M = TypeVar("M", bound="Message")


class FilterPlan(RecordQueryPlanWithChild[M]):
    """A plan that filters results from a child plan.

    FilterPlan applies residual predicates that couldn't be
    satisfied by index scans. It wraps another plan and filters
    its output.

    Attributes:
        child: The child plan to filter.
        filter: The filter predicate.
    """

    def __init__(
        self,
        child: RecordQueryPlan[M],
        filter_component: QueryComponent,
    ) -> None:
        """Initialize the filter plan.

        Args:
            child: The child plan.
            filter_component: The filter to apply.
        """
        super().__init__(child)
        self._filter = filter_component

    @property
    def filter(self) -> QueryComponent:
        """Get the filter component."""
        return self._filter

    async def execute(
        self,
        context: ExecutionContext,
        continuation: bytes | None = None,
    ) -> RecordCursor[FDBStoredRecord[M]]:
        """Execute the filter plan.

        Args:
            context: The execution context.
            continuation: Optional continuation for resuming.

        Returns:
            A cursor over filtered records.
        """
        from fdb_record_layer.cursors.base import FilterCursor

        # Execute child plan
        child_cursor = await self._child.execute(context, continuation)

        # Wrap with filter
        def predicate(stored: FDBStoredRecord[Any]) -> bool:
            return self._filter.evaluate(stored.record, context.bindings)

        return FilterCursor(child_cursor, predicate)

    def explain(self, indent: int = 0) -> str:
        """Explain the filter plan."""
        prefix = " " * indent
        child_explain = self._child.explain(indent + 2)
        filter_str = str(self._filter)
        return f"{prefix}Filter({filter_str})\n{child_explain}"

    def get_complexity(self) -> PlanComplexity:
        """Filter adds complexity to child."""
        child_complexity = self._child.get_complexity()
        return PlanComplexity(
            estimated_rows=child_complexity.estimated_rows // 2,  # Assume 50% selectivity
            index_scans=child_complexity.index_scans,
            full_scans=child_complexity.full_scans,
            filter_complexity=child_complexity.filter_complexity + 1,
        )


class RecordTypeFilterPlan(RecordQueryPlanWithChild[M]):
    """A plan that filters by record type.

    Used when querying specific record types from a store
    that contains multiple types.

    Attributes:
        child: The child plan.
        record_types: The record types to accept.
    """

    def __init__(
        self,
        child: RecordQueryPlan[M],
        record_types: list[str],
    ) -> None:
        """Initialize the record type filter.

        Args:
            child: The child plan.
            record_types: Record types to accept.
        """
        super().__init__(child)
        self._record_types = set(record_types)

    @property
    def record_types(self) -> set[str]:
        """Get the accepted record types."""
        return self._record_types

    async def execute(
        self,
        context: ExecutionContext,
        continuation: bytes | None = None,
    ) -> RecordCursor[FDBStoredRecord[M]]:
        """Execute the record type filter.

        Args:
            context: The execution context.
            continuation: Optional continuation.

        Returns:
            A cursor over matching records.
        """
        from fdb_record_layer.cursors.base import FilterCursor

        child_cursor = await self._child.execute(context, continuation)

        def predicate(stored: FDBStoredRecord[Any]) -> bool:
            return stored.record_type.name in self._record_types

        return FilterCursor(child_cursor, predicate)

    def explain(self, indent: int = 0) -> str:
        """Explain the record type filter."""
        prefix = " " * indent
        child_explain = self._child.explain(indent + 2)
        types_str = ", ".join(self._record_types)
        return f"{prefix}RecordTypeFilter([{types_str}])\n{child_explain}"

    def get_complexity(self) -> PlanComplexity:
        """Record type filter is lightweight."""
        child_complexity = self._child.get_complexity()
        return PlanComplexity(
            estimated_rows=child_complexity.estimated_rows,
            index_scans=child_complexity.index_scans,
            full_scans=child_complexity.full_scans,
            filter_complexity=child_complexity.filter_complexity,
        )


class LimitPlan(RecordQueryPlanWithChild[M]):
    """A plan that limits the number of results.

    Attributes:
        child: The child plan.
        limit: Maximum number of results.
    """

    def __init__(
        self,
        child: RecordQueryPlan[M],
        limit: int,
    ) -> None:
        """Initialize the limit plan.

        Args:
            child: The child plan.
            limit: Maximum results to return.
        """
        super().__init__(child)
        self._limit = limit

    @property
    def limit(self) -> int:
        """Get the limit."""
        return self._limit

    async def execute(
        self,
        context: ExecutionContext,
        continuation: bytes | None = None,
    ) -> RecordCursor[FDBStoredRecord[M]]:
        """Execute the limit plan.

        Args:
            context: The execution context.
            continuation: Optional continuation.

        Returns:
            A cursor with limited results.
        """
        from fdb_record_layer.cursors.base import LimitCursor

        child_cursor = await self._child.execute(context, continuation)
        return LimitCursor(child_cursor, self._limit)

    def explain(self, indent: int = 0) -> str:
        """Explain the limit plan."""
        prefix = " " * indent
        child_explain = self._child.explain(indent + 2)
        return f"{prefix}Limit({self._limit})\n{child_explain}"

    def get_complexity(self) -> PlanComplexity:
        """Limit reduces estimated rows."""
        child_complexity = self._child.get_complexity()
        return PlanComplexity(
            estimated_rows=min(self._limit, child_complexity.estimated_rows),
            index_scans=child_complexity.index_scans,
            full_scans=child_complexity.full_scans,
            filter_complexity=child_complexity.filter_complexity,
        )


class SkipPlan(RecordQueryPlanWithChild[M]):
    """A plan that skips initial results.

    Attributes:
        child: The child plan.
        skip: Number of results to skip.
    """

    def __init__(
        self,
        child: RecordQueryPlan[M],
        skip: int,
    ) -> None:
        """Initialize the skip plan.

        Args:
            child: The child plan.
            skip: Number of results to skip.
        """
        super().__init__(child)
        self._skip = skip

    @property
    def skip(self) -> int:
        """Get the skip count."""
        return self._skip

    async def execute(
        self,
        context: ExecutionContext,
        continuation: bytes | None = None,
    ) -> RecordCursor[FDBStoredRecord[M]]:
        """Execute the skip plan.

        Args:
            context: The execution context.
            continuation: Optional continuation.

        Returns:
            A cursor with skipped results.
        """
        from fdb_record_layer.cursors.base import SkipCursor

        child_cursor = await self._child.execute(context, continuation)
        return SkipCursor(child_cursor, self._skip)

    def explain(self, indent: int = 0) -> str:
        """Explain the skip plan."""
        prefix = " " * indent
        child_explain = self._child.explain(indent + 2)
        return f"{prefix}Skip({self._skip})\n{child_explain}"

    def get_complexity(self) -> PlanComplexity:
        """Skip still processes all child rows."""
        child_complexity = self._child.get_complexity()
        return PlanComplexity(
            estimated_rows=max(0, child_complexity.estimated_rows - self._skip),
            index_scans=child_complexity.index_scans,
            full_scans=child_complexity.full_scans,
            filter_complexity=child_complexity.filter_complexity,
        )
