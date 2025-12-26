"""Memo structure for Cascades optimizer.

The Memo is the central data structure in the Cascades optimizer that stores
expressions and their equivalences for memoization and optimization.
"""

from __future__ import annotations

from collections.abc import Iterator
from dataclasses import dataclass, field
from enum import Enum, auto
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from fdb_record_layer.planner.cascades.expressions import (
        ExpressionProperty,
        RelationalExpression,
    )


class GroupState(Enum):
    """State of a memo group during optimization."""

    UNEXPLORED = auto()  # Not yet explored
    EXPLORING = auto()  # Currently being explored
    EXPLORED = auto()  # Exploration complete
    OPTIMIZING = auto()  # Cost optimization in progress
    OPTIMIZED = auto()  # Optimization complete


@dataclass
class Winner:
    """Represents the winning (best) plan for a group with given properties."""

    expression: GroupExpression
    cost: float
    physical_properties: Any | None = None  # Required physical properties

    def __repr__(self) -> str:
        return f"Winner(expr={self.expression.expr_id}, cost={self.cost:.4f})"


@dataclass
class GroupExpression:
    """A single expression in a memo group.

    A GroupExpression wraps a RelationalExpression and tracks its membership
    in a group. Child expressions are represented as references to other groups.
    """

    expression: RelationalExpression
    group: MemoGroup
    expr_id: int
    child_groups: tuple[MemoGroup, ...] = field(default_factory=tuple)

    # Optimization state
    explored: bool = False
    cost: float | None = None
    derived_properties: ExpressionProperty | None = None

    def __hash__(self) -> int:
        return self.expr_id

    def __eq__(self, other: object) -> bool:
        if not isinstance(other, GroupExpression):
            return NotImplemented
        return self.expr_id == other.expr_id

    def __repr__(self) -> str:
        expr_type = type(self.expression).__name__
        return f"GE({self.expr_id}: {expr_type} -> G{self.group.group_id})"


@dataclass
class MemoGroup:
    """A group of logically equivalent expressions.

    All expressions in a group produce the same logical result, though they
    may have different physical implementations and costs.
    """

    group_id: int
    expressions: list[GroupExpression] = field(default_factory=list)
    state: GroupState = GroupState.UNEXPLORED

    # Logical properties shared by all expressions in group
    logical_properties: ExpressionProperty | None = None

    # Best plan found for different physical property requirements
    winners: dict[tuple, Winner] = field(default_factory=dict)

    # For tracking exploration
    explored_rules: set[str] = field(default_factory=set)

    def add_expression(self, group_expr: GroupExpression) -> None:
        """Add an expression to this group."""
        self.expressions.append(group_expr)

    def get_logical_expressions(self) -> Iterator[GroupExpression]:
        """Get all logical expressions in this group."""
        from fdb_record_layer.planner.cascades.expressions import ExpressionKind

        for expr in self.expressions:
            if expr.expression.kind == ExpressionKind.LOGICAL:
                yield expr

    def get_physical_expressions(self) -> Iterator[GroupExpression]:
        """Get all physical expressions in this group."""
        from fdb_record_layer.planner.cascades.expressions import ExpressionKind

        for expr in self.expressions:
            if expr.expression.kind == ExpressionKind.PHYSICAL:
                yield expr

    def get_winner(self, physical_properties: tuple | None = None) -> Winner | None:
        """Get the winning plan for given physical properties."""
        key = physical_properties or ()
        return self.winners.get(key)

    def set_winner(
        self,
        expression: GroupExpression,
        cost: float,
        physical_properties: tuple | None = None,
    ) -> None:
        """Set the winning plan for given physical properties."""
        key = physical_properties or ()
        self.winners[key] = Winner(expression, cost, physical_properties)

    def __hash__(self) -> int:
        return self.group_id

    def __eq__(self, other: object) -> bool:
        if not isinstance(other, MemoGroup):
            return NotImplemented
        return self.group_id == other.group_id

    def __repr__(self) -> str:
        return f"Group({self.group_id}, {len(self.expressions)} exprs, {self.state.name})"


class ExpressionRef:
    """Reference to a memo group.

    Used to represent child expressions in the memo structure. Each ref points
    to a group, allowing expressions to share equivalent subexpressions.
    """

    def __init__(self, group: MemoGroup) -> None:
        self._group = group

    @property
    def group(self) -> MemoGroup:
        return self._group

    @property
    def group_id(self) -> int:
        return self._group.group_id

    def get_expressions(self) -> Iterator[GroupExpression]:
        """Get all expressions in the referenced group."""
        return iter(self._group.expressions)

    def get_best(self, physical_properties: tuple | None = None) -> Winner | None:
        """Get the best plan from the referenced group."""
        return self._group.get_winner(physical_properties)

    def __repr__(self) -> str:
        return f"Ref(G{self.group_id})"


