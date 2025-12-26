"""Field key expression for extracting field values."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

from fdb_record_layer.expressions.base import FanType, KeyExpression

if TYPE_CHECKING:
    from google.protobuf.message import Message


@dataclass(frozen=True)
class FieldKeyExpression(KeyExpression):
    """Extract a field value from a record.

    This is the most common key expression, used to create indexes
    on individual fields.

    Attributes:
        field_name: The name of the field to extract.
        fan_type: How to handle repeated fields.
        null_standalone: If True, include None values in results.
    """

    field_name: str
    fan_type: FanType = FanType.NONE
    null_standalone: bool = False

    def evaluate(self, record: Message) -> list[tuple[Any, ...]]:
        """Extract the field value from the record.

        Args:
            record: The protobuf message.

        Returns:
            List of key tuples. For FAN_OUT on repeated fields,
            returns one tuple per element.
        """
        # Get the field value
        if not hasattr(record, self.field_name):
            if self.null_standalone:
                return [(None,)]
            return []

        value = getattr(record, self.field_name)

        # Handle None/default values
        if value is None:
            if self.null_standalone:
                return [(None,)]
            return []

        # Check if this is a repeated field
        is_repeated = self._is_repeated(record)

        if is_repeated:
            if self.fan_type == FanType.FAN_OUT:
                # One key per element
                if len(value) == 0:
                    if self.null_standalone:
                        return [(None,)]
                    return []
                return [(v,) for v in value]
            elif self.fan_type == FanType.CONCATENATE:
                # All elements as a nested tuple
                return [(tuple(value),)]
            else:
                # FanType.NONE - treat as error or take first?
                # For now, take first element if exists
                if len(value) > 0:
                    return [(value[0],)]
                if self.null_standalone:
                    return [(None,)]
                return []
        else:
            # Scalar field
            return [(value,)]

    def _is_repeated(self, record: Message) -> bool:
        """Check if the field is a repeated field."""
        descriptor = record.DESCRIPTOR
        for field in descriptor.fields:
            if field.name == self.field_name:
                return field.label == field.LABEL_REPEATED
        return False

    def get_column_size(self) -> int:
        return 1

    def validate(self, descriptor: Any) -> list[str]:
        """Validate that the field exists in the descriptor."""
        errors = []
        field_names = {f.name for f in descriptor.fields}
        if self.field_name not in field_names:
            errors.append(f"Field '{self.field_name}' not found in {descriptor.name}")
        return errors


def field(
    name: str,
    fan_type: FanType = FanType.NONE,
    null_standalone: bool = False,
) -> FieldKeyExpression:
    """Create a field key expression.

    Args:
        name: The field name.
        fan_type: How to handle repeated fields.
        null_standalone: Whether to include null values.

    Returns:
        A FieldKeyExpression.

    Example:
        >>> # Simple field
        >>> key = field("user_id")
        >>>
        >>> # Repeated field with fan out
        >>> key = field("tags", fan_type=FanType.FAN_OUT)
    """
    return FieldKeyExpression(
        field_name=name,
        fan_type=fan_type,
        null_standalone=null_standalone,
    )
