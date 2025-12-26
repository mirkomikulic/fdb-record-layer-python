"""Fluent predicate builders for queries."""

from __future__ import annotations

from typing import Any

from fdb_record_layer.query.comparisons import Comparison, ComparisonType
from fdb_record_layer.query.components import (
    FieldComponent,
    NestedFieldComponent,
    OneOfThemComponent,
    QueryComponent,
)


class Field:
    """Fluent builder for field predicates.

    Example:
        >>> # Simple equality
        >>> Field("name").equals("Alice")
        >>>
        >>> # Range query
        >>> Field("age").greater_than(18).and_(Field("age").less_than(65))
        >>>
        >>> # String prefix
        >>> Field("email").starts_with("admin@")
    """

    def __init__(self, name: str) -> None:
        """Initialize with field name.

        Args:
            name: The field name.
        """
        self.name = name

    def equals(self, value: Any) -> FieldComponent:
        """Create an equals comparison.

        Args:
            value: The value to compare against.

        Returns:
            A FieldComponent for this comparison.
        """
        return FieldComponent(self.name, Comparison(ComparisonType.EQUALS, value))

    def not_equals(self, value: Any) -> FieldComponent:
        """Create a not equals comparison."""
        return FieldComponent(self.name, Comparison(ComparisonType.NOT_EQUALS, value))

    def greater_than(self, value: Any) -> FieldComponent:
        """Create a greater than comparison."""
        return FieldComponent(self.name, Comparison(ComparisonType.GREATER_THAN, value))

    def greater_than_or_equals(self, value: Any) -> FieldComponent:
        """Create a greater than or equals comparison."""
        return FieldComponent(self.name, Comparison(ComparisonType.GREATER_THAN_OR_EQUALS, value))

    def less_than(self, value: Any) -> FieldComponent:
        """Create a less than comparison."""
        return FieldComponent(self.name, Comparison(ComparisonType.LESS_THAN, value))

    def less_than_or_equals(self, value: Any) -> FieldComponent:
        """Create a less than or equals comparison."""
        return FieldComponent(self.name, Comparison(ComparisonType.LESS_THAN_OR_EQUALS, value))

    def starts_with(self, prefix: str) -> FieldComponent:
        """Create a starts with comparison."""
        return FieldComponent(self.name, Comparison(ComparisonType.STARTS_WITH, prefix))

    def ends_with(self, suffix: str) -> FieldComponent:
        """Create an ends with comparison."""
        return FieldComponent(self.name, Comparison(ComparisonType.ENDS_WITH, suffix))

    def contains(self, substring: str) -> FieldComponent:
        """Create a contains comparison."""
        return FieldComponent(self.name, Comparison(ComparisonType.CONTAINS, substring))

    def in_values(self, values: list[Any]) -> FieldComponent:
        """Create an IN comparison."""
        return FieldComponent(self.name, Comparison(ComparisonType.IN, values))

    def not_in_values(self, values: list[Any]) -> FieldComponent:
        """Create a NOT IN comparison."""
        return FieldComponent(self.name, Comparison(ComparisonType.NOT_IN, values))

    def is_null(self) -> FieldComponent:
        """Create an IS NULL comparison."""
        return FieldComponent(self.name, Comparison(ComparisonType.IS_NULL))

    def is_not_null(self) -> FieldComponent:
        """Create an IS NOT NULL comparison."""
        return FieldComponent(self.name, Comparison(ComparisonType.IS_NOT_NULL))

    def between(self, low: Any, high: Any) -> QueryComponent:
        """Create a BETWEEN comparison (inclusive on both ends).

        Args:
            low: The lower bound.
            high: The upper bound.

        Returns:
            An AND of two comparisons.
        """
        return self.greater_than_or_equals(low).and_(self.less_than_or_equals(high))

    def one_of_them(self) -> OneOfThemField:
        """Start building a predicate on repeated field elements.

        Returns:
            A builder for one-of-them predicates.
        """
        return OneOfThemField(self.name)

    def matches(self, component: QueryComponent) -> NestedFieldComponent:
        """Match within a nested message.

        Args:
            component: The component to evaluate within the nested message.

        Returns:
            A NestedFieldComponent.
        """
        return NestedFieldComponent(self.name, component)

    def equals_parameter(self, param_name: str) -> FieldComponent:
        """Create a parameterized equals comparison.

        Args:
            param_name: The parameter name.

        Returns:
            A FieldComponent with parameterized value.
        """
        return FieldComponent(
            self.name,
            Comparison(ComparisonType.EQUALS, parameter_name=param_name),
        )

    def in_parameter(self, param_name: str) -> FieldComponent:
        """Create a parameterized IN comparison.

        Args:
            param_name: The parameter name.

        Returns:
            A FieldComponent with parameterized value.
        """
        return FieldComponent(
            self.name,
            Comparison(ComparisonType.IN, parameter_name=param_name),
        )

    # Text search methods
    def text_contains_all(self, tokens: list[str]) -> FieldComponent:
        """Match if text field contains all tokens."""
        return FieldComponent(self.name, Comparison(ComparisonType.TEXT_CONTAINS_ALL, tokens))

    def text_contains_any(self, tokens: list[str]) -> FieldComponent:
        """Match if text field contains any token."""
        return FieldComponent(self.name, Comparison(ComparisonType.TEXT_CONTAINS_ANY, tokens))

    def text_contains_phrase(self, phrase: str) -> FieldComponent:
        """Match if text field contains phrase."""
        return FieldComponent(self.name, Comparison(ComparisonType.TEXT_CONTAINS_PHRASE, phrase))


class OneOfThemField:
    """Builder for predicates on repeated field elements."""

    def __init__(self, name: str) -> None:
        self.name = name

    def equals(self, value: Any) -> OneOfThemComponent:
        """Match if any element equals value."""
        return OneOfThemComponent(self.name, Comparison(ComparisonType.EQUALS, value))

    def greater_than(self, value: Any) -> OneOfThemComponent:
        """Match if any element is greater than value."""
        return OneOfThemComponent(self.name, Comparison(ComparisonType.GREATER_THAN, value))

    def less_than(self, value: Any) -> OneOfThemComponent:
        """Match if any element is less than value."""
        return OneOfThemComponent(self.name, Comparison(ComparisonType.LESS_THAN, value))

    def in_values(self, values: list[Any]) -> OneOfThemComponent:
        """Match if any element is in values."""
        return OneOfThemComponent(self.name, Comparison(ComparisonType.IN, values))

    def starts_with(self, prefix: str) -> OneOfThemComponent:
        """Match if any element starts with prefix."""
        return OneOfThemComponent(self.name, Comparison(ComparisonType.STARTS_WITH, prefix))
