"""Tests for query components."""

from unittest.mock import MagicMock

from fdb_record_layer.query.comparisons import Comparison, ComparisonType
from fdb_record_layer.query.components import (
    AndComponent,
    FieldComponent,
    NotComponent,
    OrComponent,
    QueryComponent,
)
from fdb_record_layer.query.predicates import Field
from fdb_record_layer.query.query import (
    Query,
    RecordQuery,
    RecordQueryBuilder,
)


class TestComparisonType:
    """Tests for ComparisonType enum."""

    def test_comparison_types_exist(self):
        """Test comparison type values exist."""
        assert ComparisonType.EQUALS is not None
        assert ComparisonType.NOT_EQUALS is not None
        assert ComparisonType.LESS_THAN is not None
        assert ComparisonType.LESS_THAN_OR_EQUALS is not None
        assert ComparisonType.GREATER_THAN is not None
        assert ComparisonType.GREATER_THAN_OR_EQUALS is not None
        assert ComparisonType.IN is not None
        assert ComparisonType.STARTS_WITH is not None

    def test_is_equality(self):
        """Test is_equality property."""
        assert ComparisonType.EQUALS.is_equality is True
        assert ComparisonType.IS_NULL.is_equality is True
        assert ComparisonType.GREATER_THAN.is_equality is False

    def test_is_inequality(self):
        """Test is_inequality property."""
        assert ComparisonType.LESS_THAN.is_inequality is True
        assert ComparisonType.GREATER_THAN.is_inequality is True
        assert ComparisonType.EQUALS.is_inequality is False

    def test_can_use_index(self):
        """Test can_use_index property."""
        assert ComparisonType.EQUALS.can_use_index is True
        assert ComparisonType.IN.can_use_index is True
        assert ComparisonType.CONTAINS.can_use_index is False


class TestComparison:
    """Tests for Comparison class."""

    def test_equals_comparison(self):
        """Test equals comparison."""
        comp = Comparison(ComparisonType.EQUALS, 42)
        assert comp.comparison_type == ComparisonType.EQUALS
        assert comp.value == 42

    def test_in_comparison(self):
        """Test IN comparison."""
        comp = Comparison(ComparisonType.IN, [1, 2, 3])
        assert comp.comparison_type == ComparisonType.IN
        assert comp.value == [1, 2, 3]

    def test_comparison_evaluate_equals(self):
        """Test equals comparison evaluation."""
        comp = Comparison(ComparisonType.EQUALS, 42)
        assert comp.evaluate(42) is True
        assert comp.evaluate(43) is False

    def test_comparison_evaluate_not_equals(self):
        """Test not equals comparison evaluation."""
        comp = Comparison(ComparisonType.NOT_EQUALS, 42)
        assert comp.evaluate(42) is False
        assert comp.evaluate(43) is True

    def test_comparison_evaluate_less_than(self):
        """Test less than comparison evaluation."""
        comp = Comparison(ComparisonType.LESS_THAN, 10)
        assert comp.evaluate(5) is True
        assert comp.evaluate(10) is False
        assert comp.evaluate(15) is False

    def test_comparison_evaluate_greater_than(self):
        """Test greater than comparison evaluation."""
        comp = Comparison(ComparisonType.GREATER_THAN, 10)
        assert comp.evaluate(5) is False
        assert comp.evaluate(10) is False
        assert comp.evaluate(15) is True

    def test_comparison_evaluate_in(self):
        """Test IN comparison evaluation."""
        comp = Comparison(ComparisonType.IN, [1, 2, 3])
        assert comp.evaluate(1) is True
        assert comp.evaluate(2) is True
        assert comp.evaluate(4) is False

    def test_comparison_evaluate_starts_with(self):
        """Test STARTS_WITH comparison evaluation."""
        comp = Comparison(ComparisonType.STARTS_WITH, "hello")
        assert comp.evaluate("hello world") is True
        assert comp.evaluate("world hello") is False

    def test_comparison_is_null(self):
        """Test IS_NULL comparison."""
        comp = Comparison(ComparisonType.IS_NULL)
        assert comp.evaluate(None) is True
        assert comp.evaluate("value") is False

    def test_comparison_is_not_null(self):
        """Test IS_NOT_NULL comparison."""
        comp = Comparison(ComparisonType.IS_NOT_NULL)
        assert comp.evaluate(None) is False
        assert comp.evaluate("value") is True

    def test_parameterized_comparison(self):
        """Test parameterized comparison."""
        comp = Comparison(ComparisonType.EQUALS, parameter_name="user_id")
        assert comp.is_parameterized is True
        assert comp.parameter_name == "user_id"

        # Evaluate with bindings
        assert comp.evaluate(42, {"user_id": 42}) is True
        assert comp.evaluate(42, {"user_id": 99}) is False


