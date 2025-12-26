"""Comparison operators for query predicates."""

from __future__ import annotations

from enum import Enum
from typing import Any


class ComparisonType(str, Enum):
    """Types of comparisons supported in queries."""

    # Equality
    EQUALS = "equals"
    NOT_EQUALS = "not_equals"

    # Relational
    LESS_THAN = "less_than"
    LESS_THAN_OR_EQUALS = "less_than_or_equals"
    GREATER_THAN = "greater_than"
    GREATER_THAN_OR_EQUALS = "greater_than_or_equals"

    # String
    STARTS_WITH = "starts_with"
    ENDS_WITH = "ends_with"
    CONTAINS = "contains"

    # Collection
    IN = "in"
    NOT_IN = "not_in"

    # Null checks
    IS_NULL = "is_null"
    IS_NOT_NULL = "is_not_null"

    # Text search
    TEXT_CONTAINS_ALL = "text_contains_all"
    TEXT_CONTAINS_ANY = "text_contains_any"
    TEXT_CONTAINS_PHRASE = "text_contains_phrase"

    @property
    def is_equality(self) -> bool:
        """Check if this is an equality comparison."""
        return self in (ComparisonType.EQUALS, ComparisonType.IS_NULL)

    @property
    def is_inequality(self) -> bool:
        """Check if this is an inequality comparison."""
        return self in (
            ComparisonType.LESS_THAN,
            ComparisonType.LESS_THAN_OR_EQUALS,
            ComparisonType.GREATER_THAN,
            ComparisonType.GREATER_THAN_OR_EQUALS,
            ComparisonType.STARTS_WITH,
            ComparisonType.IS_NOT_NULL,
        )

    @property
    def can_use_index(self) -> bool:
        """Check if this comparison can use an index."""
        return self in (
            ComparisonType.EQUALS,
            ComparisonType.LESS_THAN,
            ComparisonType.LESS_THAN_OR_EQUALS,
            ComparisonType.GREATER_THAN,
            ComparisonType.GREATER_THAN_OR_EQUALS,
            ComparisonType.STARTS_WITH,
            ComparisonType.IS_NULL,
            ComparisonType.IS_NOT_NULL,
            ComparisonType.IN,
        )


