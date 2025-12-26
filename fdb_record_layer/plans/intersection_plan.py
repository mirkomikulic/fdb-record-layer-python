"""Intersection plan for AND queries on multiple indexes."""

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


class IntersectionPlan(RecordQueryPlanWithChildren[M]):
    """A plan that intersects results from multiple child plans.

    IntersectionPlan is used when an AND query can use multiple
    indexes. Only records that appear in ALL children are returned.

    Attributes:
        children: The child plans to intersect.
    """

    def __init__(self, children: list[RecordQueryPlan[M]]) -> None:
        """Initialize the intersection plan.

        Args:
            children: The child plans.
        """
        super().__init__(children)

    async def execute(
        self,
        context: ExecutionContext,
        continuation: bytes | None = None,
    ) -> RecordCursor[FDBStoredRecord[M]]:
        """Execute the intersection plan.

        Uses set intersection on primary keys.

        Args:
            context: The execution context.
            continuation: Optional continuation.

        Returns:
            A cursor over intersected results.
        """
        from fdb_record_layer.cursors.base import ListCursor

        if not self._children:
            return ListCursor([])

        # Execute first child and collect primary keys
        first_cursor = await self._children[0].execute(context, continuation)
        key_to_record: dict[tuple[Any, ...], FDBStoredRecord[M]] = {}

        async for stored in first_cursor:
            key_to_record[stored.primary_key] = stored

        # For each subsequent child, filter to only keep common keys
        for child in self._children[1:]:
            if not key_to_record:
                # No common records, short-circuit
                break

            cursor = await child.execute(context, continuation)
            child_keys: set[tuple[Any, ...]] = set()

            async for stored in cursor:
                child_keys.add(stored.primary_key)

            # Keep only keys present in this child
            keys_to_remove = set(key_to_record.keys()) - child_keys
            for key in keys_to_remove:
                del key_to_record[key]

        return ListCursor(list(key_to_record.values()))

    def explain(self, indent: int = 0) -> str:
        """Explain the intersection plan."""
        prefix = " " * indent
        lines = [f"{prefix}Intersection()"]
        for child in self._children:
            lines.append(child.explain(indent + 2))
        return "\n".join(lines)

    def get_complexity(self) -> PlanComplexity:
        """Intersection takes the min estimated rows."""
        if not self._children:
            return PlanComplexity()

        min_rows = float("inf")
        total_index_scans = 0
        total_full_scans = 0
        max_filter_complexity = 0

        for child in self._children:
            child_complexity = child.get_complexity()
            min_rows = min(min_rows, child_complexity.estimated_rows)
            total_index_scans += child_complexity.index_scans
            total_full_scans += child_complexity.full_scans
            max_filter_complexity = max(max_filter_complexity, child_complexity.filter_complexity)

        return PlanComplexity(
            estimated_rows=int(min_rows) if min_rows != float("inf") else 0,
            index_scans=total_index_scans,
            full_scans=total_full_scans,
            filter_complexity=max_filter_complexity,
        )


class MergeIntersectionPlan(IntersectionPlan[M]):
    """An intersection plan that uses merge-join semantics.

    More efficient when children return sorted results by
    the same key.
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
        super().__init__(children)
        self._comparison_key_fn = comparison_key_fn

    async def execute(
        self,
        context: ExecutionContext,
        continuation: bytes | None = None,
    ) -> RecordCursor[FDBStoredRecord[M]]:
        """Execute using merge semantics.

        Falls back to hash-based intersection for now.
        TODO: Implement true merge join when cursors are sorted.
        """
        # For now, use the base class implementation
        return await super().execute(context, continuation)

    def explain(self, indent: int = 0) -> str:
        """Explain the merge intersection plan."""
        prefix = " " * indent
        lines = [f"{prefix}MergeIntersection()"]
        for child in self._children:
            lines.append(child.explain(indent + 2))
        return "\n".join(lines)