class TestFieldComponent:
    """Tests for FieldComponent."""

    def test_field_component_creation(self):
        """Test field component creation."""
        comp = FieldComponent("name", Comparison(ComparisonType.EQUALS, "John"))
        assert comp.field_name == "name"

    def test_field_component_evaluate(self):
        """Test field component evaluation."""
        comp = FieldComponent("name", Comparison(ComparisonType.EQUALS, "John"))
        record = MagicMock()
        record.name = "John"

        assert comp.evaluate(record) is True

    def test_field_component_evaluate_false(self):
        """Test field component evaluation returns false."""
        comp = FieldComponent("name", Comparison(ComparisonType.EQUALS, "John"))
        record = MagicMock()
        record.name = "Jane"

        assert comp.evaluate(record) is False


class TestAndComponent:
    """Tests for AndComponent."""

    def test_and_component_creation(self):
        """Test AND component creation."""
        comp1 = FieldComponent("age", Comparison(ComparisonType.GREATER_THAN, 18))
        comp2 = FieldComponent("active", Comparison(ComparisonType.EQUALS, True))
        and_comp = AndComponent([comp1, comp2])

        assert len(and_comp.children) == 2

    def test_and_component_evaluate_all_true(self):
        """Test AND returns true when all children true."""
        comp1 = FieldComponent("age", Comparison(ComparisonType.GREATER_THAN, 18))
        comp2 = FieldComponent("active", Comparison(ComparisonType.EQUALS, True))
        and_comp = AndComponent([comp1, comp2])

        record = MagicMock()
        record.age = 25
        record.active = True

        assert and_comp.evaluate(record) is True

    def test_and_component_evaluate_one_false(self):
        """Test AND returns false when one child false."""
        comp1 = FieldComponent("age", Comparison(ComparisonType.GREATER_THAN, 18))
        comp2 = FieldComponent("active", Comparison(ComparisonType.EQUALS, True))
        and_comp = AndComponent([comp1, comp2])

        record = MagicMock()
        record.age = 15  # False
        record.active = True

        assert and_comp.evaluate(record) is False


class TestOrComponent:
    """Tests for OrComponent."""

    def test_or_component_creation(self):
        """Test OR component creation."""
        comp1 = FieldComponent("status", Comparison(ComparisonType.EQUALS, "active"))
        comp2 = FieldComponent("status", Comparison(ComparisonType.EQUALS, "pending"))
        or_comp = OrComponent([comp1, comp2])

        assert len(or_comp.children) == 2

    def test_or_component_evaluate_one_true(self):
        """Test OR returns true when one child true."""
        comp1 = FieldComponent("status", Comparison(ComparisonType.EQUALS, "active"))
        comp2 = FieldComponent("status", Comparison(ComparisonType.EQUALS, "pending"))
        or_comp = OrComponent([comp1, comp2])

        record = MagicMock()
        record.status = "active"

        assert or_comp.evaluate(record) is True

    def test_or_component_evaluate_all_false(self):
        """Test OR returns false when all children false."""
        comp1 = FieldComponent("status", Comparison(ComparisonType.EQUALS, "active"))
        comp2 = FieldComponent("status", Comparison(ComparisonType.EQUALS, "pending"))
        or_comp = OrComponent([comp1, comp2])

        record = MagicMock()
        record.status = "inactive"

        assert or_comp.evaluate(record) is False


