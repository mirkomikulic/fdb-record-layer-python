"""Nest key expression for navigating into nested messages."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

from fdb_record_layer.expressions.base import KeyExpression

if TYPE_CHECKING:
    from google.protobuf.message import Message


@dataclass(frozen=True)
class NestKeyExpression(KeyExpression):
    """Navigate into a nested message field and evaluate a child expression.

    This allows creating keys/indexes on fields within nested messages.
    For repeated nested messages, each element is evaluated separately.

    Attributes:
        parent_field: The name of the nested message field.
        child: The expression to evaluate within the nested message.
    """

    parent_field: str
    child: KeyExpression

    def evaluate(self, record: Message) -> list[tuple[Any, ...]]:
        """Navigate into the nested field and evaluate the child.

        Args:
            record: The protobuf message.

        Returns:
            List of key tuples from evaluating child on nested messages.
        """
        if not hasattr(record, self.parent_field):
            return []

        nested = getattr(record, self.parent_field)

        if nested is None:
            return []

        # Check if this is a repeated field
        is_repeated = self._is_repeated(record)

        if is_repeated:
            # Evaluate child on each element
            results: list[tuple[Any, ...]] = []
            for item in nested:
                results.extend(self.child.evaluate(item))
            return results
        else:
            # Single nested message
            return self.child.evaluate(nested)

    def _is_repeated(self, record: Message) -> bool:
        """Check if the parent field is a repeated field."""
        descriptor = record.DESCRIPTOR
        for field in descriptor.fields:
            if field.name == self.parent_field:
                return field.label == field.LABEL_REPEATED
        return False

    def get_column_size(self) -> int:
        return self.child.get_column_size()

    def validate(self, descriptor: Any) -> list[str]:
        """Validate the parent field exists and is a message type."""
        errors = []

        # Find the parent field
        parent_descriptor = None
        for field in descriptor.fields:
            if field.name == self.parent_field:
                if field.message_type is None:
                    errors.append(
                        f"Field '{self.parent_field}' in {descriptor.name} is not a message type"
                    )
                    return errors
                parent_descriptor = field.message_type
                break

        if parent_descriptor is None:
            errors.append(f"Field '{self.parent_field}' not found in {descriptor.name}")
            return errors

        # Validate child against nested message descriptor
        errors.extend(self.child.validate(parent_descriptor))
        return errors


def nest(parent: str, child: KeyExpression) -> NestKeyExpression:
    """Create a nested key expression.

    Args:
        parent: The name of the nested message field.
        child: The expression to evaluate within the nested message.

    Returns:
        A NestKeyExpression.

    Example:
        >>> # Index on a field within a nested message
        >>> key = nest("address", field("city"))
        >>>
        >>> # Compound nested key
        >>> key = nest("address", concat(field("country"), field("postal_code")))
    """
    return NestKeyExpression(parent_field=parent, child=child)
