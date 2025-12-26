"""SQL Type System.

Maps SQL types to Python types and handles type coercion.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from enum import Enum, auto
from typing import Any


class SQLTypeCategory(Enum):
    """Categories of SQL types."""

    BOOLEAN = auto()
    INTEGER = auto()
    FLOAT = auto()
    STRING = auto()
    BYTES = auto()
    TIMESTAMP = auto()
    ARRAY = auto()
    STRUCT = auto()
    MAP = auto()
    NULL = auto()


@dataclass
class SQLType(ABC):
    """Base class for SQL types."""

    @property
    @abstractmethod
    def category(self) -> SQLTypeCategory:
        """Get the type category."""
        ...

    @property
    @abstractmethod
    def name(self) -> str:
        """Get the type name."""
        ...

    @abstractmethod
    def is_compatible(self, other: SQLType) -> bool:
        """Check if another type is compatible (can be coerced)."""
        ...

    @abstractmethod
    def python_type(self) -> type:
        """Get the corresponding Python type."""
        ...

    def is_nullable(self) -> bool:
        """Check if this type is nullable."""
        return True

    def __str__(self) -> str:
        return self.name


@dataclass
class BooleanType(SQLType):
    """SQL BOOLEAN type."""

    @property
    def category(self) -> SQLTypeCategory:
        return SQLTypeCategory.BOOLEAN

    @property
    def name(self) -> str:
        return "BOOLEAN"

    def is_compatible(self, other: SQLType) -> bool:
        return isinstance(other, (BooleanType, NullType))

    def python_type(self) -> type:
        return bool


@dataclass
class IntegerType(SQLType):
    """SQL integer types (TINYINT, SMALLINT, INT, BIGINT)."""

    bits: int = 64  # 8, 16, 32, or 64

    @property
    def category(self) -> SQLTypeCategory:
        return SQLTypeCategory.INTEGER

    @property
    def name(self) -> str:
        if self.bits == 8:
            return "TINYINT"
        elif self.bits == 16:
            return "SMALLINT"
        elif self.bits == 32:
            return "INT"
        else:
            return "BIGINT"

    def is_compatible(self, other: SQLType) -> bool:
        if isinstance(other, NullType):
            return True
        if isinstance(other, IntegerType):
            return True  # All integers compatible
        if isinstance(other, FloatType):
            return True  # Integers can promote to float
        return False

    def python_type(self) -> type:
        return int


@dataclass
class FloatType(SQLType):
    """SQL floating-point types (FLOAT, DOUBLE)."""

    double_precision: bool = True

    @property
    def category(self) -> SQLTypeCategory:
        return SQLTypeCategory.FLOAT

    @property
    def name(self) -> str:
        return "DOUBLE" if self.double_precision else "FLOAT"

    def is_compatible(self, other: SQLType) -> bool:
        if isinstance(other, NullType):
            return True
        if isinstance(other, (IntegerType, FloatType)):
            return True
        return False

    def python_type(self) -> type:
        return float


@dataclass
class DecimalType(SQLType):
    """SQL DECIMAL type with precision and scale."""

    precision: int = 38
    scale: int = 0

    @property
    def category(self) -> SQLTypeCategory:
        return SQLTypeCategory.FLOAT

    @property
    def name(self) -> str:
        return f"DECIMAL({self.precision}, {self.scale})"

    def is_compatible(self, other: SQLType) -> bool:
        if isinstance(other, NullType):
            return True
        if isinstance(other, (IntegerType, FloatType, DecimalType)):
            return True
        return False

    def python_type(self) -> type:
        from decimal import Decimal

        return Decimal


@dataclass
class StringType(SQLType):
    """SQL string types (STRING, VARCHAR, CHAR)."""

    max_length: int | None = None  # None = unlimited

    @property
    def category(self) -> SQLTypeCategory:
        return SQLTypeCategory.STRING

    @property
    def name(self) -> str:
        if self.max_length is None:
            return "STRING"
        return f"VARCHAR({self.max_length})"

    def is_compatible(self, other: SQLType) -> bool:
        if isinstance(other, NullType):
            return True
        if isinstance(other, StringType):
            return True
        return False

    def python_type(self) -> type:
        return str


@dataclass
class BytesType(SQLType):
    """SQL BYTES type."""

    @property
    def category(self) -> SQLTypeCategory:
        return SQLTypeCategory.BYTES

    @property
    def name(self) -> str:
        return "BYTES"

    def is_compatible(self, other: SQLType) -> bool:
        return isinstance(other, (BytesType, NullType))

    def python_type(self) -> type:
        return bytes


@dataclass
class TimestampType(SQLType):
    """SQL TIMESTAMP type."""

    with_timezone: bool = False

    @property
    def category(self) -> SQLTypeCategory:
        return SQLTypeCategory.TIMESTAMP

    @property
    def name(self) -> str:
        return "TIMESTAMP"

    def is_compatible(self, other: SQLType) -> bool:
        if isinstance(other, NullType):
            return True
        if isinstance(other, TimestampType):
            return True
        if isinstance(other, IntegerType):
            return True  # Unix timestamp
        return False

    def python_type(self) -> type:
        from datetime import datetime

        return datetime


@dataclass
class DateType(SQLType):
    """SQL DATE type."""

    @property
    def category(self) -> SQLTypeCategory:
        return SQLTypeCategory.TIMESTAMP

    @property
    def name(self) -> str:
        return "DATE"

    def is_compatible(self, other: SQLType) -> bool:
        if isinstance(other, NullType):
            return True
        if isinstance(other, (DateType, TimestampType)):
            return True
        return False

    def python_type(self) -> type:
        from datetime import date

        return date


@dataclass
class TimeType(SQLType):
    """SQL TIME type."""

    @property
    def category(self) -> SQLTypeCategory:
        return SQLTypeCategory.TIMESTAMP

    @property
    def name(self) -> str:
        return "TIME"

    def is_compatible(self, other: SQLType) -> bool:
        return isinstance(other, (TimeType, NullType))

    def python_type(self) -> type:
        from datetime import time

        return time


@dataclass
class ArrayType(SQLType):
    """SQL ARRAY type."""

    element_type: SQLType = field(default_factory=lambda: StringType())

    @property
    def category(self) -> SQLTypeCategory:
        return SQLTypeCategory.ARRAY

    @property
    def name(self) -> str:
        return f"ARRAY<{self.element_type.name}>"

    def is_compatible(self, other: SQLType) -> bool:
        if isinstance(other, NullType):
            return True
        if isinstance(other, ArrayType):
            return self.element_type.is_compatible(other.element_type)
        return False

    def python_type(self) -> type:
        return list


@dataclass
class StructField:
    """A field in a STRUCT type."""

    name: str
    field_type: SQLType


@dataclass
class StructType(SQLType):
    """SQL STRUCT type (nested record)."""

    fields: list[StructField] = field(default_factory=list)

    @property
    def category(self) -> SQLTypeCategory:
        return SQLTypeCategory.STRUCT

    @property
    def name(self) -> str:
        field_strs = [f"{f.name}: {f.field_type.name}" for f in self.fields]
        return f"STRUCT<{', '.join(field_strs)}>"

    def is_compatible(self, other: SQLType) -> bool:
        if isinstance(other, NullType):
            return True
        if isinstance(other, StructType):
            if len(self.fields) != len(other.fields):
                return False
            for f1, f2 in zip(self.fields, other.fields):
                if not f1.field_type.is_compatible(f2.field_type):
                    return False
            return True
        return False

    def python_type(self) -> type:
        return dict

    def get_field(self, name: str) -> StructField | None:
        """Get a field by name."""
        for f in self.fields:
            if f.name.lower() == name.lower():
                return f
        return None


@dataclass
class MapType(SQLType):
    """SQL MAP type."""

    key_type: SQLType = field(default_factory=lambda: StringType())
    value_type: SQLType = field(default_factory=lambda: StringType())

    @property
    def category(self) -> SQLTypeCategory:
        return SQLTypeCategory.MAP

    @property
    def name(self) -> str:
        return f"MAP<{self.key_type.name}, {self.value_type.name}>"

    def is_compatible(self, other: SQLType) -> bool:
        if isinstance(other, NullType):
            return True
        if isinstance(other, MapType):
            return self.key_type.is_compatible(other.key_type) and self.value_type.is_compatible(
                other.value_type
            )
        return False

    def python_type(self) -> type:
        return dict


@dataclass
class NullType(SQLType):
    """SQL NULL type."""

    @property
    def category(self) -> SQLTypeCategory:
        return SQLTypeCategory.NULL

    @property
    def name(self) -> str:
        return "NULL"

    def is_compatible(self, other: SQLType) -> bool:
        return True  # NULL is compatible with everything

    def python_type(self) -> type:
        return type(None)


# Type singletons for convenience
BOOLEAN = BooleanType()
TINYINT = IntegerType(bits=8)
SMALLINT = IntegerType(bits=16)
INT = IntegerType(bits=32)
BIGINT = IntegerType(bits=64)
FLOAT = FloatType(double_precision=False)
DOUBLE = FloatType(double_precision=True)
STRING = StringType()
BYTES = BytesType()
TIMESTAMP = TimestampType()
DATE = DateType()
TIME = TimeType()
NULL = NullType()


def infer_type(value: Any) -> SQLType:
    """Infer the SQL type of a Python value."""
    if value is None:
        return NULL
    if isinstance(value, bool):
        return BOOLEAN
    if isinstance(value, int):
        if -128 <= value <= 127:
            return TINYINT
        elif -32768 <= value <= 32767:
            return SMALLINT
        elif -2147483648 <= value <= 2147483647:
            return INT
        else:
            return BIGINT
    if isinstance(value, float):
        return DOUBLE
    if isinstance(value, str):
        return STRING
    if isinstance(value, bytes):
        return BYTES
    if isinstance(value, list):
        if len(value) == 0:
            return ArrayType(STRING)
        elem_type = infer_type(value[0])
        return ArrayType(elem_type)
    if isinstance(value, dict):
        return StructType()

    # Try datetime types
    try:
        from datetime import date, datetime
        from datetime import time as time_type

        if isinstance(value, datetime):
            return TIMESTAMP
        if isinstance(value, date):
            return DATE
        if isinstance(value, time_type):
            return TIME
    except ImportError:
        pass

    return STRING  # Default fallback


def common_type(type1: SQLType, type2: SQLType) -> SQLType | None:
    """Find the common supertype of two types for coercion."""
    if isinstance(type1, NullType):
        return type2
    if isinstance(type2, NullType):
        return type1

    if type(type1) is type(type2):
        return type1

    # Numeric promotion
    if isinstance(type1, (IntegerType, FloatType, DecimalType)) and isinstance(
        type2, (IntegerType, FloatType, DecimalType)
    ):
        if isinstance(type1, DecimalType) or isinstance(type2, DecimalType):
            return DecimalType()
        if isinstance(type1, FloatType) or isinstance(type2, FloatType):
            return DOUBLE
        # Both integers - use the wider one
        if isinstance(type1, IntegerType) and isinstance(type2, IntegerType):
            return IntegerType(bits=max(type1.bits, type2.bits))

    # String coercion for comparison
    if isinstance(type1, StringType) and isinstance(type2, StringType):
        return STRING

    return None


def coerce_value(value: Any, target_type: SQLType) -> Any:
    """Coerce a value to the target SQL type."""
    if value is None:
        return None

    source_type = infer_type(value)
    if type(source_type) is type(target_type):
        return value

    # Numeric coercion
    if isinstance(target_type, IntegerType):
        if isinstance(value, (int, float, str)):
            return int(value)

    if isinstance(target_type, FloatType):
        if isinstance(value, (int, float, str)):
            return float(value)

    if isinstance(target_type, BooleanType):
        if isinstance(value, bool):
            return value
        if isinstance(value, (int, float)):
            return bool(value)
        if isinstance(value, str):
            return value.lower() in ("true", "1", "yes")

    if isinstance(target_type, StringType):
        return str(value)

    if isinstance(target_type, BytesType):
        if isinstance(value, bytes):
            return value
        if isinstance(value, str):
            return value.encode("utf-8")

    # Return as-is if no coercion possible
    return value


class TypeChecker:
    """Type checker for SQL expressions."""

    def __init__(self) -> None:
        self._errors: list[str] = []
        self._column_types: dict[str, SQLType] = {}

    def set_column_type(self, name: str, sql_type: SQLType) -> None:
        """Register a column's type."""
        self._column_types[name.lower()] = sql_type

    def get_column_type(self, name: str) -> SQLType | None:
        """Get a column's type."""
        return self._column_types.get(name.lower())

    def check_binary_op(
        self, left: SQLType, right: SQLType, operator: str
    ) -> tuple[SQLType | None, str | None]:
        """Check a binary operation and return result type."""
        # Comparison operators
        if operator in ("=", "!=", "<>", "<", "<=", ">", ">="):
            if left.is_compatible(right) or right.is_compatible(left):
                return BOOLEAN, None
            return None, f"Cannot compare {left} with {right}"

        # Arithmetic operators
        if operator in ("+", "-", "*", "/"):
            result = common_type(left, right)
            if result is not None and isinstance(result, (IntegerType, FloatType, DecimalType)):
                if operator == "/" and isinstance(result, IntegerType):
                    return DOUBLE, None
                return result, None
            return None, f"Cannot apply {operator} to {left} and {right}"

        # String concatenation
        if operator == "||":
            if isinstance(left, StringType) and isinstance(right, StringType):
                return STRING, None
            return None, f"Concatenation requires STRING types, got {left} and {right}"

        # Logical operators
        if operator.upper() in ("AND", "OR"):
            if isinstance(left, BooleanType) and isinstance(right, BooleanType):
                return BOOLEAN, None
            return None, f"{operator} requires BOOLEAN operands"

        return None, f"Unknown operator: {operator}"

    def check_function(
        self, name: str, arg_types: list[SQLType]
    ) -> tuple[SQLType | None, str | None]:
        """Check a function call and return result type."""
        name_upper = name.upper()

        # Aggregate functions
        if name_upper == "COUNT":
            return BIGINT, None

        if name_upper in ("SUM", "AVG"):
            if len(arg_types) != 1:
                return None, f"{name_upper} requires exactly one argument"
            if not isinstance(arg_types[0], (IntegerType, FloatType, DecimalType, NullType)):
                return None, f"{name_upper} requires a numeric argument"
            if name_upper == "AVG":
                return DOUBLE, None
            return arg_types[0], None

        if name_upper in ("MIN", "MAX"):
            if len(arg_types) != 1:
                return None, f"{name_upper} requires exactly one argument"
            return arg_types[0], None

        # String functions
        if name_upper == "LENGTH":
            if len(arg_types) != 1:
                return None, "LENGTH requires exactly one argument"
            if not isinstance(arg_types[0], (StringType, NullType)):
                return None, "LENGTH requires a STRING argument"
            return BIGINT, None

        if name_upper in ("UPPER", "LOWER", "TRIM", "LTRIM", "RTRIM"):
            if len(arg_types) != 1:
                return None, f"{name_upper} requires exactly one argument"
            if not isinstance(arg_types[0], (StringType, NullType)):
                return None, f"{name_upper} requires a STRING argument"
            return STRING, None

        if name_upper == "CONCAT":
            for t in arg_types:
                if not isinstance(t, (StringType, NullType)):
                    return None, "CONCAT requires STRING arguments"
            return STRING, None

        if name_upper == "SUBSTRING":
            if len(arg_types) < 2 or len(arg_types) > 3:
                return None, "SUBSTRING requires 2 or 3 arguments"
            if not isinstance(arg_types[0], (StringType, NullType)):
                return None, "SUBSTRING first argument must be STRING"
            return STRING, None

        # Type conversion
        if name_upper == "CAST":
            # CAST returns the target type, handled specially
            return None, None

        # Coalesce
        if name_upper == "COALESCE":
            if len(arg_types) == 0:
                return None, "COALESCE requires at least one argument"
            result_type = arg_types[0]
            for t in arg_types[1:]:
                result_type = common_type(result_type, t) or result_type
            return result_type, None

        # Unknown function - assume it returns STRING
        return STRING, None

    @property
    def errors(self) -> list[str]:
        """Get accumulated errors."""
        return self._errors

    def add_error(self, message: str) -> None:
        """Add an error."""
        self._errors.append(message)

    def clear_errors(self) -> None:
        """Clear errors."""
        self._errors = []