class TestNotComponent:
    """Tests for NotComponent."""

    def test_not_component_creation(self):
        """Test NOT component creation."""
        inner = FieldComponent("active", Comparison(ComparisonType.EQUALS, True))
        not_comp = NotComponent(inner)

        assert not_comp.child == inner

    def test_not_component_evaluate(self):
        """Test NOT component evaluation."""
        inner = FieldComponent("active", Comparison(ComparisonType.EQUALS, True))
        not_comp = NotComponent(inner)

        record = MagicMock()
        record.active = True

        assert not_comp.evaluate(record) is False

    def test_not_component_evaluate_negation(self):
        """Test NOT component negation."""
        inner = FieldComponent("active", Comparison(ComparisonType.EQUALS, True))
        not_comp = NotComponent(inner)

        record = MagicMock()
        record.active = False

        assert not_comp.evaluate(record) is True


class TestField:
    """Tests for Field predicate builder."""

    def test_field_equals(self):
        """Test Field.equals()."""
        pred = Field("name").equals("John")
        assert isinstance(pred, FieldComponent)

    def test_field_not_equals(self):
        """Test Field.not_equals()."""
        pred = Field("name").not_equals("John")
        assert isinstance(pred, FieldComponent)

    def test_field_less_than(self):
        """Test Field.less_than()."""
        pred = Field("age").less_than(18)
        assert isinstance(pred, FieldComponent)

    def test_field_greater_than(self):
        """Test Field.greater_than()."""
        pred = Field("age").greater_than(18)
        assert isinstance(pred, FieldComponent)

    def test_field_in_values(self):
        """Test Field.in_values()."""
        pred = Field("status").in_values(["active", "pending"])
        assert isinstance(pred, FieldComponent)

    def test_field_starts_with(self):
        """Test Field.starts_with()."""
        pred = Field("name").starts_with("John")
        assert isinstance(pred, FieldComponent)

    def test_field_is_null(self):
        """Test Field.is_null()."""
        pred = Field("email").is_null()
        assert isinstance(pred, FieldComponent)

    def test_field_is_not_null(self):
        """Test Field.is_not_null()."""
        pred = Field("email").is_not_null()
        assert isinstance(pred, FieldComponent)

    def test_field_between(self):
        """Test Field.between()."""
        pred = Field("age").between(18, 65)
        assert isinstance(pred, QueryComponent)


class TestRecordQuery:
    """Tests for RecordQuery."""

    def test_record_query_creation(self):
        """Test RecordQuery creation."""
        filter_comp = FieldComponent("name", Comparison(ComparisonType.EQUALS, "John"))
        query = RecordQuery(
            record_types=["Person"],
            filter=filter_comp,
        )
        assert query.record_types == ["Person"]
        assert query.filter == filter_comp

    def test_record_query_default_values(self):
        """Test RecordQuery default values."""
        query = RecordQuery()
        assert query.record_types == []
        assert query.filter is None
        assert query.sort is None
        assert query.removes_duplicates is False

    def test_record_query_get_filter(self):
        """Test get_filter method."""
        filter_comp = FieldComponent("name", Comparison(ComparisonType.EQUALS, "John"))
        query = RecordQuery(filter=filter_comp)
        assert query.get_filter() == filter_comp

    def test_record_query_get_record_types(self):
        """Test get_record_types method."""
        query = RecordQuery(record_types=["Person", "Employee"])
        assert query.get_record_types() == ["Person", "Employee"]

    def test_record_query_has_record_type_filter(self):
        """Test has_record_type_filter method."""
        query = RecordQuery(record_types=["Person"])
        assert query.has_record_type_filter() is True

        empty_query = RecordQuery()
        assert empty_query.has_record_type_filter() is False


