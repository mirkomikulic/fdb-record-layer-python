"""Query component hierarchy for building query filters."""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

from fdb_record_layer.query.comparisons import Comparison, ComparisonType

if TYPE_CHECKING:
    from google.protobuf.message import Message


class QueryComponent(ABC):
    """Abstract base for query filter components.

    QueryComponents form a tree structure representing query predicates.
    They can be composed with AND, OR, and NOT operations.
    """

    @abstractmethod
    def evaluate(
        self,
        record: Message,
        bindings: dict[str, Any] | None = None,
    ) -> bool:
        """Evaluate this component against a record.

        Args:
            record: The protobuf message to evaluate.
            bindings: Parameter bindings for parameterized queries.

        Returns:
            True if the record matches this component.
        """
        pass

    @abstractmethod
    def get_fields(self) -> set[str]:
        """Get all field names referenced by this component."""
        pass

    def and_(self, other: QueryComponent) -> QueryComponent:
        """Combine with another component using AND."""
        if isinstance(self, AndComponent):
            return AndComponent(children=[*self.children, other])
        return AndComponent(children=[self, other])

    def or_(self, other: QueryComponent) -> QueryComponent:
        """Combine with another component using OR."""
        if isinstance(self, OrComponent):
            return OrComponent(children=[*self.children, other])
        return OrComponent(children=[self, other])

    def not_(self) -> QueryComponent:
        """Negate this component."""
        return NotComponent(child=self)

    def __and__(self, other: QueryComponent) -> QueryComponent:
        return self.and_(other)

    def __or__(self, other: QueryComponent) -> QueryComponent:
        return self.or_(other)

    def __invert__(self) -> QueryComponent:
        return self.not_()


@dataclass
class FieldComponent(QueryComponent):
    """A comparison on a single field.

    This is the most common query component, used to filter
    records based on field values.

    Attributes:
        field_name: The name of the field to compare.
        comparison: The comparison to apply.
    """

    field_name: str
    comparison: Comparison

    def evaluate(
        self,
        record: Message,
        bindings: dict[str, Any] | None = None,
    ) -> bool:
        """Evaluate the field comparison against a record."""
        if not hasattr(record, self.field_name):
            return self.comparison.comparison_type == ComparisonType.IS_NULL

        field_value = getattr(record, self.field_name)
        return self.comparison.evaluate(field_value, bindings)

    def get_fields(self) -> set[str]:
        return {self.field_name}

    def __repr__(self) -> str:
        return f"FieldComponent({self.field_name}, {self.comparison})"


@dataclass
class NestedFieldComponent(QueryComponent):
    """A comparison on a field within a nested message.

    Attributes:
        parent_field: The name of the nested message field.
        child: The component to evaluate within the nested message.
    """

    parent_field: str
    child: QueryComponent

    def evaluate(
        self,
        record: Message,
        bindings: dict[str, Any] | None = None,
    ) -> bool:
        """Evaluate within the nested message."""
        if not hasattr(record, self.parent_field):
            return False

        nested = getattr(record, self.parent_field)
        if nested is None:
            return False

        # Check if it's a repeated field
        if hasattr(nested, "__iter__") and not isinstance(nested, (str, bytes)):
            # For repeated nested messages, check if any match
            return any(self.child.evaluate(item, bindings) for item in nested)

        return self.child.evaluate(nested, bindings)

    def get_fields(self) -> set[str]:
        return {f"{self.parent_field}.{f}" for f in self.child.get_fields()}


@dataclass
class AndComponent(QueryComponent):
    """Logical AND of multiple components.

    All children must match for the overall component to match.

    Attributes:
        children: The child components to AND together.
    """

    children: list[QueryComponent] = field(default_factory=list)

    def evaluate(
        self,
        record: Message,
        bindings: dict[str, Any] | None = None,
    ) -> bool:
        """All children must match."""
        return all(child.evaluate(record, bindings) for child in self.children)

    def get_fields(self) -> set[str]:
        result: set[str] = set()
        for child in self.children:
            result.update(child.get_fields())
        return result

    def __repr__(self) -> str:
        return f"And({self.children})"


