"""Cascades cost-based query planner.

This is the main entry point for the Cascades optimizer. It takes a logical
query plan, explores the search space using rules, and returns the optimal
physical plan.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum, auto
from typing import TYPE_CHECKING, Any

from fdb_record_layer.planner.cascades.cost_model import (
    Cost,
    DefaultCostModel,
    Statistics,
)
from fdb_record_layer.planner.cascades.expressions import (
    ExpressionKind,
    LogicalFilter,
    LogicalScan,
    RelationalExpression,
)
from fdb_record_layer.planner.cascades.memo import (
    GroupExpression,
    GroupState,
    Memo,
    MemoGroup,
)
from fdb_record_layer.planner.cascades.rule import (
    RuleContext,
    RuleMatch,
    RuleSet,
    RuleType,
)

if TYPE_CHECKING:
    from fdb_record_layer.metadata.record_metadata import RecordMetaData
    from fdb_record_layer.plans.base import RecordQueryPlan
    from fdb_record_layer.query.query import RecordQuery


class TaskType(Enum):
    """Types of tasks in the Cascades optimizer."""

    EXPLORE_GROUP = auto()  # Explore alternatives in a group
    EXPLORE_EXPRESSION = auto()  # Apply transformation rules
    IMPLEMENT_EXPRESSION = auto()  # Apply implementation rules
    OPTIMIZE_GROUP = auto()  # Find best plan for a group
    OPTIMIZE_INPUTS = auto()  # Recursively optimize children


@dataclass
class Task:
    """A task in the Cascades optimization queue."""

    task_type: TaskType
    group: MemoGroup
    expression: GroupExpression | None = None
    required_properties: Any | None = None
    cost_limit: float | None = None


@dataclass
class PlannerConfig:
    """Configuration for the Cascades planner."""

    # Maximum number of tasks to process
    max_tasks: int = 10000

    # Maximum depth for exploration
    max_depth: int = 100

    # Whether to use branch-and-bound pruning
    use_pruning: bool = True

    # Timeout in seconds (0 = no timeout)
    timeout_seconds: float = 0.0

    # Enable debug output
    debug: bool = False


class CascadesPlanner:
    """Cost-based query planner using the Cascades optimization framework.

    The Cascades planner explores the space of equivalent query plans using
    transformation and implementation rules, using a cost model to select
    the best plan.

    Key concepts:
    - Memo: Stores all explored expressions grouped by equivalence
    - Rules: Transform logical expressions or implement as physical plans
    - Cost Model: Estimates execution cost of physical plans
    - Tasks: Work items processed in a priority queue

    Example:
        >>> planner = CascadesPlanner(metadata)
        >>> plan = planner.plan(query)
    """

    def __init__(
        self,
        metadata: RecordMetaData,
        rules: RuleSet | None = None,
        cost_model: DefaultCostModel | None = None,
        config: PlannerConfig | None = None,
    ) -> None:
        self._metadata = metadata
        self._rules = rules or RuleSet.default()
        self._cost_model = cost_model or DefaultCostModel(metadata)
        self._config = config or PlannerConfig()

        # State for current optimization
        self._memo: Memo | None = None
        self._tasks: list[Task] = []
        self._tasks_processed = 0

    @property
    def memo(self) -> Memo | None:
        """Get the memo from the last optimization."""
        return self._memo

    def plan(self, query: RecordQuery) -> RecordQueryPlan:
        """Create an optimal execution plan for a query.

        Args:
            query: The query to plan

        Returns:
            Optimal physical execution plan
        """
        # Convert query to logical expression tree
        logical_expr = self._query_to_logical(query)

        # Optimize the logical expression
        physical_expr = self.optimize(logical_expr)

        # Convert to RecordQueryPlan
        return self._expression_to_plan(physical_expr, query)

    def optimize(self, logical_expr: RelationalExpression) -> RelationalExpression | None:
        """Optimize a logical expression to find the best physical plan.

        Args:
            logical_expr: The root logical expression

        Returns:
            The optimal physical expression, or None if optimization failed
        """
        # Initialize memo
        self._memo = Memo()
        self._tasks = []
        self._tasks_processed = 0

        # Add root expression to memo
        root_group = self._memo.create_group(logical_expr)

        # Start optimization from root
        self._add_task(Task(task_type=TaskType.OPTIMIZE_GROUP, group=root_group))

        # Process tasks until done
        self._process_tasks()

        # Extract best plan
        return self._memo.extract_best_plan(root_group)

    def _add_task(self, task: Task) -> None:
        """Add a task to the work queue."""
        self._tasks.append(task)

    def _process_tasks(self) -> None:
        """Process tasks until the queue is empty or limits are hit."""
        while self._tasks and self._tasks_processed < self._config.max_tasks:
            task = self._tasks.pop()
            self._tasks_processed += 1

            if self._config.debug:
                print(f"Task {self._tasks_processed}: {task.task_type.name} on {task.group}")

            self._process_task(task)

    def _process_task(self, task: Task) -> None:
        """Process a single task."""
        if task.task_type == TaskType.OPTIMIZE_GROUP:
            self._optimize_group(task)
        elif task.task_type == TaskType.EXPLORE_GROUP:
            self._explore_group(task)
        elif task.task_type == TaskType.EXPLORE_EXPRESSION:
            self._explore_expression(task)
        elif task.task_type == TaskType.IMPLEMENT_EXPRESSION:
            self._implement_expression(task)
        elif task.task_type == TaskType.OPTIMIZE_INPUTS:
            self._optimize_inputs(task)

    def _optimize_group(self, task: Task) -> None:
        """Optimize a group to find its best plan."""
        group = task.group

        # If already optimized with compatible properties, skip
        if group.state == GroupState.OPTIMIZED:
            if group.get_winner(task.required_properties):
                return

        group.state = GroupState.OPTIMIZING

        # First explore the group to generate alternatives
        self._add_task(
            Task(
                task_type=TaskType.EXPLORE_GROUP,
                group=group,
                required_properties=task.required_properties,
                cost_limit=task.cost_limit,
            )
        )

        # Then optimize each expression
        for expr in list(group.expressions):
            self._add_task(
                Task(
                    task_type=TaskType.OPTIMIZE_INPUTS,
                    group=group,
                    expression=expr,
                    required_properties=task.required_properties,
                    cost_limit=task.cost_limit,
                )
            )

    def _explore_group(self, task: Task) -> None:
        """Explore alternatives in a group."""
        group = task.group

        if group.state in (GroupState.EXPLORED, GroupState.OPTIMIZED):
            return

        group.state = GroupState.EXPLORING

        # Apply transformation rules to each logical expression
        for expr in list(group.get_logical_expressions()):
            self._add_task(
                Task(
                    task_type=TaskType.EXPLORE_EXPRESSION,
                    group=group,
                    expression=expr,
                )
            )

            # Also try implementation rules
            self._add_task(
                Task(
                    task_type=TaskType.IMPLEMENT_EXPRESSION,
                    group=group,
                    expression=expr,
                )
            )

        group.state = GroupState.EXPLORED

    def _explore_expression(self, task: Task) -> None:
        """Apply transformation rules to an expression."""
        group = task.group
        expr = task.expression

        if expr is None or expr.explored:
            return

        assert self._memo is not None
        context = RuleContext(
            memo=self._memo,
            metadata=self._metadata,
            group=group,
            required_properties=task.required_properties,
            cost_limit=task.cost_limit,
        )

        # Apply matching transformation rules
        for rule in self._rules.get_matching_rules(expr, RuleType.TRANSFORMATION, context):
            if rule.name in group.explored_rules:
                continue

            match = RuleMatch(expression=expr, bindings={})

            for new_expr in rule.apply(match, context):
                # Add new expression to the group
                self._memo.add_expression(new_expr, group)

            group.explored_rules.add(rule.name)

        expr.explored = True

    def _implement_expression(self, task: Task) -> None:
        """Apply implementation rules to a logical expression."""
        group = task.group
        expr = task.expression

        if expr is None:
            return

        # Only implement logical expressions
        if expr.expression.kind != ExpressionKind.LOGICAL:
            return

        assert self._memo is not None
        context = RuleContext(
            memo=self._memo,
            metadata=self._metadata,
            group=group,
            required_properties=task.required_properties,
            cost_limit=task.cost_limit,
        )

        # Apply matching implementation rules
        for rule in self._rules.get_matching_rules(expr, RuleType.IMPLEMENTATION, context):
            match = RuleMatch(expression=expr, bindings={})

            for physical_expr in rule.apply(match, context):
                # Add physical expression to the group
                self._memo.add_expression(physical_expr, group)

    def _optimize_inputs(self, task: Task) -> None:
        """Recursively optimize child groups and compute cost."""
        group = task.group
        expr = task.expression

        if expr is None:
            return

        # Only compute cost for physical expressions
        if expr.expression.kind != ExpressionKind.PHYSICAL:
            return

        # Optimize child groups first
        child_costs: list[Cost] = []

        for child_group in expr.child_groups:
            # Recursively optimize child
            self._add_task(
                Task(
                    task_type=TaskType.OPTIMIZE_GROUP,
                    group=child_group,
                    required_properties=None,  # Could propagate properties
                )
            )

            # Get child's best cost
            child_winner = child_group.get_winner()
            if child_winner:
                child_costs.append(Cost(cpu=child_winner.cost, io=0))
            else:
                # Child not yet optimized - estimate
                child_costs.append(Cost(cpu=1.0, io=1.0))

        # Compute cost for this expression
        stats = self._get_statistics(expr)
        cost = self._cost_model.estimate_cost(expr, child_costs, stats)

        # Check if this is the new winner
        total_cost = cost.total + sum(c.total for c in child_costs)

        current_winner = group.get_winner(task.required_properties)
        if current_winner is None or total_cost < current_winner.cost:
            group.set_winner(expr, total_cost, task.required_properties)

        expr.cost = total_cost
        group.state = GroupState.OPTIMIZED

    def _get_statistics(self, expr: GroupExpression) -> Statistics:
        """Get statistics for costing an expression."""
        # Extract record types from expression tree
        from fdb_record_layer.planner.cascades.expressions import (
            LogicalScan,
            PhysicalScan,
        )

        expression = expr.expression

        if isinstance(expression, (LogicalScan, PhysicalScan)):
            if expression.record_types:
                return self._cost_model.get_statistics(expression.record_types[0])

        # Default statistics
        return Statistics()

    def _query_to_logical(self, query: RecordQuery) -> RelationalExpression:
        """Convert a RecordQuery to a logical expression tree."""
        # Start with a scan
        record_types = tuple(query.record_types) if query.record_types else ()
        base_expr: RelationalExpression = LogicalScan(record_types=record_types)

        # Add filter if present
        if query.filter is not None:
            base_expr = LogicalFilter(predicate=query.filter, input_expr=base_expr)

        # Add sort if present
        if query.sort:
            from fdb_record_layer.expressions.field import FieldKeyExpression
            from fdb_record_layer.planner.cascades.expressions import LogicalSort

            # Convert SortDescriptor to sort_fields format
            sort_fields: list[tuple[str, bool]] = []
            key_expr = query.sort.key_expression
            if isinstance(key_expr, FieldKeyExpression):
                sort_fields.append((key_expr.field_name, query.sort.reverse))
            # For other key expressions, extract field names if possible
            elif hasattr(key_expr, "field_name"):
                sort_fields.append((key_expr.field_name, query.sort.reverse))

            if sort_fields:
                base_expr = LogicalSort(sort_fields=tuple(sort_fields), input_expr=base_expr)

        return base_expr

    def _expression_to_plan(
        self, expr: RelationalExpression | None, query: RecordQuery
    ) -> RecordQueryPlan:
        """Convert a physical expression to a RecordQueryPlan."""
        from fdb_record_layer.planner.cascades.expressions import (
            PhysicalFilter,
            PhysicalIndexScan,
            PhysicalIntersection,
            PhysicalScan,
            PhysicalSort,
            PhysicalUnion,
        )
        from fdb_record_layer.plans.filter_plan import FilterPlan
        from fdb_record_layer.plans.index_plan import IndexScanPlan
        from fdb_record_layer.plans.intersection_plan import IntersectionPlan
        from fdb_record_layer.plans.scan_plan import ScanPlan
        from fdb_record_layer.plans.union_plan import UnionPlan

        if expr is None:
            # Fallback to full scan
            return ScanPlan(record_types=list(query.record_types or []))

        if isinstance(expr, PhysicalScan):
            return ScanPlan(record_types=list(expr.record_types))

        elif isinstance(expr, PhysicalIndexScan):
            # Convert predicate to scan comparisons
            from fdb_record_layer.planner.scan_comparisons import ScanComparisons

            scan_comparisons = ScanComparisons()
            if expr.scan_predicates:
                scan_comparisons = self._predicate_to_scan_comparisons(expr.scan_predicates)

            return IndexScanPlan(
                index_name=expr.index_name,
                scan_comparisons=scan_comparisons,
                reverse=expr.reverse,
            )

        elif isinstance(expr, PhysicalFilter):
            input_plan = self._expression_to_plan(expr.input_expr, query)
            return FilterPlan(child=input_plan, filter_component=expr.predicate)

        elif isinstance(expr, PhysicalUnion):
            child_plans = [self._expression_to_plan(c, query) for c in expr.inputs]
            return UnionPlan(children=child_plans)

        elif isinstance(expr, PhysicalIntersection):
            child_plans = [self._expression_to_plan(c, query) for c in expr.inputs]
            return IntersectionPlan(children=child_plans)

        elif isinstance(expr, PhysicalSort):
            # Sort plan not yet implemented - fallback to scan with sort
            input_plan = self._expression_to_plan(expr.input_expr, query)
            # Would wrap in SortPlan if available
            return input_plan

        else:
            # Unknown expression type - fallback
            return ScanPlan(record_types=list(query.record_types or []))

    def _predicate_to_scan_comparisons(self, predicate: Any) -> Any:
        """Convert a predicate to ScanComparisons."""
        from fdb_record_layer.planner.scan_comparisons import ScanComparisons
        from fdb_record_layer.query.components import FieldComponent

        comparisons = ScanComparisons()

        if isinstance(predicate, FieldComponent):
            comparisons.add_equality(predicate.comparison)

        return comparisons

    def explain(self, query: RecordQuery) -> str:
        """Generate an explanation of the optimization process.

        Args:
            query: The query to explain

        Returns:
            String explanation of the optimization
        """
        # Run optimization
        logical_expr = self._query_to_logical(query)
        physical_expr = self.optimize(logical_expr)

        lines = ["Cascades Query Optimization"]
        lines.append("=" * 60)

        # Show original query
        lines.append(f"\nQuery: {query}")

        # Show logical expression
        lines.append(f"\nLogical Plan:\n  {logical_expr}")

        # Show memo statistics
        if self._memo:
            lines.append("\nMemo Statistics:")
            lines.append(f"  Groups: {self._memo.num_groups}")
            lines.append(f"  Expressions: {self._memo.num_expressions}")
            lines.append(f"  Tasks processed: {self._tasks_processed}")

        # Show best plan
        lines.append(f"\nOptimal Physical Plan:\n  {physical_expr}")

        # Show cost
        if self._memo:
            root_group = self._memo.get_root_group()
            if root_group:
                winner = root_group.get_winner()
                if winner:
                    lines.append(f"\nEstimated Cost: {winner.cost:.4f}")

        # Detailed memo dump if debug
        if self._config.debug and self._memo:
            lines.append("\n" + self._memo.dump(verbose=True))

        return "\n".join(lines)
