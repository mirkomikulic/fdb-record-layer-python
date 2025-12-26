"""Union plan for OR queries."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, TypeVar

from fdb_record_layer.plans.base import (
    ExecutionContext,
    PlanComplexity,
    RecordQueryPlan,
    RecordQueryPlanWithChildren,
)

if TYPE_CHECKING:
    from google.protobuf.message import Message

    from fdb_record_layer.core.record import FDBStoredRecord
    from fdb_record_layer.cursors.base import RecordCursor

M = TypeVar("M", bound="Message")


class UnionPlan(RecordQueryPlanWithChildren[M]):
    """A plan that unions results from multiple child plans.

    UnionPlan is used for OR queries where different branches
    might use different indexes. It combines results from all
    children and removes duplicates.

    Attributes:
        children: The child plans to union.
        remove_duplicates: Whether to deduplicate results.
    """

    def __init__(
        self,
        children: list[RecordQueryPlan[M]],
        remove_duplicates: bool = True,
    ) -> None:
        """Initialize the union plan.

        Args:
            children: The child plans.
            remove_duplicates: Whether to remove duplicates.
        """
        super().__init__(children)
        self._remove_duplicates = remove_duplicates

    @property
    def remove_duplicates(self) -> bool:
        """Check if duplicates are removed."""
        return self._remove_duplicates

    async def execute(
        self,
        context: ExecutionContext,
        continuation: bytes | None = None,
    ) -> RecordCursor[FDBStoredRecord[M]]:
        """Execute the union plan.

        Executes all children and merges their results.

        Args:
            context: The execution context.
            continuation: Optional continuation.

        Returns:
            A cursor over combined results.
        """
        from fdb_record_layer.cursors.base import ListCursor

        all_results: list[FDBStoredRecord[M]] = []
        seen_keys: set[tuple[Any, ...]] = set()

        # Execute all children and collect results
        for child in self._children:
            cursor = await child.execute(context, continuation)

            async for stored in cursor:
                pk = stored.primary_key

                if self._remove_duplicates:
                    if pk not in seen_keys:
                        seen_keys.add(pk)
                        all_results.append(stored)
                else:
                    all_results.append(stored)

        return ListCursor(all_results)

    def explain(self, indent: int = 0) -> str:
        """Explain the union plan."""
        prefix = " " * indent
        lines = [f"{prefix}Union(remove_duplicates={self._remove_duplicates})"]
        for child in self._children:
            lines.append(child.explain(indent + 2))
        return "\n".join(lines)

    def get_complexity(self) -> PlanComplexity:
        """Union combines child complexities."""
        total_rows = 0
        total_index_scans = 0
        total_full_scans = 0
        max_filter_complexity = 0

        for child in self._children:
            child_complexity = child.get_complexity()
            total_rows += child_complexity.estimated_rows
            total_index_scans += child_complexity.index_scans
            total_full_scans += child_complexity.full_scans
            max_filter_complexity = max(max_filter_complexity, child_complexity.filter_complexity)

        return PlanComplexity(
            estimated_rows=total_rows,
            index_scans=total_index_scans,
            full_scans=total_full_scans,
            filter_complexity=max_filter_complexity,
        )


class UnionOnExpressionPlan(UnionPlan[M]):
    """A union plan that uses a comparison key for deduplication.

    This allows deduplication on a specific expression rather than
    the full primary key.
    """

    def __init__(
        self,
        children: list[RecordQueryPlan[M]],
        comparison_key_fn: Any,  # Callable[[FDBStoredRecord], Any]
    ) -> None:
        """Initialize with comparison key function.

        Args:
            children: The child plans.
            comparison_key_fn: Function to extract comparison key.
        """
        super().__init__(children, remove_duplicates=True)
        self._comparison_key_fn = comparison_key_fn

    async def execute(
        self,
        context: ExecutionContext,
        continuation: bytes | None = None,
    ) -> RecordCursor[FDBStoredRecord[M]]:
        """Execute with custom deduplication."""
        from fdb_record_layer.cursors.base import ListCursor

        all_results: list[FDBStoredRecord[M]] = []
        seen_keys: set[Any] = set()

        for child in self._children:
            cursor = await child.execute(context, continuation)

            async for stored in cursor:
                key = self._comparison_key_fn(stored)

                if key not in seen_keys:
                    seen_keys.add(key)
                    all_results.append(stored)

        return ListCursor(all_results)

    def explain(self, indent: int = 0) -> str:
        """Explain the union on expression plan."""
        prefix = " " * indent
        lines = [f"{prefix}UnionOnExpression()"]
        for child in self._children:
            lines.append(child.explain(indent + 2))
        return "\n".join(lines)
