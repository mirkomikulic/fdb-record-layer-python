"""Key expressions: describe how to extract index and primary keys from records.

The helper functions are re-exported here so that
``from fdb_record_layer.expressions import field, concat, nest, record_type``
returns the functions rather than the submodules of the same name.
"""

from fdb_record_layer.expressions.base import (
    EMPTY,
    FanType,
    KeyExpression,
    LiteralKeyExpression,
    empty,
    literal,
)
from fdb_record_layer.expressions.concat import ConcatenateKeyExpression, concat
from fdb_record_layer.expressions.field import FieldKeyExpression, field
from fdb_record_layer.expressions.nest import NestKeyExpression, nest
from fdb_record_layer.expressions.record_type import RecordTypeKeyExpression, record_type

__all__ = [
    "EMPTY",
    "ConcatenateKeyExpression",
    "FanType",
    "FieldKeyExpression",
    "KeyExpression",
    "LiteralKeyExpression",
    "NestKeyExpression",
    "RecordTypeKeyExpression",
    "concat",
    "empty",
    "field",
    "literal",
    "nest",
    "record_type",
]
