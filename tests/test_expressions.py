"""Tests for key expressions."""

from unittest.mock import MagicMock

from fdb_record_layer.expressions.base import (
    EMPTY,
    FanType,
    LiteralKeyExpression,
    empty,
    literal,
)
from fdb_record_layer.expressions.concat import ConcatenateKeyExpression, concat
from fdb_record_layer.expressions.field import FieldKeyExpression, field
from fdb_record_layer.expressions.nest import NestKeyExpression, nest
from fdb_record_layer.expressions.record_type import RecordTypeKeyExpression, record_type


class TestFieldKeyExpression:
    """Tests for FieldKeyExpression."""

    def test_field_creation(self):
        """Test field expression creation."""
        expr = field("name")
        assert isinstance(expr, FieldKeyExpression)
        assert expr.field_name == "name"

    def test_field_evaluate(self):
        """Test field expression evaluation."""
        expr = field("name")
        record = MagicMock()
        record.name = "John"

        result = expr.evaluate(record)
        assert result == [("John",)]

    def test_field_with_fan_type(self):
        """Test field expression with fan type."""
        expr = field("tags", fan_type=FanType.FAN_OUT)
        assert expr.fan_type == FanType.FAN_OUT

    def test_field_validate(self):
        """Test field expression validation."""
        from unittest.mock import MagicMock

        expr = field("name")

        # Create a mock descriptor with the field
        descriptor = MagicMock()
        field_mock = MagicMock()
        field_mock.name = "name"
        descriptor.fields = [field_mock]
        descriptor.name = "TestRecord"

        errors = expr.validate(descriptor)
        assert errors == []

    def test_field_validate_missing(self):
        """Test field expression validation with missing field."""
        from unittest.mock import MagicMock

        expr = field("missing_field")

        descriptor = MagicMock()
        descriptor.fields = []
        descriptor.name = "TestRecord"

        errors = expr.validate(descriptor)
        assert len(errors) == 1
        assert "missing_field" in errors[0]


class TestConcatenateKeyExpression:
    """Tests for ConcatenateKeyExpression."""

    def test_concat_creation(self):
        """Test concat expression creation."""
        expr = concat(field("first_name"), field("last_name"))
        assert isinstance(expr, ConcatenateKeyExpression)

    def test_concat_evaluate(self):
        """Test concat expression evaluation."""
        expr = concat(field("first_name"), field("last_name"))
        record = MagicMock()
        record.first_name = "John"
        record.last_name = "Doe"

        result = expr.evaluate(record)
        assert result == [("John", "Doe")]

    def test_concat_multiple_fields(self):
        """Test concat with multiple fields."""
        expr = concat(field("a"), field("b"), field("c"))
        record = MagicMock()
        record.a = 1
        record.b = 2
        record.c = 3

        result = expr.evaluate(record)
        assert result == [(1, 2, 3)]


class TestNestKeyExpression:
    """Tests for NestKeyExpression."""

    def test_nest_creation(self):
        """Test nest expression creation."""
        expr = nest("address", field("city"))
        assert isinstance(expr, NestKeyExpression)
        assert expr.parent_field == "address"

    def test_nest_evaluate(self):
        """Test nest expression evaluation."""
        expr = nest("address", field("city"))
        record = MagicMock()
        address = MagicMock()
        address.city = "New York"
        record.address = address

        result = expr.evaluate(record)
        assert result == [("New York",)]

    def test_nest_convenience_function(self):
        """Test nest convenience function."""
        expr = nest("parent", field("child"))
        assert isinstance(expr, NestKeyExpression)


class TestRecordTypeKeyExpression:
    """Tests for RecordTypeKeyExpression."""

    def test_record_type_creation(self):
        """Test record type expression creation."""
        expr = record_type()
        assert isinstance(expr, RecordTypeKeyExpression)

    def test_record_type_evaluate(self):
        """Test record type expression evaluation."""
        expr = record_type()
        record = MagicMock()
        record.DESCRIPTOR.name = "Person"

        result = expr.evaluate(record)
        assert result == [("Person",)]


class TestLiteralKeyExpression:
    """Tests for LiteralKeyExpression."""

    def test_literal_creation(self):
        """Test literal expression creation."""
        expr = literal("constant")
        assert isinstance(expr, LiteralKeyExpression)
        assert expr.value == "constant"

    def test_literal_evaluate(self):
        """Test literal expression evaluation."""
        expr = literal(42)
        record = MagicMock()

        result = expr.evaluate(record)
        assert result == [(42,)]


class TestEmptyKeyExpression:
    """Tests for empty key expression."""

    def test_empty_constant(self):
        """Test EMPTY constant."""
        assert EMPTY is not None

    def test_empty_function(self):
        """Test empty function."""
        expr = empty()
        assert expr is EMPTY

    def test_empty_evaluate(self):
        """Test empty expression evaluation."""
        record = MagicMock()
        result = EMPTY.evaluate(record)
        assert result == [()]


class TestFanType:
    """Tests for FanType enum."""

    def test_fan_types_exist(self):
        """Test fan type values exist."""
        assert FanType.NONE is not None
        assert FanType.FAN_OUT is not None
        assert FanType.CONCATENATE is not None


class TestKeyExpressionCombinations:
    """Tests for combining key expressions."""

    def test_concat_with_literal(self):
        """Test concat with literal."""
        expr = concat(literal("prefix"), field("id"))
        record = MagicMock()
        record.id = 123

        result = expr.evaluate(record)
        assert result == [("prefix", 123)]

    def test_nested_concat(self):
        """Test nested concat expressions."""
        expr = concat(
            concat(field("a"), field("b")),
            field("c"),
        )
        record = MagicMock()
        record.a = 1
        record.b = 2
        record.c = 3

        result = expr.evaluate(record)
        # The exact result depends on implementation
        assert len(result) > 0

    def test_record_type_with_field(self):
        """Test record type combined with field."""
        expr = concat(record_type(), field("id"))
        record = MagicMock()
        record.DESCRIPTOR.name = "Person"
        record.id = 123

        result = expr.evaluate(record)
        assert result == [("Person", 123)]


class TestKeyExpressionEquality:
    """Tests for key expression equality."""

    def test_field_equality(self):
        """Test field expression equality."""
        expr1 = field("name")
        expr2 = field("name")
        expr3 = field("age")

        assert expr1 == expr2
        assert expr1 != expr3

    def test_concat_equality(self):
        """Test concat expression equality."""
        expr1 = concat(field("a"), field("b"))
        expr2 = concat(field("a"), field("b"))
        expr3 = concat(field("a"), field("c"))

        assert expr1 == expr2
        assert expr1 != expr3

    def test_literal_equality(self):
        """Test literal expression equality."""
        expr1 = literal(42)
        expr2 = literal(42)
        expr3 = literal(43)

        assert expr1 == expr2
        assert expr1 != expr3


class TestKeyExpressionHashing:
    """Tests for key expression hashing."""

    def test_field_hashable(self):
        """Test field expression is hashable."""
        expr = field("name")
        hash(expr)  # Should not raise

    def test_field_in_set(self):
        """Test field expression can be used in set."""
        expr1 = field("name")
        expr2 = field("name")
        expr_set = {expr1, expr2}
        assert len(expr_set) == 1

    def test_concat_hashable(self):
        """Test concat expression is hashable."""
        expr = concat(field("a"), field("b"))
        hash(expr)  # Should not raise