class Comparison:
    """A comparison between a field and a value."""

    def __init__(
        self,
        comparison_type: ComparisonType,
        value: Any = None,
        parameter_name: str | None = None,
    ) -> None:
        """Initialize a comparison.

        Args:
            comparison_type: The type of comparison.
            value: The value to compare against (if not parameterized).
            parameter_name: Name of parameter for parameterized queries.
        """
        self.comparison_type = comparison_type
        self._value = value
        self.parameter_name = parameter_name

    @property
    def value(self) -> Any:
        """Get the comparison value."""
        return self._value

    @property
    def is_parameterized(self) -> bool:
        """Check if this comparison uses a parameter."""
        return self.parameter_name is not None

    def get_value(self, bindings: dict[str, Any] | None = None) -> Any:
        """Get the comparison value, resolving parameters if needed.

        Args:
            bindings: Parameter bindings for parameterized queries.

        Returns:
            The resolved value.
        """
        if self.parameter_name is not None:
            if bindings is None or self.parameter_name not in bindings:
                raise ValueError(f"Missing parameter binding: {self.parameter_name}")
            return bindings[self.parameter_name]
        return self._value

    def evaluate(self, field_value: Any, bindings: dict[str, Any] | None = None) -> bool:
        """Evaluate this comparison against a field value.

        Args:
            field_value: The actual field value from a record.
            bindings: Parameter bindings for parameterized queries.

        Returns:
            True if the comparison is satisfied.
        """
        compare_value = self.get_value(bindings)

        if self.comparison_type == ComparisonType.EQUALS:
            return field_value == compare_value
        elif self.comparison_type == ComparisonType.NOT_EQUALS:
            return field_value != compare_value
        elif self.comparison_type == ComparisonType.LESS_THAN:
            return field_value is not None and field_value < compare_value
        elif self.comparison_type == ComparisonType.LESS_THAN_OR_EQUALS:
            return field_value is not None and field_value <= compare_value
        elif self.comparison_type == ComparisonType.GREATER_THAN:
            return field_value is not None and field_value > compare_value
        elif self.comparison_type == ComparisonType.GREATER_THAN_OR_EQUALS:
            return field_value is not None and field_value >= compare_value
        elif self.comparison_type == ComparisonType.STARTS_WITH:
            return field_value is not None and str(field_value).startswith(str(compare_value))
        elif self.comparison_type == ComparisonType.ENDS_WITH:
            return field_value is not None and str(field_value).endswith(str(compare_value))
        elif self.comparison_type == ComparisonType.CONTAINS:
            return field_value is not None and str(compare_value) in str(field_value)
        elif self.comparison_type == ComparisonType.IN:
            return field_value in compare_value
        elif self.comparison_type == ComparisonType.NOT_IN:
            return field_value not in compare_value
        elif self.comparison_type == ComparisonType.IS_NULL:
            return field_value is None
        elif self.comparison_type == ComparisonType.IS_NOT_NULL:
            return field_value is not None
        elif self.comparison_type == ComparisonType.TEXT_CONTAINS_ALL:
            if field_value is None:
                return False
            tokens = set(str(field_value).lower().split())
            search_tokens = set(str(t).lower() for t in compare_value)
            return search_tokens.issubset(tokens)
        elif self.comparison_type == ComparisonType.TEXT_CONTAINS_ANY:
            if field_value is None:
                return False
            tokens = set(str(field_value).lower().split())
            search_tokens = set(str(t).lower() for t in compare_value)
            return bool(search_tokens.intersection(tokens))
        elif self.comparison_type == ComparisonType.TEXT_CONTAINS_PHRASE:
            if field_value is None:
                return False
            return str(compare_value).lower() in str(field_value).lower()
        else:
            raise ValueError(f"Unknown comparison type: {self.comparison_type}")

    def __repr__(self) -> str:
        if self.parameter_name:
            return f"Comparison({self.comparison_type.value}, ${self.parameter_name})"
        return f"Comparison({self.comparison_type.value}, {self._value!r})"


# Factory functions for creating comparisons
def equals(value: Any) -> Comparison:
    """Create an EQUALS comparison."""
    return Comparison(ComparisonType.EQUALS, value)


def not_equals(value: Any) -> Comparison:
    """Create a NOT_EQUALS comparison."""
    return Comparison(ComparisonType.NOT_EQUALS, value)


def less_than(value: Any) -> Comparison:
    """Create a LESS_THAN comparison."""
    return Comparison(ComparisonType.LESS_THAN, value)


def less_than_or_equals(value: Any) -> Comparison:
    """Create a LESS_THAN_OR_EQUALS comparison."""
    return Comparison(ComparisonType.LESS_THAN_OR_EQUALS, value)


def greater_than(value: Any) -> Comparison:
    """Create a GREATER_THAN comparison."""
    return Comparison(ComparisonType.GREATER_THAN, value)


def greater_than_or_equals(value: Any) -> Comparison:
    """Create a GREATER_THAN_OR_EQUALS comparison."""
    return Comparison(ComparisonType.GREATER_THAN_OR_EQUALS, value)


def starts_with(prefix: str) -> Comparison:
    """Create a STARTS_WITH comparison."""
    return Comparison(ComparisonType.STARTS_WITH, prefix)


def in_values(values: list[Any]) -> Comparison:
    """Create an IN comparison."""
    return Comparison(ComparisonType.IN, values)


def is_null() -> Comparison:
    """Create an IS_NULL comparison."""
    return Comparison(ComparisonType.IS_NULL)


def is_not_null() -> Comparison:
    """Create an IS_NOT_NULL comparison."""
    return Comparison(ComparisonType.IS_NOT_NULL)


def parameter(name: str, comparison_type: ComparisonType = ComparisonType.EQUALS) -> Comparison:
    """Create a parameterized comparison."""
    return Comparison(comparison_type, parameter_name=name)
