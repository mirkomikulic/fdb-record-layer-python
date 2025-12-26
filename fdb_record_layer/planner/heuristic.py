"""Heuristic query planner implementation."""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import TYPE_CHECKING, Any, TypeVar

from fdb_record_layer.planner.scan_comparisons import ScanComparisons
from fdb_record_layer.plans.base import RecordQueryPlan
from fdb_record_layer.plans.filter_plan import FilterPlan, RecordTypeFilterPlan
from fdb_record_layer.plans.index_plan import IndexScanPlan
from fdb_record_layer.plans.scan_plan import ScanPlan, TypeScanPlan
from fdb_record_layer.plans.union_plan import UnionPlan
from fdb_record_layer.query.components import (
    AndComponent,
    FieldComponent,
    NestedFieldComponent,
    NotComponent,
    OrComponent,
    QueryComponent,
)

if TYPE_CHECKING:
    from google.protobuf.message import Message

    from fdb_record_layer.metadata.index import Index
    from fdb_record_layer.metadata.record_metadata import RecordMetaData
    from fdb_record_layer.query.query import RecordQuery

M = TypeVar("M", bound="Message")


class RecordQueryPlanner(ABC):
    """Abstract base class for query planners.

    A planner takes a RecordQuery and produces an execution plan.
    """

    @abstractmethod
    def plan(self, query: RecordQuery) -> RecordQueryPlan[Any]:
        """Create an execution plan for a query.

        Args:
            query: The query to plan.

        Returns:
            An execution plan.
        """
        pass

    @abstractmethod
    def explain(self, query: RecordQuery) -> str:
        """Explain the plan that would be generated.

        Args:
            query: The query to explain.

        Returns:
            A human-readable explanation.
        """
        pass


