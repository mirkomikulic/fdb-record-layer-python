"""Cost model for Cascades optimizer.

The cost model estimates the cost of executing different physical plans,
enabling the optimizer to select the cheapest plan.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from fdb_record_layer.metadata.record_metadata import RecordMetaData
    from fdb_record_layer.planner.cascades.memo import GroupExpression


@dataclass
class Statistics:
    """Statistics about a data set used for cost estimation."""

    row_count: float = 1000.0  # Estimated number of rows
    avg_row_size: float = 100.0  # Average row size in bytes
    distinct_values: dict[str, float] = field(default_factory=dict)  # Per-column
    null_fraction: dict[str, float] = field(default_factory=dict)  # Per-column
    min_values: dict[str, Any] = field(default_factory=dict)
    max_values: dict[str, Any] = field(default_factory=dict)

    def selectivity(self, field_name: str, predicate_type: str) -> float:
        """Estimate selectivity for a predicate on a field.

        Returns fraction of rows that pass the predicate (0.0 to 1.0).
        """
        distinct = self.distinct_values.get(field_name, 100.0)

        if predicate_type == "EQUALS":
            # Assume uniform distribution
            return 1.0 / distinct
        elif predicate_type == "NOT_EQUALS":
            return 1.0 - (1.0 / distinct)
        elif predicate_type in ("GREATER_THAN", "LESS_THAN"):
            # Assume range covers half the values
            return 0.5
        elif predicate_type in ("GREATER_OR_EQUALS", "LESS_OR_EQUALS"):
            return 0.5 + (1.0 / distinct)
        elif predicate_type == "IN":
            # Depends on IN list size, default to 10%
            return 0.1
        elif predicate_type == "IS_NULL":
            return self.null_fraction.get(field_name, 0.01)
        elif predicate_type == "IS_NOT_NULL":
            return 1.0 - self.null_fraction.get(field_name, 0.01)
        elif predicate_type == "STARTS_WITH":
            # Prefix match - typically more selective
            return 0.1
        else:
            # Default selectivity
            return 0.5

    def merge(self, other: Statistics) -> Statistics:
        """Merge statistics from two sources (e.g., for union)."""
        return Statistics(
            row_count=self.row_count + other.row_count,
            avg_row_size=(self.avg_row_size + other.avg_row_size) / 2,
            distinct_values={
                **self.distinct_values,
                **other.distinct_values,
            },
        )


@dataclass
class Cost:
    """Represents the estimated cost of a plan.

    Cost is modeled as a combination of:
    - CPU cost (processing time)
    - I/O cost (disk/network reads)
    - Memory cost (memory usage)
    """

    cpu: float = 0.0
    io: float = 0.0
    memory: float = 0.0
    network: float = 0.0

    @property
    def total(self) -> float:
        """Total cost as a weighted sum."""
        # I/O is typically the dominant cost
        return self.cpu + (self.io * 10.0) + self.memory + (self.network * 5.0)

    def __add__(self, other: Cost) -> Cost:
        return Cost(
            cpu=self.cpu + other.cpu,
            io=self.io + other.io,
            memory=self.memory + other.memory,
            network=self.network + other.network,
        )

    def __mul__(self, factor: float) -> Cost:
        return Cost(
            cpu=self.cpu * factor,
            io=self.io * factor,
            memory=self.memory * factor,
            network=self.network * factor,
        )

    def __lt__(self, other: Cost) -> bool:
        return self.total < other.total

    def __le__(self, other: Cost) -> bool:
        return self.total <= other.total

    def __repr__(self) -> str:
        return f"Cost(cpu={self.cpu:.2f}, io={self.io:.2f}, total={self.total:.2f})"


class CostModel(ABC):
    """Abstract base class for cost models."""

    @abstractmethod
    def estimate_cost(
        self,
        expression: GroupExpression,
        child_costs: list[Cost],
        statistics: Statistics,
    ) -> Cost:
        """Estimate the cost of executing an expression.

        Args:
            expression: The expression to cost
            child_costs: Costs of child expressions
            statistics: Statistics about input data

        Returns:
            Estimated cost
        """
        pass

    @abstractmethod
    def estimate_cardinality(self, expression: GroupExpression, input_stats: Statistics) -> float:
        """Estimate the output cardinality of an expression.

        Args:
            expression: The expression to analyze
            input_stats: Statistics about input data

        Returns:
            Estimated number of output rows
        """
        pass


class DefaultCostModel(CostModel):
    """Default cost model with reasonable estimates.

    This model uses simple heuristics for cost estimation. A more
    sophisticated model would use actual statistics from the database.
    """

    # Cost factors (can be tuned)
    SCAN_COST_PER_ROW = 0.01
    INDEX_SCAN_COST_PER_ROW = 0.001
    INDEX_SEEK_COST = 1.0
    FILTER_COST_PER_ROW = 0.001
    SORT_COST_PER_ROW = 0.1  # N log N amortized
    MERGE_COST_PER_ROW = 0.01
    NETWORK_COST_PER_ROW = 0.01

    def __init__(self, metadata: RecordMetaData | None = None) -> None:
        self._metadata = metadata
        self._stats_cache: dict[str, Statistics] = {}

    def get_statistics(self, record_type: str) -> Statistics:
        """Get statistics for a record type."""
        if record_type in self._stats_cache:
            return self._stats_cache[record_type]

        # Default statistics
        stats = Statistics(row_count=1000.0, avg_row_size=100.0)

        # If we have metadata, we could derive some stats from index info
        if self._metadata and record_type in self._metadata.record_types:
            # Could inspect primary key, indexes, etc.
            pass

        self._stats_cache[record_type] = stats
        return stats

    def estimate_cost(
        self,
        expression: GroupExpression,
        child_costs: list[Cost],
        statistics: Statistics,
    ) -> Cost:
        """Estimate cost based on expression type."""
        from fdb_record_layer.planner.cascades.expressions import (
            PhysicalFilter,
            PhysicalIndexScan,
            PhysicalIntersection,
            PhysicalScan,
            PhysicalSort,
            PhysicalUnion,
        )

        expr = expression.expression

        if isinstance(expr, PhysicalScan):
            return self._cost_scan(expr, statistics)
        elif isinstance(expr, PhysicalIndexScan):
            return self._cost_index_scan(expr, statistics)
        elif isinstance(expr, PhysicalFilter):
            return self._cost_filter(expr, child_costs, statistics)
        elif isinstance(expr, PhysicalSort):
            return self._cost_sort(expr, child_costs, statistics)
        elif isinstance(expr, PhysicalUnion):
            return self._cost_union(expr, child_costs, statistics)
        elif isinstance(expr, PhysicalIntersection):
            return self._cost_intersection(expr, child_costs, statistics)
        else:
            # Unknown expression - use child costs as base
            return sum(child_costs, Cost())

    def _cost_scan(self, expr: Any, stats: Statistics) -> Cost:
        """Cost of a full table scan."""
        rows = stats.row_count

        return Cost(
            cpu=rows * self.SCAN_COST_PER_ROW,
            io=rows * (stats.avg_row_size / 1000.0),  # IO proportional to data size
        )

    def _cost_index_scan(self, expr: Any, stats: Statistics) -> Cost:
        """Cost of an index scan."""
        # Start with seek cost
        cost = Cost(io=self.INDEX_SEEK_COST)

        # Estimate rows returned based on selectivity
        selectivity = self._estimate_index_selectivity(expr, stats)
        rows = stats.row_count * selectivity

        # Index scans are cheaper per row than full scans
        cost.cpu = rows * self.INDEX_SCAN_COST_PER_ROW
        cost.io += rows * 0.01  # Smaller IO per row for index access

        # Reverse scans are slightly more expensive
        if getattr(expr, "reverse", False):
            cost.cpu *= 1.1

        return cost

    def _cost_filter(self, expr: Any, child_costs: list[Cost], stats: Statistics) -> Cost:
        """Cost of applying a filter."""
        base_cost = child_costs[0] if child_costs else Cost()

        # Filter adds CPU cost for each input row
        input_rows = stats.row_count
        filter_cost = Cost(cpu=input_rows * self.FILTER_COST_PER_ROW)

        return base_cost + filter_cost

    def _cost_sort(self, expr: Any, child_costs: list[Cost], stats: Statistics) -> Cost:
        """Cost of sorting."""
        base_cost = child_costs[0] if child_costs else Cost()

        rows = stats.row_count
        # Sort is O(N log N)
        import math

        sort_factor = math.log2(max(rows, 2))

        sort_cost = Cost(
            cpu=rows * self.SORT_COST_PER_ROW * sort_factor,
            memory=rows * stats.avg_row_size / 1000.0,  # Need memory buffer
        )

        return base_cost + sort_cost

    def _cost_union(self, expr: Any, child_costs: list[Cost], stats: Statistics) -> Cost:
        """Cost of union operation."""
        # Sum of child costs plus merge overhead
        base_cost = sum(child_costs, Cost())

        # Simple append union - just concatenate
        union_cost = Cost(cpu=stats.row_count * self.MERGE_COST_PER_ROW)

        return base_cost + union_cost

    def _cost_intersection(self, expr: Any, child_costs: list[Cost], stats: Statistics) -> Cost:
        """Cost of intersection operation."""
        base_cost = sum(child_costs, Cost())

        # Merge intersection - need to compare and merge
        intersection_cost = Cost(
            cpu=stats.row_count * self.MERGE_COST_PER_ROW * 2,
            memory=stats.row_count * 0.01,  # Hash table for one side
        )

        return base_cost + intersection_cost

    def _estimate_index_selectivity(self, expr: Any, stats: Statistics) -> float:
        """Estimate selectivity of an index scan predicate."""
        scan_predicates = getattr(expr, "scan_predicates", None)

        if scan_predicates is None:
            return 1.0

        # Try to extract field and predicate type
        return self._predicate_selectivity(scan_predicates, stats)

    def _predicate_selectivity(self, predicate: Any, stats: Statistics) -> float:
        """Estimate selectivity of a predicate."""
        from fdb_record_layer.query.components import (
            AndComponent,
            FieldComponent,
            NotComponent,
            OrComponent,
        )

        if predicate is None:
            return 1.0

        if isinstance(predicate, FieldComponent):
            pred_type = predicate.comparison.comparison_type.name
            return stats.selectivity(predicate.field_name, pred_type)

        elif isinstance(predicate, AndComponent):
            # AND: multiply selectivities (assuming independence)
            selectivity = 1.0
            for child in predicate.children:
                selectivity *= self._predicate_selectivity(child, stats)
            return selectivity

        elif isinstance(predicate, OrComponent):
            # OR: 1 - product of (1 - selectivity) for each child
            product = 1.0
            for child in predicate.children:
                product *= 1.0 - self._predicate_selectivity(child, stats)
            return 1.0 - product

        elif isinstance(predicate, NotComponent):
            return 1.0 - self._predicate_selectivity(predicate.child, stats)

        else:
            # Unknown predicate - default selectivity
            return 0.5

    def estimate_cardinality(self, expression: GroupExpression, input_stats: Statistics) -> float:
        """Estimate output cardinality."""
        from fdb_record_layer.planner.cascades.expressions import (
            PhysicalFilter,
            PhysicalIndexScan,
            PhysicalIntersection,
            PhysicalScan,
            PhysicalSort,
            PhysicalUnion,
        )

        expr = expression.expression

        if isinstance(expr, PhysicalScan):
            # Full scan returns all rows
            return input_stats.row_count

        elif isinstance(expr, PhysicalIndexScan):
            # Index scan selectivity
            selectivity = self._estimate_index_selectivity(expr, input_stats)
            return input_stats.row_count * selectivity

        elif isinstance(expr, PhysicalFilter):
            # Apply filter selectivity
            selectivity = self._predicate_selectivity(expr.predicate, input_stats)
            # Get input cardinality from child group
            if expression.child_groups:
                input_card = input_stats.row_count
            else:
                input_card = input_stats.row_count
            return input_card * selectivity

        elif isinstance(expr, PhysicalSort):
            # Sort doesn't change cardinality
            return input_stats.row_count

        elif isinstance(expr, PhysicalUnion):
            # Union adds cardinalities
            return input_stats.row_count * len(expr.inputs)

        elif isinstance(expr, PhysicalIntersection):
            # Intersection: estimate as min of inputs times selectivity
            return input_stats.row_count * 0.1  # Conservative estimate

        else:
            return input_stats.row_count


@dataclass
class CostEstimate:
    """Full cost estimate for a plan."""

    cost: Cost
    cardinality: float
    statistics: Statistics

    @property
    def total_cost(self) -> float:
        return self.cost.total

    def __lt__(self, other: CostEstimate) -> bool:
        return self.cost < other.cost

    def __repr__(self) -> str:
        return f"CostEstimate(cost={self.cost.total:.2f}, rows={self.cardinality:.0f})"
