"""Record type key expression for including record type in keys."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

from fdb_record_layer.expressions.base import KeyExpression

if TYPE_CHECKING:
    from google.protobuf.message import Message


@dataclass(frozen=True)
class RecordTypeKeyExpression(KeyExpression):
    """Include the record type name in the key.

    This is useful for:
    - Creating indexes that span multiple record types
    - Including type information in primary keys for polymorphic storage

    The record type name is extracted from the protobuf message descriptor.
    """

    def evaluate(self, record: Message) -> list[tuple[Any, ...]]:
        """Extract the record type name.

        Args:
            record: The protobuf message.

        Returns:
            A single tuple containing the record type name.
        """
        return [(record.DESCRIPTOR.name,)]

    def get_column_size(self) -> int:
        return 1

    def validate(self, descriptor: Any) -> list[str]:
        # Always valid - any message has a descriptor name
        return []


# Singleton instance
_RECORD_TYPE_EXPR = RecordTypeKeyExpression()


def record_type() -> RecordTypeKeyExpression:
    """Get the record type key expression.

    Returns:
        A RecordTypeKeyExpression.

    Example:
        >>> # Include record type in index key for multi-type indexes
        >>> key = concat(record_type(), field("email"))
    """
    return _RECORD_TYPE_EXPR
