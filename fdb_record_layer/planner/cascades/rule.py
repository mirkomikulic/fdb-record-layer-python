"""Cascades optimization rules.

Rules are the core transformation mechanism in the Cascades optimizer.
There are two types:
- TransformationRules: Rewrite logical expressions to equivalent logical forms
- ImplementationRules: Convert logical expressions to physical plans
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import Iterator
from dataclasses import dataclass
from enum import Enum, auto
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from fdb_record_layer.metadata.record_metadata import RecordMetaData
    from fdb_record_layer.planner.cascades.expressions import RelationalExpression
    from fdb_record_layer.planner.cascades.memo import GroupExpression, Memo, MemoGroup


class RuleType(Enum):
    """Type of optimization rule."""

    TRANSFORMATION = auto()  # Logical -> Logical
    IMPLEMENTATION = auto()  # Logical -> Physical


@dataclass
class RuleMatch:
    """Result of matching a rule to an expression."""

    expression: GroupExpression
    bindings: dict  # Captured sub-expressions and values


class CascadesRule(ABC):
    """Base class for all Cascades optimization rules.

    A rule matches a pattern of expressions and produces alternative
    expressions. Rules are applied during exploration and implementation.
    """

    def __init__(self, name: str | None = None) -> None:
        self._name = name or self.__class__.__name__

    @property
    def name(self) -> str:
        """Name of this rule for debugging."""
        return self._name

    @property
    @abstractmethod
    def rule_type(self) -> RuleType:
        """Type of rule (transformation or implementation)."""
        pass

    @abstractmethod
    def pattern(self) -> type[RelationalExpression]:
        """The expression type this rule matches."""
        pass

    def matches(self, expr: GroupExpression, context: RuleContext) -> bool:
        """Check if this rule matches the given expression.

        Default implementation checks expression type. Override for
        more specific matching conditions.
        """
        return isinstance(expr.expression, self.pattern())

    @abstractmethod
    def apply(self, match: RuleMatch, context: RuleContext) -> Iterator[RelationalExpression]:
        """Apply the rule to produce alternative expressions.

        Args:
            match: The matched expression and bindings
            context: Rule application context

        Yields:
            Alternative expressions to add to the group
        """
        pass

    def __repr__(self) -> str:
        return f"{self.rule_type.name}Rule({self.name})"


@dataclass
class RuleContext:
    """Context for rule application."""

    memo: Memo
    metadata: RecordMetaData
    group: MemoGroup

    # Optional constraints on the search
    required_properties: Any | None = None
    cost_limit: float | None = None


class TransformationRule(CascadesRule):
    """Rule that transforms logical expressions to equivalent logical forms."""

    @property
    def rule_type(self) -> RuleType:
        return RuleType.TRANSFORMATION


class ImplementationRule(CascadesRule):
    """Rule that converts logical expressions to physical plans."""

    @property
    def rule_type(self) -> RuleType:
        return RuleType.IMPLEMENTATION


# ============================================================================
# Transformation Rules
# ============================================================================


class PushFilterThroughProjectRule(TransformationRule):
    """Push a filter below a projection when possible.

    Filter(Project(X, cols), pred) -> Project(Filter(X, pred), cols)

    This is valid when the filter predicate only references columns
    that are in the projection.
    """

    def pattern(self) -> type[RelationalExpression]:
        from fdb_record_layer.planner.cascades.expressions import LogicalFilter

        return LogicalFilter

    def matches(self, expr: GroupExpression, context: RuleContext) -> bool:
        from fdb_record_layer.planner.cascades.expressions import (
            LogicalFilter,
            LogicalProject,
        )

        if not isinstance(expr.expression, LogicalFilter):
            return False

        # Check if input is a projection
        if expr.child_groups:
            for child_expr in expr.child_groups[0].get_logical_expressions():
                if isinstance(child_expr.expression, LogicalProject):
                    return True
        return False

    def apply(self, match: RuleMatch, context: RuleContext) -> Iterator[RelationalExpression]:
        from fdb_record_layer.planner.cascades.expressions import (
            LogicalFilter,
            LogicalProject,
        )

        filter_expr = match.expression.expression
        assert isinstance(filter_expr, LogicalFilter)

        # Get the project child
        for child_expr in match.expression.child_groups[0].get_logical_expressions():
            if isinstance(child_expr.expression, LogicalProject):
                project = child_expr.expression

                # Create: Project(Filter(project.input, pred), project.fields)
                new_filter = LogicalFilter(
                    predicate=filter_expr.predicate, input_expr=project.input_expr
                )
                new_project = LogicalProject(fields=project.fields, input_expr=new_filter)

                yield new_project
                break


class FilterMergeRule(TransformationRule):
    """Merge adjacent filters into a single filter.

    Filter(Filter(X, pred1), pred2) -> Filter(X, AND(pred1, pred2))
    """

    def pattern(self) -> type[RelationalExpression]:
        from fdb_record_layer.planner.cascades.expressions import LogicalFilter

        return LogicalFilter

    def matches(self, expr: GroupExpression, context: RuleContext) -> bool:
        from fdb_record_layer.planner.cascades.expressions import LogicalFilter

        if not isinstance(expr.expression, LogicalFilter):
            return False

        # Check if input is also a filter
        if expr.child_groups:
            for child_expr in expr.child_groups[0].get_logical_expressions():
                if isinstance(child_expr.expression, LogicalFilter):
                    return True
        return False

    def apply(self, match: RuleMatch, context: RuleContext) -> Iterator[RelationalExpression]:
        from fdb_record_layer.planner.cascades.expressions import LogicalFilter
        from fdb_record_layer.query.components import AndComponent

        outer_filter = match.expression.expression
        assert isinstance(outer_filter, LogicalFilter)

        for child_expr in match.expression.child_groups[0].get_logical_expressions():
            if isinstance(child_expr.expression, LogicalFilter):
                inner_filter = child_expr.expression

                # Combine predicates with AND
                combined = AndComponent([outer_filter.predicate, inner_filter.predicate])

                # Create merged filter
                merged = LogicalFilter(predicate=combined, input_expr=inner_filter.input_expr)
                yield merged
                break


class PredicatePushDownRule(TransformationRule):
    """Push filter predicates down toward data sources.

    Filter(Union(A, B), pred) -> Union(Filter(A, pred), Filter(B, pred))
    """

    def pattern(self) -> type[RelationalExpression]:
        from fdb_record_layer.planner.cascades.expressions import LogicalFilter

        return LogicalFilter

    def matches(self, expr: GroupExpression, context: RuleContext) -> bool:
        from fdb_record_layer.planner.cascades.expressions import (
            LogicalFilter,
            LogicalUnion,
        )

        if not isinstance(expr.expression, LogicalFilter):
            return False

        # Check if input is a union
        if expr.child_groups:
            for child_expr in expr.child_groups[0].get_logical_expressions():
                if isinstance(child_expr.expression, LogicalUnion):
                    return True
        return False

    def apply(self, match: RuleMatch, context: RuleContext) -> Iterator[RelationalExpression]:
        from fdb_record_layer.planner.cascades.expressions import (
            LogicalFilter,
            LogicalUnion,
        )

        filter_expr = match.expression.expression
        assert isinstance(filter_expr, LogicalFilter)

        for child_expr in match.expression.child_groups[0].get_logical_expressions():
            if isinstance(child_expr.expression, LogicalUnion):
                union = child_expr.expression

                # Push filter to each union input
                new_inputs = tuple(
                    LogicalFilter(predicate=filter_expr.predicate, input_expr=inp)
                    for inp in union.inputs
                )

                yield LogicalUnion(inputs=new_inputs)
                break


# ============================================================================
# Implementation Rules
# ============================================================================


class ImplementScanRule(ImplementationRule):
    """Implement logical scan as physical table scan."""

    def pattern(self) -> type[RelationalExpression]:
        from fdb_record_layer.planner.cascades.expressions import LogicalScan

        return LogicalScan

    def apply(self, match: RuleMatch, context: RuleContext) -> Iterator[RelationalExpression]:
        from fdb_record_layer.planner.cascades.expressions import (
            LogicalScan,
            PhysicalScan,
        )

        logical = match.expression.expression
        assert isinstance(logical, LogicalScan)

        yield PhysicalScan(record_types=logical.record_types)


class ImplementIndexScanRule(ImplementationRule):
    """Implement logical index scan as physical index scan."""

    def pattern(self) -> type[RelationalExpression]:
        from fdb_record_layer.planner.cascades.expressions import LogicalIndexScan

        return LogicalIndexScan

    def apply(self, match: RuleMatch, context: RuleContext) -> Iterator[RelationalExpression]:
        from fdb_record_layer.planner.cascades.expressions import (
            LogicalIndexScan,
            PhysicalIndexScan,
        )

        logical = match.expression.expression
        assert isinstance(logical, LogicalIndexScan)

        # Generate both forward and reverse scans
        yield PhysicalIndexScan(
            index_name=logical.index_name,
            scan_predicates=logical.scan_predicates,
            reverse=False,
        )

        # Only generate reverse if ordering might benefit
        yield PhysicalIndexScan(
            index_name=logical.index_name,
            scan_predicates=logical.scan_predicates,
            reverse=True,
        )


class ImplementFilterRule(ImplementationRule):
    """Implement logical filter as physical filter."""

    def pattern(self) -> type[RelationalExpression]:
        from fdb_record_layer.planner.cascades.expressions import LogicalFilter

        return LogicalFilter

    def apply(self, match: RuleMatch, context: RuleContext) -> Iterator[RelationalExpression]:
        from fdb_record_layer.planner.cascades.expressions import (
            LogicalFilter,
            PhysicalFilter,
        )

        logical = match.expression.expression
        assert isinstance(logical, LogicalFilter)

        yield PhysicalFilter(
            predicate=logical.predicate,
            input_expr=logical.input_expr,  # Will be resolved from child group
        )


class ImplementSortRule(ImplementationRule):
    """Implement logical sort as physical sort."""

    def pattern(self) -> type[RelationalExpression]:
        from fdb_record_layer.planner.cascades.expressions import LogicalSort

        return LogicalSort

    def apply(self, match: RuleMatch, context: RuleContext) -> Iterator[RelationalExpression]:
        from fdb_record_layer.planner.cascades.expressions import LogicalSort, PhysicalSort

        logical = match.expression.expression
        assert isinstance(logical, LogicalSort)

        yield PhysicalSort(sort_fields=logical.sort_fields, input_expr=logical.input_expr)


class ImplementUnionRule(ImplementationRule):
    """Implement logical union as physical union."""

    def pattern(self) -> type[RelationalExpression]:
        from fdb_record_layer.planner.cascades.expressions import LogicalUnion

        return LogicalUnion

    def apply(self, match: RuleMatch, context: RuleContext) -> Iterator[RelationalExpression]:
        from fdb_record_layer.planner.cascades.expressions import (
            LogicalUnion,
            PhysicalUnion,
        )

        logical = match.expression.expression
        assert isinstance(logical, LogicalUnion)

        yield PhysicalUnion(inputs=logical.inputs)


class ImplementIntersectionRule(ImplementationRule):
    """Implement logical intersection as physical intersection."""

    def pattern(self) -> type[RelationalExpression]:
        from fdb_record_layer.planner.cascades.expressions import LogicalIntersection

        return LogicalIntersection

    def apply(self, match: RuleMatch, context: RuleContext) -> Iterator[RelationalExpression]:
        from fdb_record_layer.planner.cascades.expressions import (
            LogicalIntersection,
            PhysicalIntersection,
        )

        logical = match.expression.expression
        assert isinstance(logical, LogicalIntersection)

        yield PhysicalIntersection(inputs=logical.inputs)


class IndexSelectionRule(ImplementationRule):
    """Convert a scan + filter to index scan when applicable.

    This is a key optimization rule that identifies when a filter can
    be pushed into an index scan.

    Filter(Scan(types), pred) -> IndexScan(index, pred_scan) + Filter(pred_residual)
    """

    def pattern(self) -> type[RelationalExpression]:
        from fdb_record_layer.planner.cascades.expressions import LogicalFilter

        return LogicalFilter

    def matches(self, expr: GroupExpression, context: RuleContext) -> bool:
        from fdb_record_layer.planner.cascades.expressions import (
            LogicalFilter,
            LogicalScan,
        )

        if not isinstance(expr.expression, LogicalFilter):
            return False

        # Check if input is a scan
        if expr.child_groups:
            for child_expr in expr.child_groups[0].get_logical_expressions():
                if isinstance(child_expr.expression, LogicalScan):
                    return True
        return False

    def apply(self, match: RuleMatch, context: RuleContext) -> Iterator[RelationalExpression]:
        from fdb_record_layer.planner.cascades.expressions import (
            LogicalFilter,
            LogicalScan,
            PhysicalFilter,
            PhysicalIndexScan,
        )

        filter_expr = match.expression.expression
        assert isinstance(filter_expr, LogicalFilter)

        # Get the scan child
        scan_expr = None
        for child_expr in match.expression.child_groups[0].get_logical_expressions():
            if isinstance(child_expr.expression, LogicalScan):
                scan_expr = child_expr.expression
                break

        if scan_expr is None:
            return

        # Find applicable indexes
        applicable_indexes = self._find_applicable_indexes(
            filter_expr.predicate, scan_expr.record_types, context.metadata
        )

        for index_name, scan_pred, residual_pred in applicable_indexes:
            # Create index scan
            index_scan = PhysicalIndexScan(
                index_name=index_name, scan_predicates=scan_pred, reverse=False
            )

            if residual_pred:
                # Need a residual filter
                yield PhysicalFilter(predicate=residual_pred, input_expr=index_scan)
            else:
                # Index covers the whole predicate
                yield index_scan

    def _find_applicable_indexes(
        self,
        predicate: Any,
        record_types: tuple[str, ...],
        metadata: RecordMetaData,
    ) -> list[tuple[str, Any, Any]]:
        """Find indexes that can satisfy (part of) the predicate.

        Returns:
            List of (index_name, scan_predicate, residual_predicate) tuples
        """
        from fdb_record_layer.metadata.index import IndexType

        results = []

        # Get all applicable indexes for these record types
        for index_name, index in metadata.indexes.items():
            if index.index_type != IndexType.VALUE:
                continue

            # Check if index applies to any of our record types
            if index.record_types is not None:
                if not any(rt in index.record_types for rt in record_types):
                    continue

            # Check if predicate uses the indexed field
            indexed_field = self._get_indexed_field(index)
            if indexed_field is None:
                continue

            # Try to match predicate to index
            scan_pred, residual = self._split_predicate(predicate, indexed_field)

            if scan_pred is not None:
                results.append((index_name, scan_pred, residual))

        return results

    def _get_indexed_field(self, index) -> str | None:
        """Extract the field name from an index definition."""
        from fdb_record_layer.expressions.field import FieldKeyExpression

        if isinstance(index.root_expression, FieldKeyExpression):
            return index.root_expression.field_name
        return None

    def _split_predicate(self, predicate: Any, indexed_field: str) -> tuple[Any | None, Any | None]:
        """Split predicate into index-scannable and residual parts.

        Returns:
            (scan_predicate, residual_predicate) tuple
        """
        from fdb_record_layer.query.components import (
            AndComponent,
            FieldComponent,
            OrComponent,
        )

        if isinstance(predicate, FieldComponent):
            if predicate.field_name == indexed_field:
                # Fully covered by index
                return predicate, None
            else:
                # Not covered - all residual
                return None, predicate

        elif isinstance(predicate, AndComponent):
            scan_parts = []
            residual_parts = []

            for child in predicate.children:
                scan, residual = self._split_predicate(child, indexed_field)
                if scan:
                    scan_parts.append(scan)
                if residual:
                    residual_parts.append(residual)

            scan_pred = AndComponent(scan_parts) if scan_parts else None
            residual_pred = (
                AndComponent(residual_parts)
                if len(residual_parts) > 1
                else residual_parts[0]
                if residual_parts
                else None
            )

            return scan_pred, residual_pred

        elif isinstance(predicate, OrComponent):
            # OR predicates can only use index if ALL branches match the index
            all_scan = []
            for child in predicate.children:
                scan, residual = self._split_predicate(child, indexed_field)
                if scan is None:
                    # One branch doesn't match - can't use index for OR
                    return None, predicate
                if residual:
                    # One branch has residual - can't fully push to index
                    return None, predicate
                all_scan.append(scan)

            return OrComponent(all_scan), None

        else:
            # Unknown predicate type - all residual
            return None, predicate


# ============================================================================
# Rule Set
# ============================================================================


class RuleSet:
    """Collection of optimization rules."""

    def __init__(self) -> None:
        self._transformation_rules: list[TransformationRule] = []
        self._implementation_rules: list[ImplementationRule] = []

    def add_rule(self, rule: CascadesRule) -> None:
        """Add a rule to the set."""
        if isinstance(rule, TransformationRule):
            self._transformation_rules.append(rule)
        elif isinstance(rule, ImplementationRule):
            self._implementation_rules.append(rule)

    @property
    def transformation_rules(self) -> list[TransformationRule]:
        return self._transformation_rules

    @property
    def implementation_rules(self) -> list[ImplementationRule]:
        return self._implementation_rules

    def get_matching_rules(
        self, expr: GroupExpression, rule_type: RuleType, context: RuleContext
    ) -> Iterator[CascadesRule]:
        """Get all rules that match the given expression."""
        rules = (
            self._transformation_rules
            if rule_type == RuleType.TRANSFORMATION
            else self._implementation_rules
        )

        for rule in rules:
            if rule.matches(expr, context):
                yield rule

    @classmethod
    def default(cls) -> RuleSet:
        """Create the default rule set with all standard rules."""
        rule_set = cls()

        # Transformation rules
        rule_set.add_rule(PushFilterThroughProjectRule())
        rule_set.add_rule(FilterMergeRule())
        rule_set.add_rule(PredicatePushDownRule())

        # Implementation rules
        rule_set.add_rule(ImplementScanRule())
        rule_set.add_rule(ImplementIndexScanRule())
        rule_set.add_rule(ImplementFilterRule())
        rule_set.add_rule(ImplementSortRule())
        rule_set.add_rule(ImplementUnionRule())
        rule_set.add_rule(ImplementIntersectionRule())
        rule_set.add_rule(IndexSelectionRule())

        return rule_set

    def __len__(self) -> int:
        return len(self._transformation_rules) + len(self._implementation_rules)

    def __repr__(self) -> str:
        return (
            f"RuleSet({len(self._transformation_rules)} transform, "
            f"{len(self._implementation_rules)} implement)"
        )
