"""Relational expressions for the Cascades optimizer.

Expressions represent query plan nodes in either logical or physical form.
Logical expressions describe WHAT to compute, physical expressions describe HOW.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from enum import Enum
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    pass


class ExpressionKind(str, Enum):
    """Categories of expressions."""

    LOGICAL = "logical"
    PHYSICAL = "physical"


@dataclass(frozen=True)
class ExpressionProperty:
    """Properties derived from an expression.

    Properties flow up from children and are used for:
    - Determining applicable rules
    - Cost estimation
    - Plan validation
    """

    output_fields: frozenset[str] = field(default_factory=frozenset)
    record_types: frozenset[str] = field(default_factory=frozenset)
    is_ordered: bool = False
    order_fields: tuple[str, ...] = ()
    estimated_cardinality: int = 0

    def with_cardinality(self, cardinality: int) -> ExpressionProperty:
        return ExpressionProperty(
            output_fields=self.output_fields,
            record_types=self.record_types,
            is_ordered=self.is_ordered,
            order_fields=self.order_fields,
            estimated_cardinality=cardinality,
        )


class RelationalExpression(ABC):
    """Abstract base for all relational expressions.

    Expressions form a tree representing a query plan. Each expression
    has zero or more child expressions (inputs).
    """

    @property
    @abstractmethod
    def kind(self) -> ExpressionKind:
        """Whether this is a logical or physical expression."""
        pass

    @property
    @abstractmethod
    def children(self) -> list[RelationalExpression]:
        """Get child expressions (inputs)."""
        pass

    @abstractmethod
    def with_children(self, children: list[RelationalExpression]) -> RelationalExpression:
        """Create a copy with different children."""
        pass

    @abstractmethod
    def derive_properties(self, child_props: list[ExpressionProperty]) -> ExpressionProperty:
        """Derive properties from child properties."""
        pass

    @abstractmethod
    def matches_pattern(self, pattern: RelationalExpression) -> bool:
        """Check if this expression matches a pattern for rule application."""
        pass

    def is_logical(self) -> bool:
        return self.kind == ExpressionKind.LOGICAL

    def is_physical(self) -> bool:
        return self.kind == ExpressionKind.PHYSICAL

    @abstractmethod
    def __hash__(self) -> int:
        pass

    @abstractmethod
    def __eq__(self, other: object) -> bool:
        pass


# =============================================================================
# Logical Expressions - describe WHAT to compute
# =============================================================================


class LogicalExpression(RelationalExpression):
    """Base for logical expressions."""

    @property
    def kind(self) -> ExpressionKind:
        return ExpressionKind.LOGICAL


@dataclass(frozen=True)
class LogicalScan(LogicalExpression):
    """Logical scan of a record type.

    Represents: "get all records of type X"
    """

    record_types: tuple[str, ...]

    @property
    def children(self) -> list[RelationalExpression]:
        return []

    def with_children(self, children: list[RelationalExpression]) -> RelationalExpression:
        return self

    def derive_properties(self, child_props: list[ExpressionProperty]) -> ExpressionProperty:
        return ExpressionProperty(
            record_types=frozenset(self.record_types),
            estimated_cardinality=10000,  # Unknown, estimate high
        )

    def matches_pattern(self, pattern: RelationalExpression) -> bool:
        if isinstance(pattern, LogicalScan):
            return pattern.record_types == () or pattern.record_types == self.record_types
        return False

    def __hash__(self) -> int:
        return hash(("LogicalScan", self.record_types))

    def __eq__(self, other: object) -> bool:
        return isinstance(other, LogicalScan) and other.record_types == self.record_types


@dataclass(frozen=True)
class LogicalFilter(LogicalExpression):
    """Logical filter operation.

    Represents: "apply predicate P to input"
    """

    predicate: Any  # QueryComponent
    input_expr: RelationalExpression

    @property
    def children(self) -> list[RelationalExpression]:
        return [self.input_expr]

    def with_children(self, children: list[RelationalExpression]) -> RelationalExpression:
        return LogicalFilter(self.predicate, children[0])

    def derive_properties(self, child_props: list[ExpressionProperty]) -> ExpressionProperty:
        if not child_props:
            return ExpressionProperty()
        child = child_props[0]
        # Assume 50% selectivity
        return child.with_cardinality(max(1, child.estimated_cardinality // 2))

    def matches_pattern(self, pattern: RelationalExpression) -> bool:
        if isinstance(pattern, LogicalFilter):
            return pattern.predicate is None or pattern.predicate == self.predicate
        return False

    def __hash__(self) -> int:
        return hash(("LogicalFilter", id(self.predicate), hash(self.input_expr)))

    def __eq__(self, other: object) -> bool:
        return (
            isinstance(other, LogicalFilter)
            and other.predicate == self.predicate
            and other.input_expr == self.input_expr
        )


@dataclass(frozen=True)
class LogicalProject(LogicalExpression):
    """Logical projection operation.

    Represents: "output only fields F from input"
    """

    fields: tuple[str, ...]
    input_expr: RelationalExpression

    @property
    def children(self) -> list[RelationalExpression]:
        return [self.input_expr]

    def with_children(self, children: list[RelationalExpression]) -> RelationalExpression:
        return LogicalProject(self.fields, children[0])

    def derive_properties(self, child_props: list[ExpressionProperty]) -> ExpressionProperty:
        if not child_props:
            return ExpressionProperty(output_fields=frozenset(self.fields))
        child = child_props[0]
        return ExpressionProperty(
            output_fields=frozenset(self.fields),
            record_types=child.record_types,
            estimated_cardinality=child.estimated_cardinality,
        )

    def matches_pattern(self, pattern: RelationalExpression) -> bool:
        return isinstance(pattern, LogicalProject)

    def __hash__(self) -> int:
        return hash(("LogicalProject", self.fields, hash(self.input_expr)))

    def __eq__(self, other: object) -> bool:
        return (
            isinstance(other, LogicalProject)
            and other.fields == self.fields
            and other.input_expr == self.input_expr
        )


@dataclass(frozen=True)
class LogicalSort(LogicalExpression):
    """Logical sort operation.

    Represents: "sort input by fields F"
    """

    sort_fields: tuple[tuple[str, bool], ...]  # (field, descending)
    input_expr: RelationalExpression

    @property
    def children(self) -> list[RelationalExpression]:
        return [self.input_expr]

    def with_children(self, children: list[RelationalExpression]) -> RelationalExpression:
        return LogicalSort(self.sort_fields, children[0])

    def derive_properties(self, child_props: list[ExpressionProperty]) -> ExpressionProperty:
        if not child_props:
            return ExpressionProperty()
        child = child_props[0]
        return ExpressionProperty(
            output_fields=child.output_fields,
            record_types=child.record_types,
            is_ordered=True,
            order_fields=tuple(f for f, _ in self.sort_fields),
            estimated_cardinality=child.estimated_cardinality,
        )

    def matches_pattern(self, pattern: RelationalExpression) -> bool:
        return isinstance(pattern, LogicalSort)

    def __hash__(self) -> int:
        return hash(("LogicalSort", self.sort_fields, hash(self.input_expr)))

    def __eq__(self, other: object) -> bool:
        return (
            isinstance(other, LogicalSort)
            and other.sort_fields == self.sort_fields
            and other.input_expr == self.input_expr
        )


@dataclass(frozen=True)
class LogicalUnion(LogicalExpression):
    """Logical union of multiple inputs.

    Represents: "combine results from multiple inputs"
    """

    inputs: tuple[RelationalExpression, ...]
    remove_duplicates: bool = True

    @property
    def children(self) -> list[RelationalExpression]:
        return list(self.inputs)

    def with_children(self, children: list[RelationalExpression]) -> RelationalExpression:
        return LogicalUnion(tuple(children), self.remove_duplicates)

    def derive_properties(self, child_props: list[ExpressionProperty]) -> ExpressionProperty:
        all_types: set[str] = set()
        total_card = 0
        for prop in child_props:
            all_types.update(prop.record_types)
            total_card += prop.estimated_cardinality
        return ExpressionProperty(
            record_types=frozenset(all_types),
            estimated_cardinality=total_card,
        )

    def matches_pattern(self, pattern: RelationalExpression) -> bool:
        return isinstance(pattern, LogicalUnion)

    def __hash__(self) -> int:
        return hash(("LogicalUnion", self.inputs, self.remove_duplicates))

    def __eq__(self, other: object) -> bool:
        return (
            isinstance(other, LogicalUnion)
            and other.inputs == self.inputs
            and other.remove_duplicates == self.remove_duplicates
        )


@dataclass(frozen=True)
class LogicalIntersection(LogicalExpression):
    """Logical intersection of multiple inputs."""

    inputs: tuple[RelationalExpression, ...]

    @property
    def children(self) -> list[RelationalExpression]:
        return list(self.inputs)

    def with_children(self, children: list[RelationalExpression]) -> RelationalExpression:
        return LogicalIntersection(tuple(children))

    def derive_properties(self, child_props: list[ExpressionProperty]) -> ExpressionProperty:
        if not child_props:
            return ExpressionProperty()
        min_card = min(p.estimated_cardinality for p in child_props)
        all_types: set[str] = set()
        for prop in child_props:
            all_types.update(prop.record_types)
        return ExpressionProperty(
            record_types=frozenset(all_types),
            estimated_cardinality=min_card,
        )

    def matches_pattern(self, pattern: RelationalExpression) -> bool:
        return isinstance(pattern, LogicalIntersection)

    def __hash__(self) -> int:
        return hash(("LogicalIntersection", self.inputs))

    def __eq__(self, other: object) -> bool:
        return isinstance(other, LogicalIntersection) and other.inputs == self.inputs


@dataclass(frozen=True)
class LogicalIndexScan(LogicalExpression):
    """Logical index scan - uses a specific index.

    This is a "semi-physical" expression - it specifies which index
    but not the exact implementation details.
    """

    index_name: str
    scan_predicates: Any  # ScanComparisons
    record_types: tuple[str, ...]

    @property
    def children(self) -> list[RelationalExpression]:
        return []

    def with_children(self, children: list[RelationalExpression]) -> RelationalExpression:
        return self

    def derive_properties(self, child_props: list[ExpressionProperty]) -> ExpressionProperty:
        # Estimate based on index selectivity
        estimated = 100 if self.scan_predicates else 10000
        return ExpressionProperty(
            record_types=frozenset(self.record_types),
            estimated_cardinality=estimated,
        )

    def matches_pattern(self, pattern: RelationalExpression) -> bool:
        if isinstance(pattern, LogicalIndexScan):
            return pattern.index_name == "" or pattern.index_name == self.index_name
        return False

    def __hash__(self) -> int:
        return hash(("LogicalIndexScan", self.index_name, id(self.scan_predicates)))

    def __eq__(self, other: object) -> bool:
        return (
            isinstance(other, LogicalIndexScan)
            and other.index_name == self.index_name
            and other.scan_predicates == self.scan_predicates
        )


# =============================================================================
# Physical Expressions - describe HOW to compute
# =============================================================================


class PhysicalExpression(RelationalExpression):
    """Base for physical expressions."""

    @property
    def kind(self) -> ExpressionKind:
        return ExpressionKind.PHYSICAL


@dataclass(frozen=True)
class PhysicalScan(PhysicalExpression):
    """Physical full table scan."""

    record_types: tuple[str, ...]

    @property
    def children(self) -> list[RelationalExpression]:
        return []

    def with_children(self, children: list[RelationalExpression]) -> RelationalExpression:
        return self

    def derive_properties(self, child_props: list[ExpressionProperty]) -> ExpressionProperty:
        return ExpressionProperty(
            record_types=frozenset(self.record_types),
            estimated_cardinality=10000,
        )

    def matches_pattern(self, pattern: RelationalExpression) -> bool:
        return isinstance(pattern, PhysicalScan)

    def __hash__(self) -> int:
        return hash(("PhysicalScan", self.record_types))

    def __eq__(self, other: object) -> bool:
        return isinstance(other, PhysicalScan) and other.record_types == self.record_types


@dataclass(frozen=True)
class PhysicalIndexScan(PhysicalExpression):
    """Physical index scan."""

    index_name: str
    scan_predicates: Any  # ScanComparisons
    reverse: bool = False

    @property
    def children(self) -> list[RelationalExpression]:
        return []

    def with_children(self, children: list[RelationalExpression]) -> RelationalExpression:
        return self

    def derive_properties(self, child_props: list[ExpressionProperty]) -> ExpressionProperty:
        estimated = 100 if self.scan_predicates else 10000
        return ExpressionProperty(estimated_cardinality=estimated)

    def matches_pattern(self, pattern: RelationalExpression) -> bool:
        return isinstance(pattern, PhysicalIndexScan)

    def __hash__(self) -> int:
        return hash(("PhysicalIndexScan", self.index_name, id(self.scan_predicates)))

    def __eq__(self, other: object) -> bool:
        return isinstance(other, PhysicalIndexScan) and other.index_name == self.index_name


@dataclass(frozen=True)
class PhysicalFilter(PhysicalExpression):
    """Physical filter (post-scan predicate evaluation)."""

    predicate: Any
    input_expr: RelationalExpression

    @property
    def children(self) -> list[RelationalExpression]:
        return [self.input_expr]

    def with_children(self, children: list[RelationalExpression]) -> RelationalExpression:
        return PhysicalFilter(self.predicate, children[0])

    def derive_properties(self, child_props: list[ExpressionProperty]) -> ExpressionProperty:
        if not child_props:
            return ExpressionProperty()
        return child_props[0].with_cardinality(max(1, child_props[0].estimated_cardinality // 2))

    def matches_pattern(self, pattern: RelationalExpression) -> bool:
        return isinstance(pattern, PhysicalFilter)

    def __hash__(self) -> int:
        return hash(("PhysicalFilter", id(self.predicate), hash(self.input_expr)))

    def __eq__(self, other: object) -> bool:
        return isinstance(other, PhysicalFilter) and other.predicate == self.predicate


@dataclass(frozen=True)
class PhysicalUnion(PhysicalExpression):
    """Physical union with deduplication."""

    inputs: tuple[RelationalExpression, ...]

    @property
    def children(self) -> list[RelationalExpression]:
        return list(self.inputs)

    def with_children(self, children: list[RelationalExpression]) -> RelationalExpression:
        return PhysicalUnion(tuple(children))

    def derive_properties(self, child_props: list[ExpressionProperty]) -> ExpressionProperty:
        total = sum(p.estimated_cardinality for p in child_props)
        return ExpressionProperty(estimated_cardinality=total)

    def matches_pattern(self, pattern: RelationalExpression) -> bool:
        return isinstance(pattern, PhysicalUnion)

    def __hash__(self) -> int:
        return hash(("PhysicalUnion", self.inputs))

    def __eq__(self, other: object) -> bool:
        return isinstance(other, PhysicalUnion) and other.inputs == self.inputs


@dataclass(frozen=True)
class PhysicalIntersection(PhysicalExpression):
    """Physical intersection."""

    inputs: tuple[RelationalExpression, ...]

    @property
    def children(self) -> list[RelationalExpression]:
        return list(self.inputs)

    def with_children(self, children: list[RelationalExpression]) -> RelationalExpression:
        return PhysicalIntersection(tuple(children))

    def derive_properties(self, child_props: list[ExpressionProperty]) -> ExpressionProperty:
        if not child_props:
            return ExpressionProperty()
        return ExpressionProperty(
            estimated_cardinality=min(p.estimated_cardinality for p in child_props)
        )

    def matches_pattern(self, pattern: RelationalExpression) -> bool:
        return isinstance(pattern, PhysicalIntersection)

    def __hash__(self) -> int:
        return hash(("PhysicalIntersection", self.inputs))

    def __eq__(self, other: object) -> bool:
        return isinstance(other, PhysicalIntersection) and other.inputs == self.inputs


@dataclass(frozen=True)
class PhysicalSort(PhysicalExpression):
    """Physical sort operation."""

    sort_fields: tuple[tuple[str, bool], ...]
    input_expr: RelationalExpression

    @property
    def children(self) -> list[RelationalExpression]:
        return [self.input_expr]

    def with_children(self, children: list[RelationalExpression]) -> RelationalExpression:
        return PhysicalSort(self.sort_fields, children[0])

    def derive_properties(self, child_props: list[ExpressionProperty]) -> ExpressionProperty:
        if not child_props:
            return ExpressionProperty()
        return ExpressionProperty(
            is_ordered=True,
            order_fields=tuple(f for f, _ in self.sort_fields),
            estimated_cardinality=child_props[0].estimated_cardinality,
        )

    def matches_pattern(self, pattern: RelationalExpression) -> bool:
        return isinstance(pattern, PhysicalSort)

    def __hash__(self) -> int:
        return hash(("PhysicalSort", self.sort_fields, hash(self.input_expr)))

    def __eq__(self, other: object) -> bool:
        return isinstance(other, PhysicalSort) and other.sort_fields == self.sort_fields
