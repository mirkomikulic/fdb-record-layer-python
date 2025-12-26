"""Base classes for key expressions."""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from enum import Enum
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from google.protobuf.message import Message


class FanType(Enum):
    """Specifies how repeated fields should be handled in key expressions.

    NONE: Treat the field as a scalar (error if repeated).
    FAN_OUT: Generate one key per element in the repeated field.
    CONCATENATE: Combine all elements into a single nested tuple.
    """

    NONE = "none"
    FAN_OUT = "fan_out"
    CONCATENATE = "concatenate"


class KeyExpression(ABC):
    """Abstract base class for key expressions.

    A key expression defines how to extract one or more key tuples from
    a record. Key expressions are used for:
    - Defining primary keys
    - Defining index keys
    - Defining sort orders

    Key expressions form a tree structure that can be composed to create
    complex key definitions.
    """

    @abstractmethod
    def evaluate(self, record: Message) -> list[tuple[Any, ...]]:
        """Evaluate this expression against a record.

        Args:
            record: The protobuf message to evaluate against.

        Returns:
            A list of key tuples. Most expressions return a single tuple,
            but FAN_OUT expressions may return multiple tuples.
        """
        pass

    @abstractmethod
    def get_column_size(self) -> int:
        """Get the number of columns this expression produces.

        Returns:
            The number of elements in each key tuple.
        """
        pass

    def then(self, other: KeyExpression) -> KeyExpression:
        """Concatenate this expression with another.

        Args:
            other: The expression to append.

        Returns:
            A new ConcatenateKeyExpression combining both.
        """
        from fdb_record_layer.expressions.concat import ConcatenateKeyExpression

        if isinstance(self, ConcatenateKeyExpression):
            return ConcatenateKeyExpression(children=[*self.children, other])
        return ConcatenateKeyExpression(children=[self, other])

    def __add__(self, other: KeyExpression) -> KeyExpression:
        """Operator overload for concatenation."""
        return self.then(other)

    @abstractmethod
    def validate(self, descriptor: Any) -> list[str]:
        """Validate this expression against a message descriptor.

        Args:
            descriptor: The protobuf Descriptor to validate against.

        Returns:
            A list of validation error messages, empty if valid.
        """
        pass

    def normalize(self) -> KeyExpression:
        """Return a normalized form of this expression.

        Subclasses may override to simplify nested structures.
        """
        return self


@dataclass(frozen=True)
class EmptyKeyExpression(KeyExpression):
    """A key expression that produces an empty tuple.

    Useful as a placeholder or for records with no key.
    """

    def evaluate(self, record: Message) -> list[tuple[Any, ...]]:
        return [()]

    def get_column_size(self) -> int:
        return 0

    def validate(self, descriptor: Any) -> list[str]:
        return []


@dataclass(frozen=True)
class LiteralKeyExpression(KeyExpression):
    """A key expression that produces a literal value.

    Useful for including constant values in keys.

    Attributes:
        value: The literal value to include in the key.
    """

    value: Any

    def evaluate(self, record: Message) -> list[tuple[Any, ...]]:
        return [(self.value,)]

    def get_column_size(self) -> int:
        return 1

    def validate(self, descriptor: Any) -> list[str]:
        return []


# Singleton for empty expression
EMPTY = EmptyKeyExpression()


def empty() -> EmptyKeyExpression:
    """Get the empty key expression singleton."""
    return EMPTY


def literal(value: Any) -> LiteralKeyExpression:
    """Create a literal key expression.

    Args:
        value: The literal value.

    Returns:
        A LiteralKeyExpression for the value.
    """
    return LiteralKeyExpression(value=value)