@dataclass
class OrComponent(QueryComponent):
    """Logical OR of multiple components.

    At least one child must match for the overall component to match.

    Attributes:
        children: The child components to OR together.
    """

    children: list[QueryComponent] = field(default_factory=list)

    def evaluate(
        self,
        record: Message,
        bindings: dict[str, Any] | None = None,
    ) -> bool:
        """At least one child must match."""
        return any(child.evaluate(record, bindings) for child in self.children)

    def get_fields(self) -> set[str]:
        result: set[str] = set()
        for child in self.children:
            result.update(child.get_fields())
        return result

    def __repr__(self) -> str:
        return f"Or({self.children})"


@dataclass
class NotComponent(QueryComponent):
    """Logical NOT of a component.

    Attributes:
        child: The component to negate.
    """

    child: QueryComponent

    def evaluate(
        self,
        record: Message,
        bindings: dict[str, Any] | None = None,
    ) -> bool:
        """Negate the child's result."""
        return not self.child.evaluate(record, bindings)

    def get_fields(self) -> set[str]:
        return self.child.get_fields()

    def __repr__(self) -> str:
        return f"Not({self.child})"


@dataclass
class OneOfThemComponent(QueryComponent):
    """Match if any element of a repeated field satisfies a condition.

    Attributes:
        field_name: The name of the repeated field.
        comparison: The comparison to apply to each element.
    """

    field_name: str
    comparison: Comparison

    def evaluate(
        self,
        record: Message,
        bindings: dict[str, Any] | None = None,
    ) -> bool:
        """Check if any element matches."""
        if not hasattr(record, self.field_name):
            return False

        field_value = getattr(record, self.field_name)
        if field_value is None:
            return False

        if not hasattr(field_value, "__iter__"):
            # Not a repeated field, treat as single value
            return self.comparison.evaluate(field_value, bindings)

        return any(self.comparison.evaluate(item, bindings) for item in field_value)

    def get_fields(self) -> set[str]:
        return {self.field_name}


@dataclass
class RecordTypeComponent(QueryComponent):
    """Match records of specific types.

    Attributes:
        record_types: The record type names to match.
    """

    record_types: list[str]

    def evaluate(
        self,
        record: Message,
        bindings: dict[str, Any] | None = None,
    ) -> bool:
        """Check if record type matches."""
        return record.DESCRIPTOR.name in self.record_types

    def get_fields(self) -> set[str]:
        return set()


# Factory functions for creating components
def field_equals(name: str, value: Any) -> FieldComponent:
    """Create a field equals comparison."""
    return FieldComponent(name, Comparison(ComparisonType.EQUALS, value))


def field_not_equals(name: str, value: Any) -> FieldComponent:
    """Create a field not equals comparison."""
    return FieldComponent(name, Comparison(ComparisonType.NOT_EQUALS, value))


def field_greater_than(name: str, value: Any) -> FieldComponent:
    """Create a field greater than comparison."""
    return FieldComponent(name, Comparison(ComparisonType.GREATER_THAN, value))


def field_less_than(name: str, value: Any) -> FieldComponent:
    """Create a field less than comparison."""
    return FieldComponent(name, Comparison(ComparisonType.LESS_THAN, value))


def field_in(name: str, values: list[Any]) -> FieldComponent:
    """Create a field IN comparison."""
    return FieldComponent(name, Comparison(ComparisonType.IN, values))


def field_starts_with(name: str, prefix: str) -> FieldComponent:
    """Create a field starts with comparison."""
    return FieldComponent(name, Comparison(ComparisonType.STARTS_WITH, prefix))


def field_is_null(name: str) -> FieldComponent:
    """Create a field is null comparison."""
    return FieldComponent(name, Comparison(ComparisonType.IS_NULL))


def field_is_not_null(name: str) -> FieldComponent:
    """Create a field is not null comparison."""
    return FieldComponent(name, Comparison(ComparisonType.IS_NOT_NULL))


def and_(*components: QueryComponent) -> AndComponent:
    """Create an AND component."""
    return AndComponent(children=list(components))


def or_(*components: QueryComponent) -> OrComponent:
    """Create an OR component."""
    return OrComponent(children=list(components))


def not_(component: QueryComponent) -> NotComponent:
    """Create a NOT component."""
    return NotComponent(child=component)
