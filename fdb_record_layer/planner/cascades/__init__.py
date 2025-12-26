"""Cascades cost-based query optimizer.

The Cascades framework is a modern query optimization architecture that uses:
- Memoization to avoid redundant work
- Rule-based transformations for exploring alternatives
- Cost-based selection of the best physical plan
"""

from fdb_record_layer.planner.cascades.cost_model import (
    Cost,
    CostEstimate,
    CostModel,
    DefaultCostModel,
    Statistics,
)
from fdb_record_layer.planner.cascades.expressions import (
    ExpressionKind,
    ExpressionProperty,
    LogicalExpression,
    LogicalFilter,
    LogicalIndexScan,
    LogicalIntersection,
    LogicalProject,
    LogicalScan,
    LogicalSort,
    LogicalUnion,
    PhysicalExpression,
    PhysicalFilter,
    PhysicalIndexScan,
    PhysicalIntersection,
    PhysicalScan,
    PhysicalSort,
    PhysicalUnion,
    RelationalExpression,
)
from fdb_record_layer.planner.cascades.memo import (
    ExpressionRef,
    GroupExpression,
    GroupState,
    Memo,
    MemoGroup,
    Winner,
)
from fdb_record_layer.planner.cascades.planner import (
    CascadesPlanner,
    PlannerConfig,
    Task,
    TaskType,
)
from fdb_record_layer.planner.cascades.rule import (
    CascadesRule,
    FilterMergeRule,
    ImplementationRule,
    ImplementFilterRule,
    ImplementIndexScanRule,
    ImplementIntersectionRule,
    ImplementScanRule,
    ImplementSortRule,
    ImplementUnionRule,
    IndexSelectionRule,
    PredicatePushDownRule,
    PushFilterThroughProjectRule,
    RuleContext,
    RuleMatch,
    RuleSet,
    RuleType,
    TransformationRule,
)

__all__ = [
    # Planner
    "CascadesPlanner",
    "PlannerConfig",
    "Task",
    "TaskType",
    # Expressions
    "RelationalExpression",
    "ExpressionKind",
    "ExpressionProperty",
    "LogicalExpression",
    "PhysicalExpression",
    # Logical
    "LogicalScan",
    "LogicalFilter",
    "LogicalProject",
    "LogicalSort",
    "LogicalUnion",
    "LogicalIntersection",
    "LogicalIndexScan",
    # Physical
    "PhysicalScan",
    "PhysicalIndexScan",
    "PhysicalFilter",
    "PhysicalSort",
    "PhysicalUnion",
    "PhysicalIntersection",
    # Memo
    "Memo",
    "MemoGroup",
    "GroupExpression",
    "ExpressionRef",
    "GroupState",
    "Winner",
    # Rules
    "CascadesRule",
    "TransformationRule",
    "ImplementationRule",
    "RuleSet",
    "RuleContext",
    "RuleMatch",
    "RuleType",
    "PushFilterThroughProjectRule",
    "FilterMergeRule",
    "PredicatePushDownRule",
    "ImplementScanRule",
    "ImplementIndexScanRule",
    "ImplementFilterRule",
    "ImplementSortRule",
    "ImplementUnionRule",
    "ImplementIntersectionRule",
    "IndexSelectionRule",
    # Cost Model
    "CostModel",
    "DefaultCostModel",
    "Cost",
    "CostEstimate",
    "Statistics",
]