class HeuristicPlanner(RecordQueryPlanner):
    """A rule-based heuristic query planner.

    The heuristic planner uses simple rules to select indexes:
    1. Equality predicates match the start of an index
    2. One inequality predicate can use the next position
    3. OR queries may use union of index scans
    4. Remaining predicates become residual filters

    This is simpler than a cost-based optimizer but handles
    most common cases efficiently.
    """

    def __init__(self, meta_data: RecordMetaData) -> None:
        """Initialize the planner.

        Args:
            meta_data: The record metadata.
        """
        self._meta_data = meta_data

    def plan(self, query: RecordQuery) -> RecordQueryPlan[Any]:
        """Create an execution plan for the query.

        Args:
            query: The query to plan.

        Returns:
            The execution plan.
        """
        # Determine record types to query
        record_types = query.record_types
        if not record_types:
            # Query all record types
            record_types = list(self._meta_data.record_types.keys())

        # Get available indexes for these record types
        available_indexes = self._get_indexes_for_types(record_types)

        # Plan the filter
        filter_component = query.filter
        if filter_component is None:
            # No filter - full scan
            if len(record_types) == 1:
                return TypeScanPlan(record_types[0])
            return ScanPlan(record_types)

        # Try to find an index plan
        plan = self._plan_filter(filter_component, available_indexes, record_types)

        # Add record type filter if needed
        if len(record_types) > 0 and len(record_types) < len(self._meta_data.record_types):
            plan = RecordTypeFilterPlan(plan, record_types)

        return plan

    def explain(self, query: RecordQuery) -> str:
        """Explain the plan for a query.

        Args:
            query: The query to explain.

        Returns:
            Plan explanation string.
        """
        plan = self.plan(query)
        return plan.explain()

    def _get_indexes_for_types(self, record_types: list[str]) -> list[Index]:
        """Get indexes applicable to the given record types.

        Args:
            record_types: The record types.

        Returns:
            List of applicable indexes.
        """
        indexes = []
        for record_type in record_types:
            type_indexes = self._meta_data.get_indexes_for_record_type(record_type)
            for idx in type_indexes:
                if idx not in indexes:
                    indexes.append(idx)
        return indexes

    def _plan_filter(
        self,
        filter_component: QueryComponent,
        available_indexes: list[Index],
        record_types: list[str],
    ) -> RecordQueryPlan[Any]:
        """Plan a filter component.

        Args:
            filter_component: The filter to plan.
            available_indexes: Available indexes.
            record_types: Record types being queried.

        Returns:
            An execution plan.
        """
        # Handle different component types
        if isinstance(filter_component, AndComponent):
            return self._plan_and(filter_component, available_indexes, record_types)
        elif isinstance(filter_component, OrComponent):
            return self._plan_or(filter_component, available_indexes, record_types)
        elif isinstance(filter_component, NotComponent):
            return self._plan_not(filter_component, available_indexes, record_types)
        elif isinstance(filter_component, FieldComponent):
            return self._plan_field(filter_component, available_indexes, record_types)
        elif isinstance(filter_component, NestedFieldComponent):
            return self._plan_nested(filter_component, available_indexes, record_types)
        else:
            # Unknown component type - fall back to scan with filter
            base_plan = self._make_scan_plan(record_types)
            return FilterPlan(base_plan, filter_component)

    def _plan_and(
        self,
        component: AndComponent,
        available_indexes: list[Index],
        record_types: list[str],
    ) -> RecordQueryPlan[Any]:
        """Plan an AND component.

        Try to use an index for equality/range predicates.

        Args:
            component: The AND component.
            available_indexes: Available indexes.
            record_types: Record types.

        Returns:
            An execution plan.
        """
        # Collect field predicates
        field_predicates: list[FieldComponent] = []
        other_predicates: list[QueryComponent] = []

        for child in component.children:
            if isinstance(child, FieldComponent):
                field_predicates.append(child)
            else:
                other_predicates.append(child)

        # Try to find best index
        best_index, best_comparisons, residual_predicates = self._match_index(
            field_predicates, available_indexes
        )

        if best_index is not None:
            # Use index scan
            plan: RecordQueryPlan[Any] = IndexScanPlan(best_index.name, best_comparisons)

            # Add residual filter if needed
            all_residual = residual_predicates + other_predicates
            if all_residual:
                residual_component = self._combine_predicates(all_residual)
                plan = FilterPlan(plan, residual_component)

            return plan

        # No index found - use scan with filter
        base_plan = self._make_scan_plan(record_types)
        return FilterPlan(base_plan, component)

    def _plan_or(
        self,
        component: OrComponent,
        available_indexes: list[Index],
        record_types: list[str],
    ) -> RecordQueryPlan[Any]:
        """Plan an OR component.

        May use union of index scans if each branch can use an index.

        Args:
            component: The OR component.
            available_indexes: Available indexes.
            record_types: Record types.

        Returns:
            An execution plan.
        """
        # Try to plan each branch
        child_plans: list[RecordQueryPlan[Any]] = []
        can_use_union = True

        for child in component.children:
            child_plan = self._plan_filter(child, available_indexes, record_types)
            child_plans.append(child_plan)

            # Check if this branch uses a full scan
            if child_plan.has_full_scan():
                # One branch needs full scan, union doesn't help
                can_use_union = False

        if can_use_union and len(child_plans) > 1:
            return UnionPlan(child_plans)

        # Fall back to scan with filter
        base_plan = self._make_scan_plan(record_types)
        return FilterPlan(base_plan, component)

    def _plan_not(
        self,
        component: NotComponent,
        available_indexes: list[Index],
        record_types: list[str],
    ) -> RecordQueryPlan[Any]:
        """Plan a NOT component.

        NOT predicates generally can't use indexes efficiently.

        Args:
            component: The NOT component.
            available_indexes: Available indexes.
            record_types: Record types.

        Returns:
            An execution plan.
        """
        # NOT predicates typically need full scan with filter
        base_plan = self._make_scan_plan(record_types)
        return FilterPlan(base_plan, component)

    def _plan_field(
        self,
        component: FieldComponent,
        available_indexes: list[Index],
        record_types: list[str],
    ) -> RecordQueryPlan[Any]:
        """Plan a single field predicate.

        Args:
            component: The field component.
            available_indexes: Available indexes.
            record_types: Record types.

        Returns:
            An execution plan.
        """
        # Try to find an index starting with this field
        for index in available_indexes:
            # Get index fields
            index_fields = self._get_index_fields(index)
            if index_fields and index_fields[0] == component.field_name:
                # This index can be used
                comparison = component.comparison
                scan_comparisons = ScanComparisons.from_comparison(comparison)
                return IndexScanPlan(index.name, scan_comparisons)

        # No suitable index - scan with filter
        base_plan = self._make_scan_plan(record_types)
        return FilterPlan(base_plan, component)

    def _plan_nested(
        self,
        component: NestedFieldComponent,
        available_indexes: list[Index],
        record_types: list[str],
    ) -> RecordQueryPlan[Any]:
        """Plan a nested field predicate.

        Args:
            component: The nested field component.
            available_indexes: Available indexes.
            record_types: Record types.

        Returns:
            An execution plan.
        """
        # Nested fields require scan with filter for now
        # TODO: Support nested indexes
        base_plan = self._make_scan_plan(record_types)
        return FilterPlan(base_plan, component)

    def _match_index(
        self,
        predicates: list[FieldComponent],
        available_indexes: list[Index],
    ) -> tuple[Index | None, ScanComparisons, list[FieldComponent]]:
        """Find the best index for a set of predicates.

        Args:
            predicates: Field predicates to match.
            available_indexes: Available indexes.

        Returns:
            Tuple of (best index, scan comparisons, residual predicates).
        """
        best_index: Index | None = None
        best_comparisons = ScanComparisons()
        best_residual = list(predicates)
        best_score = 0

        # Build a map of field -> predicates
        field_predicates: dict[str, list[FieldComponent]] = {}
        for pred in predicates:
            if pred.field_name not in field_predicates:
                field_predicates[pred.field_name] = []
            field_predicates[pred.field_name].append(pred)

        # Try each index
        for index in available_indexes:
            index_fields = self._get_index_fields(index)
            if not index_fields:
                continue

            # Try to match predicates to index fields in order
            comparisons = ScanComparisons()
            matched_predicates: list[FieldComponent] = []
            score = 0

            for i, field_name in enumerate(index_fields):
                if field_name not in field_predicates:
                    # No predicate for this field - stop matching
                    break

                field_preds = field_predicates[field_name]

                # Look for equality predicate first
                equality_pred = None
                inequality_pred = None

                for pred in field_preds:
                    comp_type = pred.comparison.comparison_type
                    if comp_type.is_equality:
                        equality_pred = pred
                        break
                    elif comp_type.is_inequality:
                        inequality_pred = pred

                if equality_pred is not None:
                    # Add equality comparison
                    comparisons = comparisons.add_equality(equality_pred.comparison)
                    matched_predicates.append(equality_pred)
                    score += 10  # Equality is valuable
                elif inequality_pred is not None:
                    # Add inequality comparison (can only have one)
                    comparisons = comparisons.add_inequality(inequality_pred.comparison)
                    matched_predicates.append(inequality_pred)
                    score += 5  # Range is less valuable
                    break  # Can't match more after inequality
                else:
                    break

            if score > best_score:
                best_index = index
                best_comparisons = comparisons
                best_residual = [p for p in predicates if p not in matched_predicates]
                best_score = score

        return best_index, best_comparisons, best_residual

    def _get_index_fields(self, index: Index) -> list[str]:
        """Get the fields covered by an index.

        Args:
            index: The index.

        Returns:
            List of field names.
        """
        # Extract fields from the index's root expression
        from fdb_record_layer.expressions.concat import ConcatenateKeyExpression
        from fdb_record_layer.expressions.field import FieldKeyExpression

        root_expr = index.root_expression
        fields: list[str] = []

        if isinstance(root_expr, FieldKeyExpression):
            fields.append(root_expr.field_name)
        elif isinstance(root_expr, ConcatenateKeyExpression):
            for child in root_expr.children:
                if isinstance(child, FieldKeyExpression):
                    fields.append(child.field_name)

        return fields

    def _make_scan_plan(self, record_types: list[str]) -> RecordQueryPlan[Any]:
        """Create a scan plan for the given types.

        Args:
            record_types: Record types to scan.

        Returns:
            A scan plan.
        """
        if len(record_types) == 1:
            return TypeScanPlan(record_types[0])
        return ScanPlan(record_types)

    def _combine_predicates(self, predicates: list[QueryComponent]) -> QueryComponent:
        """Combine multiple predicates with AND.

        Args:
            predicates: Predicates to combine.

        Returns:
            Combined predicate.
        """
        if len(predicates) == 1:
            return predicates[0]
        return AndComponent(children=predicates)


class IndexMatcher:
    """Helper class for matching predicates to indexes."""

    def __init__(self, index: Index) -> None:
        self._index = index
        self._fields = self._extract_fields()

    def _extract_fields(self) -> list[str]:
        """Extract field names from the index."""
        from fdb_record_layer.expressions.concat import ConcatenateKeyExpression
        from fdb_record_layer.expressions.field import FieldKeyExpression

        root = self._index.root_expression
        fields: list[str] = []

        if isinstance(root, FieldKeyExpression):
            fields.append(root.field_name)
        elif isinstance(root, ConcatenateKeyExpression):
            for child in root.children:
                if isinstance(child, FieldKeyExpression):
                    fields.append(child.field_name)

        return fields

    def get_fields(self) -> list[str]:
        """Get the index fields."""
        return self._fields

    def can_satisfy(self, field_name: str, position: int = 0) -> bool:
        """Check if the index can satisfy a predicate at a position.

        Args:
            field_name: The field name.
            position: The position in the index.

        Returns:
            True if the index can satisfy the predicate.
        """
        if position >= len(self._fields):
            return False
        return self._fields[position] == field_name
