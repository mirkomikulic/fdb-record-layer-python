"""Concatenate key expression for combining multiple expressions."""

from __future__ import annotations

from dataclasses import dataclass
from dataclasses import field as dataclass_field
from typing import TYPE_CHECKING, Any

from fdb_record_layer.expressions.base import KeyExpression

if TYPE_CHECKING:
    from google.protobuf.message import Message


@dataclass(frozen=True)
class ConcatenateKeyExpression(KeyExpression):
    """Concatenate multiple key expressions into a single key.

    The resulting key contains all columns from all child expressions
    in order. If any child expression has FAN_OUT behavior, the result
    is the cross product of all child results.

    Attributes:
        children: The child expressions to concatenate.
    """

    children: tuple[KeyExpression, ...] = dataclass_field(default_factory=tuple)

    def __init__(self, children: list[KeyExpression] | tuple[KeyExpression, ...]) -> None:
        # Use object.__setattr__ because dataclass is frozen
        object.__setattr__(self, "children", tuple(children))

    def evaluate(self, record: Message) -> list[tuple[Any, ...]]:
        """Evaluate all children and combine results.

        Computes the cross product when multiple children have
        multiple results (from FAN_OUT).

        Args:
            record: The protobuf message.

        Returns:
            List of combined key tuples.
        """
        if not self.children:
            return [()]

        # Start with empty tuples
        results: list[tuple[Any, ...]] = [()]

        for child in self.children:
            child_results = child.evaluate(record)

            if not child_results:
                # If any child produces no results, the whole thing is empty
                return []

            # Cross product with existing results
            new_results: list[tuple[Any, ...]] = []
            for existing in results:
                for child_result in child_results:
                    new_results.append(existing + child_result)
            results = new_results

        return results

    def get_column_size(self) -> int:
        return sum(c.get_column_size() for c in self.children)

    def validate(self, descriptor: Any) -> list[str]:
        """Validate all children."""
        errors = []
        for child in self.children:
            errors.extend(child.validate(descriptor))
        return errors

    def normalize(self) -> KeyExpression:
        """Flatten nested concatenations."""
        flattened: list[KeyExpression] = []

        for child in self.children:
            normalized = child.normalize()
            if isinstance(normalized, ConcatenateKeyExpression):
                flattened.extend(normalized.children)
            else:
                flattened.append(normalized)

        if len(flattened) == 0:
            from fdb_record_layer.expressions.base import EMPTY

            return EMPTY
        if len(flattened) == 1:
            return flattened[0]

        return ConcatenateKeyExpression(flattened)

    def then(self, other: KeyExpression) -> KeyExpression:
        """Append another expression efficiently."""
        return ConcatenateKeyExpression([*self.children, other])


def concat(*expressions: KeyExpression) -> KeyExpression:
    """Create a concatenated key expression.

    Args:
        *expressions: The expressions to concatenate.

    Returns:
        A ConcatenateKeyExpression, or a simpler expression if possible.

    Example:
        >>> # Compound key
        >>> key = concat(field("customer_id"), field("order_id"))
        >>>
        >>> # Multi-column index
        >>> key = concat(field("status"), field("created_at"), field("id"))
    """
    if len(expressions) == 0:
        from fdb_record_layer.expressions.base import EMPTY

        return EMPTY
    if len(expressions) == 1:
        return expressions[0]
    return ConcatenateKeyExpression(list(expressions))