class Memo:
    """Central memoization structure for Cascades optimizer.

    The Memo stores all expressions organized into equivalence groups.
    It provides:
    - Deduplication of equivalent expressions
    - Grouping of logically equivalent alternatives
    - Tracking of optimization state
    - Winner (best plan) tracking per group
    """

    def __init__(self) -> None:
        self._groups: list[MemoGroup] = []
        self._expression_to_group: dict[int, MemoGroup] = {}  # expr hash -> group
        self._next_group_id = 0
        self._next_expr_id = 0

        # Expression fingerprinting for deduplication
        self._fingerprints: dict[tuple, MemoGroup] = {}

    @property
    def groups(self) -> list[MemoGroup]:
        """Get all groups in the memo."""
        return self._groups

    @property
    def num_groups(self) -> int:
        """Get the number of groups."""
        return len(self._groups)

    @property
    def num_expressions(self) -> int:
        """Get the total number of expressions."""
        return sum(len(g.expressions) for g in self._groups)

    def create_group(self, expression: RelationalExpression) -> MemoGroup:
        """Create a new group with the given expression as its first member."""
        group = MemoGroup(group_id=self._next_group_id)
        self._next_group_id += 1
        self._groups.append(group)

        # Add the expression to the new group
        self._add_expression_to_group(expression, group)

        # Add fingerprint for deduplication
        fingerprint = self._compute_fingerprint(expression)
        self._fingerprints[fingerprint] = group

        return group

    def get_or_create_group(self, expression: RelationalExpression) -> tuple[MemoGroup, bool]:
        """Get existing group for expression or create a new one.

        Returns:
            Tuple of (group, was_new) where was_new is True if a new group was created.
        """
        fingerprint = self._compute_fingerprint(expression)

        if fingerprint in self._fingerprints:
            return self._fingerprints[fingerprint], False

        group = self.create_group(expression)
        self._fingerprints[fingerprint] = group
        return group, True

    def add_expression(
        self, expression: RelationalExpression, target_group: MemoGroup
    ) -> GroupExpression:
        """Add an expression to an existing group.

        Returns:
            The GroupExpression wrapper for the added expression.
        """
        return self._add_expression_to_group(expression, target_group)

    def _add_expression_to_group(
        self, expression: RelationalExpression, group: MemoGroup
    ) -> GroupExpression:
        """Internal method to add expression to group."""
        # Create child group refs
        child_groups = tuple(self.get_or_create_group(child)[0] for child in expression.children)

        group_expr = GroupExpression(
            expression=expression,
            group=group,
            expr_id=self._next_expr_id,
            child_groups=child_groups,
        )
        self._next_expr_id += 1

        group.add_expression(group_expr)
        self._expression_to_group[group_expr.expr_id] = group

        return group_expr

    def _compute_fingerprint(self, expression: RelationalExpression) -> tuple:
        """Compute a fingerprint for expression deduplication.

        Two expressions with the same fingerprint are considered equivalent
        and should be in the same group.
        """
        expr_type = type(expression).__name__

        # Get child fingerprints recursively
        child_fps = tuple(self._compute_fingerprint(c) for c in expression.children)

        # Get expression-specific attributes for the fingerprint
        expr_attrs = self._get_expression_attrs(expression)

        return (expr_type, expr_attrs, child_fps)

    def _get_expression_attrs(self, expression: RelationalExpression) -> tuple:
        """Extract hashable attributes from an expression for fingerprinting."""
        from fdb_record_layer.planner.cascades.expressions import (
            LogicalFilter,
            LogicalIndexScan,
            LogicalProject,
            LogicalScan,
            LogicalSort,
            PhysicalFilter,
            PhysicalIndexScan,
            PhysicalScan,
            PhysicalSort,
        )

        if isinstance(expression, LogicalScan):
            return ("scan", expression.record_types)
        elif isinstance(expression, LogicalIndexScan):
            return ("idx_scan", expression.index_name, str(expression.scan_predicates))
        elif isinstance(expression, LogicalFilter):
            return ("filter", str(expression.predicate))
        elif isinstance(expression, LogicalProject):
            return ("project", expression.fields)
        elif isinstance(expression, LogicalSort):
            return ("sort", expression.sort_fields)
        elif isinstance(expression, PhysicalScan):
            return ("phys_scan", expression.record_types)
        elif isinstance(expression, PhysicalIndexScan):
            return (
                "phys_idx",
                expression.index_name,
                str(expression.scan_predicates),
                expression.reverse,
            )
        elif isinstance(expression, PhysicalFilter):
            return ("phys_filter", str(expression.predicate))
        elif isinstance(expression, PhysicalSort):
            return ("phys_sort", expression.sort_fields)
        else:
            # Generic fallback using __dict__
            try:
                return tuple(sorted(expression.__dict__.items()))
            except (TypeError, AttributeError):
                return (id(expression),)

    def get_group(self, group_id: int) -> MemoGroup | None:
        """Get a group by ID."""
        if 0 <= group_id < len(self._groups):
            return self._groups[group_id]
        return None

    def get_root_group(self) -> MemoGroup | None:
        """Get the root group (first group created, typically the query root)."""
        if self._groups:
            return self._groups[0]
        return None

    def merge_groups(self, group1: MemoGroup, group2: MemoGroup) -> MemoGroup:
        """Merge two groups that are discovered to be equivalent.

        All expressions from group2 are moved to group1, and group2 is marked
        as merged.
        """
        if group1 == group2:
            return group1

        # Move all expressions from group2 to group1
        for expr in group2.expressions:
            expr.group = group1
            group1.expressions.append(expr)
            self._expression_to_group[expr.expr_id] = group1

        # Merge explored rules
        group1.explored_rules.update(group2.explored_rules)

        # Merge winners (keep better ones)
        for key, winner in group2.winners.items():
            if key not in group1.winners or winner.cost < group1.winners[key].cost:
                group1.winners[key] = winner

        # Clear group2
        group2.expressions = []
        group2.winners = {}

        # Update fingerprints pointing to group2
        for fp, group in list(self._fingerprints.items()):
            if group == group2:
                self._fingerprints[fp] = group1

        return group1

    def extract_best_plan(
        self, group: MemoGroup | None = None, physical_props: tuple | None = None
    ) -> RelationalExpression | None:
        """Extract the best physical plan from the memo.

        Args:
            group: Group to extract from (default: root group)
            physical_props: Required physical properties

        Returns:
            The best physical expression tree, or None if not found.
        """
        if group is None:
            group = self.get_root_group()

        if group is None:
            return None

        winner = group.get_winner(physical_props)
        if winner is None:
            return None

        # Recursively extract children
        return self._extract_plan_recursive(winner.expression)

    def _extract_plan_recursive(self, group_expr: GroupExpression) -> RelationalExpression:
        """Recursively extract plan from GroupExpression."""
        expression = group_expr.expression

        # If no children, return as-is
        if not group_expr.child_groups:
            return expression

        # Recursively get best plans for children
        child_plans = []
        for child_group in group_expr.child_groups:
            winner = child_group.get_winner()
            if winner:
                child_plan = self._extract_plan_recursive(winner.expression)
                child_plans.append(child_plan)
            else:
                # No winner found for child - use first physical expression
                for phys_expr in child_group.get_physical_expressions():
                    child_plan = self._extract_plan_recursive(phys_expr)
                    child_plans.append(child_plan)
                    break

        # Create new expression with resolved children
        return self._rebuild_with_children(expression, child_plans)

    def _rebuild_with_children(
        self, expression: RelationalExpression, children: list[RelationalExpression]
    ) -> RelationalExpression:
        """Create a copy of expression with new children.

        This is needed because expressions are immutable (frozen dataclasses).
        """
        from dataclasses import replace

        from fdb_record_layer.planner.cascades.expressions import (
            LogicalFilter,
            LogicalIntersection,
            LogicalProject,
            LogicalSort,
            LogicalUnion,
            PhysicalFilter,
            PhysicalIntersection,
            PhysicalSort,
            PhysicalUnion,
        )

        if not children:
            return expression

        # Handle expressions with children
        if isinstance(expression, (LogicalFilter, PhysicalFilter)):
            return replace(expression, input_expr=children[0])
        elif isinstance(expression, (LogicalProject,)):
            return replace(expression, input_expr=children[0])
        elif isinstance(expression, (LogicalSort, PhysicalSort)):
            return replace(expression, input_expr=children[0])
        elif isinstance(expression, (LogicalUnion, PhysicalUnion)):
            return replace(expression, inputs=tuple(children))
        elif isinstance(expression, (LogicalIntersection, PhysicalIntersection)):
            return replace(expression, inputs=tuple(children))
        else:
            # Expression has no child fields we recognize
            return expression

    def dump(self, verbose: bool = False) -> str:
        """Dump memo contents for debugging."""
        lines = [f"Memo: {self.num_groups} groups, {self.num_expressions} expressions"]
        lines.append("-" * 60)

        for group in self._groups:
            lines.append(f"\n{group}")
            if group.logical_properties:
                lines.append(f"  Properties: {group.logical_properties}")
            if group.winners:
                for key, winner in group.winners.items():
                    lines.append(f"  Winner({key}): {winner}")

            if verbose:
                for expr in group.expressions:
                    kind = expr.expression.kind.name
                    lines.append(f"    [{kind}] {expr}")
                    if expr.child_groups:
                        children = ", ".join(f"G{g.group_id}" for g in expr.child_groups)
                        lines.append(f"      Children: {children}")

        return "\n".join(lines)

    def __repr__(self) -> str:
        return f"Memo({self.num_groups} groups, {self.num_expressions} exprs)"
