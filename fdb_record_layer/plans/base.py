"""Base classes for query execution plans."""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, Generic, TypeVar

if TYPE_CHECKING:
    from fdb import Transaction
    from google.protobuf.message import Message

    from fdb_record_layer.core.record import FDBStoredRecord
    from fdb_record_layer.core.store import FDBRecordStore
    from fdb_record_layer.cursors.base import RecordCursor

M = TypeVar("M", bound="Message")


@dataclass
class ExecutionContext:
    """Context for plan execution.

    Provides access to the record store, transaction, and parameter
    bindings during query execution.

    Attributes:
        store: The record store.
        bindings: Parameter bindings for the query.
    """

    store: FDBRecordStore[Any]
    bindings: dict[str, Any] | None = None

    @property
    def transaction(self) -> Transaction:
        """Get the FDB transaction."""
        return self.store.transaction


class RecordQueryPlan(ABC, Generic[M]):
    """Abstract base class for query execution plans.

    A RecordQueryPlan represents an executable plan that produces
    records. Plans can be composed hierarchically.

    Plans should be immutable after creation.
    """

    @abstractmethod
    async def execute(
        self,
        context: ExecutionContext,
        continuation: bytes | None = None,
    ) -> RecordCursor[FDBStoredRecord[M]]:
        """Execute the plan and return a cursor over results.

        Args:
            context: The execution context.
            continuation: Optional continuation for resuming.

        Returns:
            A cursor over matching records.
        """
        pass

    @abstractmethod
    def explain(self, indent: int = 0) -> str:
        """Return a human-readable explanation of the plan.

        Args:
            indent: Indentation level for nested plans.

        Returns:
            A string explaining the plan.
        """
        pass

    @abstractmethod
    def get_complexity(self) -> PlanComplexity:
        """Get the estimated complexity of this plan.

        Returns:
            The plan complexity estimate.
        """
        pass

    def has_full_scan(self) -> bool:
        """Check if this plan includes a full table scan.

        Returns:
            True if a full scan is involved.
        """
        return False

    def uses_index(self, index_name: str) -> bool:
        """Check if this plan uses a specific index.

        Args:
            index_name: The index name to check.

        Returns:
            True if the index is used.
        """
        return False

    def get_used_indexes(self) -> set[str]:
        """Get all indexes used by this plan.

        Returns:
            Set of index names.
        """
        return set()


@dataclass
class PlanComplexity:
    """Estimated complexity of a query plan.

    This is used for plan comparison and selection.

    Attributes:
        estimated_rows: Estimated number of rows to examine.
        index_scans: Number of index scans.
        full_scans: Number of full table scans.
        filter_complexity: Complexity of post-scan filtering.
    """

    estimated_rows: int = 0
    index_scans: int = 0
    full_scans: int = 0
    filter_complexity: int = 0

    def total_cost(self) -> int:
        """Calculate a total cost score.

        Lower is better.

        Returns:
            The total cost.
        """
        # Full scans are very expensive
        full_scan_cost = self.full_scans * 1000000

        # Index scans are relatively cheap
        index_cost = self.index_scans * 100

        # Row examination has base cost
        row_cost = self.estimated_rows * 10

        # Filter cost is per-row
        filter_cost = self.estimated_rows * self.filter_complexity

        return full_scan_cost + index_cost + row_cost + filter_cost

    def __lt__(self, other: PlanComplexity) -> bool:
        """Compare plans by total cost."""
        return self.total_cost() < other.total_cost()


class RecordQueryPlanWithChild(RecordQueryPlan[M]):
    """Base class for plans with a single child plan.

    Attributes:
        child: The child plan.
    """

    def __init__(self, child: RecordQueryPlan[M]) -> None:
        self._child = child

    @property
    def child(self) -> RecordQueryPlan[M]:
        """Get the child plan."""
        return self._child

    def has_full_scan(self) -> bool:
        """Delegate to child."""
        return self._child.has_full_scan()

    def uses_index(self, index_name: str) -> bool:
        """Delegate to child."""
        return self._child.uses_index(index_name)

    def get_used_indexes(self) -> set[str]:
        """Delegate to child."""
        return self._child.get_used_indexes()


class RecordQueryPlanWithChildren(RecordQueryPlan[M]):
    """Base class for plans with multiple children.

    Attributes:
        children: The child plans.
    """

    def __init__(self, children: list[RecordQueryPlan[M]]) -> None:
        self._children = children

    @property
    def children(self) -> list[RecordQueryPlan[M]]:
        """Get the child plans."""
        return self._children

    def has_full_scan(self) -> bool:
        """Check if any child has a full scan."""
        return any(child.has_full_scan() for child in self._children)

    def uses_index(self, index_name: str) -> bool:
        """Check if any child uses the index."""
        return any(child.uses_index(index_name) for child in self._children)

    def get_used_indexes(self) -> set[str]:
        """Get all indexes used by children."""
        indexes: set[str] = set()
        for child in self._children:
            indexes.update(child.get_used_indexes())
        return indexes


class EmptyPlan(RecordQueryPlan[M]):
    """A plan that returns no results.

    Used when the query is provably unsatisfiable.
    """

    async def execute(
        self,
        context: ExecutionContext,
        continuation: bytes | None = None,
    ) -> RecordCursor[FDBStoredRecord[M]]:
        """Return an empty cursor."""
        from fdb_record_layer.cursors.base import ListCursor

        return ListCursor([])

    def explain(self, indent: int = 0) -> str:
        """Explain the empty plan."""
        return " " * indent + "Empty()"

    def get_complexity(self) -> PlanComplexity:
        """Empty plans have zero complexity."""
        return PlanComplexity()