class TestQueryBuilder:
    """Tests for QueryBuilder."""

    def test_query_builder_basic(self):
        """Test basic query building."""
        query = Query.from_type("Person").where(Field("name").equals("John")).build()
        assert isinstance(query, RecordQuery)
        assert "Person" in query.record_types

    def test_query_builder_with_and(self):
        """Test query builder with AND using Query.and_()."""
        query = (
            Query.from_type("Person")
            .where(Query.and_(Field("age").greater_than(18), Field("active").equals(True)))
            .build()
        )
        assert isinstance(query, RecordQuery)
        assert isinstance(query.filter, AndComponent)

    def test_query_builder_with_or(self):
        """Test query builder with OR using Query.or_()."""
        query = (
            Query.from_type("Person")
            .where(Query.or_(Field("status").equals("active"), Field("status").equals("pending")))
            .build()
        )
        assert isinstance(query, RecordQuery)
        assert isinstance(query.filter, OrComponent)

    def test_query_builder_multiple_types(self):
        """Test query builder with multiple record types."""
        query = Query.from_types("Person", "Employee").where(Field("active").equals(True)).build()
        assert len(query.record_types) == 2
        assert "Person" in query.record_types
        assert "Employee" in query.record_types

    def test_query_builder_distinct(self):
        """Test query builder with distinct."""
        query = Query.from_type("Person").where(Field("active").equals(True)).distinct().build()
        assert query.removes_duplicates is True


class TestRecordQueryBuilder:
    """Tests for RecordQueryBuilder."""

    def test_record_query_builder(self):
        """Test RecordQueryBuilder."""
        builder = RecordQueryBuilder()
        builder.set_record_type("Person")
        builder.set_filter(Field("name").equals("John"))
        query = builder.build()

        assert isinstance(query, RecordQuery)
        assert "Person" in query.record_types

    def test_record_query_builder_multiple_types(self):
        """Test RecordQueryBuilder with multiple types."""
        builder = RecordQueryBuilder()
        builder.set_record_types("Person", "Employee")
        query = builder.build()

        assert len(query.record_types) == 2

    def test_record_query_builder_removes_duplicates(self):
        """Test RecordQueryBuilder removes duplicates."""
        builder = RecordQueryBuilder()
        builder.set_record_type("Person")
        builder.set_removes_duplicates(True)
        query = builder.build()

        assert query.removes_duplicates is True


class TestComplexQueries:
    """Tests for complex query combinations."""

    def test_nested_and_or(self):
        """Test nested AND/OR queries."""
        query = (
            Query.from_type("Person")
            .where(
                AndComponent(
                    [
                        FieldComponent("active", Comparison(ComparisonType.EQUALS, True)),
                        OrComponent(
                            [
                                FieldComponent("role", Comparison(ComparisonType.EQUALS, "admin")),
                                FieldComponent(
                                    "role", Comparison(ComparisonType.EQUALS, "moderator")
                                ),
                            ]
                        ),
                    ]
                )
            )
            .build()
        )
        assert isinstance(query, RecordQuery)

    def test_not_with_and(self):
        """Test NOT with AND."""
        inner = AndComponent(
            [
                FieldComponent("deleted", Comparison(ComparisonType.EQUALS, True)),
                FieldComponent("archived", Comparison(ComparisonType.EQUALS, True)),
            ]
        )
        not_comp = NotComponent(inner)

        query = Query.from_type("Document").where(not_comp).build()
        assert isinstance(query.filter, NotComponent)

    def test_chained_where_creates_and(self):
        """Test that chaining where() creates AND."""
        query = (
            Query.from_type("Person")
            .where(Field("age").greater_than(18))
            .where(Field("active").equals(True))
            .build()
        )
        # Chained where() should AND the filters
        assert isinstance(query.filter, AndComponent)
