"""Tests for SQL parser."""

import pytest

from fdb_record_layer.relational.sql.ast import (
    AllColumns,
    BinaryExpression,
    ComparisonExpression,
    ComparisonOp,
    CreateTableStatement,
    DeleteStatement,
    InsertStatement,
    Literal,
    SelectItem,
    SelectStatement,
    UpdateStatement,
)
from fdb_record_layer.relational.sql.parser import (
    DEFAULT_MAX_RECURSION_DEPTH,
    DEFAULT_MAX_SQL_SIZE,
    InputTooLargeError,
    ParseError,
    Parser,
    RecursionLimitError,
    parse,
)


class TestParserConfiguration:
    """Tests for parser configuration."""

    def test_default_max_recursion_depth(self):
        """Test default max recursion depth."""
        assert DEFAULT_MAX_RECURSION_DEPTH == 100

    def test_default_max_sql_size(self):
        """Test default max SQL size."""
        assert DEFAULT_MAX_SQL_SIZE == 1_000_000

    def test_input_too_large_error(self):
        """Test InputTooLargeError is raised for large input."""
        large_sql = "x" * 100
        with pytest.raises(InputTooLargeError) as exc_info:
            Parser(large_sql, max_size=50)
        assert "100 bytes" in str(exc_info.value)
        assert "50 bytes" in str(exc_info.value)

    def test_recursion_limit_error(self):
        """Test RecursionLimitError on deeply nested expressions."""
        # Create deeply nested expression: ((((((1))))))
        nested = "(" * 50 + "1" + ")" * 50
        sql = f"SELECT {nested}"

        with pytest.raises(RecursionLimitError):
            Parser(sql, max_depth=10).parse()


class TestSelectStatement:
    """Tests for SELECT statement parsing."""

    def test_select_star(self):
        """Test SELECT * FROM table."""
        stmt = parse("SELECT * FROM users")
        assert isinstance(stmt, SelectStatement)
        assert len(stmt.select_items) == 1
        assert isinstance(stmt.select_items[0], AllColumns)

    def test_select_columns(self):
        """Test SELECT with specific columns."""
        stmt = parse("SELECT id, name, email FROM users")
        assert isinstance(stmt, SelectStatement)
        assert len(stmt.select_items) == 3

    def test_select_with_alias(self):
        """Test SELECT with column alias."""
        stmt = parse("SELECT id AS user_id FROM users")
        assert isinstance(stmt, SelectStatement)
        assert len(stmt.select_items) == 1
        item = stmt.select_items[0]
        assert isinstance(item, SelectItem)
        assert item.alias == "user_id"

    def test_select_table_star(self):
        """Test SELECT table.* FROM table."""
        stmt = parse("SELECT u.* FROM users u")
        assert isinstance(stmt, SelectStatement)
        item = stmt.select_items[0]
        assert isinstance(item, AllColumns)
        assert item.table == "u"

    def test_select_with_where(self):
        """Test SELECT with WHERE clause."""
        stmt = parse("SELECT * FROM users WHERE id = 1")
        assert isinstance(stmt, SelectStatement)
        assert stmt.where is not None
        assert isinstance(stmt.where, ComparisonExpression)

    def test_select_with_and(self):
        """Test SELECT with AND in WHERE."""
        stmt = parse("SELECT * FROM users WHERE age > 18 AND active = TRUE")
        assert isinstance(stmt, SelectStatement)
        assert stmt.where is not None

    def test_select_with_or(self):
        """Test SELECT with OR in WHERE."""
        stmt = parse("SELECT * FROM users WHERE status = 'active' OR status = 'pending'")
        assert isinstance(stmt, SelectStatement)
        assert stmt.where is not None

    def test_select_distinct(self):
        """Test SELECT DISTINCT."""
        stmt = parse("SELECT DISTINCT name FROM users")
        assert isinstance(stmt, SelectStatement)
        assert stmt.distinct is True

    def test_select_order_by(self):
        """Test SELECT with ORDER BY."""
        stmt = parse("SELECT * FROM users ORDER BY name")
        assert isinstance(stmt, SelectStatement)
        assert stmt.order_by is not None
        assert len(stmt.order_by) == 1

    def test_select_order_by_multiple(self):
        """Test SELECT with multiple ORDER BY columns."""
        stmt = parse("SELECT * FROM users ORDER BY last_name, first_name DESC")
        assert isinstance(stmt, SelectStatement)
        assert len(stmt.order_by) == 2

    def test_select_limit(self):
        """Test SELECT with LIMIT."""
        stmt = parse("SELECT * FROM users LIMIT 10")
        assert isinstance(stmt, SelectStatement)
        assert stmt.limit == 10

    def test_select_limit_offset(self):
        """Test SELECT with LIMIT and OFFSET."""
        stmt = parse("SELECT * FROM users LIMIT 10 OFFSET 20")
        assert isinstance(stmt, SelectStatement)
        assert stmt.limit == 10
        assert stmt.offset == 20

    def test_select_group_by(self):
        """Test SELECT with GROUP BY."""
        stmt = parse("SELECT status, COUNT(*) FROM users GROUP BY status")
        assert isinstance(stmt, SelectStatement)
        assert stmt.group_by is not None

    def test_select_having(self):
        """Test SELECT with HAVING."""
        stmt = parse("SELECT status, COUNT(*) FROM users GROUP BY status HAVING COUNT(*) > 5")
        assert isinstance(stmt, SelectStatement)
        assert stmt.having is not None

    def test_select_join(self):
        """Test SELECT with JOIN."""
        stmt = parse("SELECT * FROM users JOIN orders ON users.id = orders.user_id")
        assert isinstance(stmt, SelectStatement)
        assert stmt.from_clause is not None
        assert len(stmt.from_clause.joins) > 0

    def test_select_left_join(self):
        """Test SELECT with LEFT JOIN."""
        stmt = parse("SELECT * FROM users LEFT JOIN orders ON users.id = orders.user_id")
        assert isinstance(stmt, SelectStatement)

    def test_select_union(self):
        """Test SELECT with UNION."""
        stmt = parse("SELECT id FROM users UNION SELECT id FROM admins")
        assert isinstance(stmt, SelectStatement)
        assert stmt.set_operation is not None
        assert stmt.right_query is not None

    def test_select_subquery(self):
        """Test SELECT with subquery."""
        stmt = parse("SELECT * FROM (SELECT id FROM users) AS sub")
        assert isinstance(stmt, SelectStatement)


class TestInsertStatement:
    """Tests for INSERT statement parsing."""

    def test_insert_values(self):
        """Test INSERT with VALUES."""
        stmt = parse("INSERT INTO users (id, name) VALUES (1, 'John')")
        assert isinstance(stmt, InsertStatement)
        assert stmt.table.name == "users"
        assert len(stmt.columns) == 2
        assert len(stmt.values) == 1

    def test_insert_multiple_rows(self):
        """Test INSERT with multiple rows."""
        stmt = parse("INSERT INTO users (id, name) VALUES (1, 'John'), (2, 'Jane')")
        assert isinstance(stmt, InsertStatement)
        assert len(stmt.values) == 2

    def test_insert_without_columns(self):
        """Test INSERT without column list."""
        stmt = parse("INSERT INTO users VALUES (1, 'John', 'john@example.com')")
        assert isinstance(stmt, InsertStatement)
        assert stmt.columns is None or len(stmt.columns) == 0


class TestUpdateStatement:
    """Tests for UPDATE statement parsing."""

    def test_update_single_column(self):
        """Test UPDATE with single column."""
        stmt = parse("UPDATE users SET name = 'John' WHERE id = 1")
        assert isinstance(stmt, UpdateStatement)
        assert stmt.table.name == "users"
        assert len(stmt.set_clauses) == 1
        assert stmt.where is not None

    def test_update_multiple_columns(self):
        """Test UPDATE with multiple columns."""
        stmt = parse("UPDATE users SET name = 'John', age = 30 WHERE id = 1")
        assert isinstance(stmt, UpdateStatement)
        assert len(stmt.set_clauses) == 2

    def test_update_without_where(self):
        """Test UPDATE without WHERE clause."""
        stmt = parse("UPDATE users SET active = FALSE")
        assert isinstance(stmt, UpdateStatement)
        assert stmt.where is None


class TestDeleteStatement:
    """Tests for DELETE statement parsing."""

    def test_delete_with_where(self):
        """Test DELETE with WHERE."""
        stmt = parse("DELETE FROM users WHERE id = 1")
        assert isinstance(stmt, DeleteStatement)
        assert stmt.table.name == "users"
        assert stmt.where is not None

    def test_delete_without_where(self):
        """Test DELETE without WHERE."""
        stmt = parse("DELETE FROM users")
        assert isinstance(stmt, DeleteStatement)
        assert stmt.where is None


class TestCreateTableStatement:
    """Tests for CREATE TABLE statement parsing."""

    def test_create_table_simple(self):
        """Test simple CREATE TABLE."""
        stmt = parse("CREATE TABLE users (id BIGINT, name STRING)")
        assert isinstance(stmt, CreateTableStatement)
        assert stmt.name == "users"
        assert len(stmt.columns) == 2

    def test_create_table_with_primary_key(self):
        """Test CREATE TABLE with PRIMARY KEY."""
        stmt = parse("CREATE TABLE users (id BIGINT PRIMARY KEY, name STRING)")
        assert isinstance(stmt, CreateTableStatement)

    def test_create_table_if_not_exists(self):
        """Test CREATE TABLE IF NOT EXISTS."""
        stmt = parse("CREATE TABLE IF NOT EXISTS users (id BIGINT)")
        assert isinstance(stmt, CreateTableStatement)
        assert stmt.if_not_exists is True


class TestExpressions:
    """Tests for expression parsing."""

    def test_comparison_equals(self):
        """Test equals comparison."""
        stmt = parse("SELECT * FROM t WHERE a = 1")
        assert isinstance(stmt.where, ComparisonExpression)
        assert stmt.where.operator == ComparisonOp.EQ

    def test_comparison_not_equals(self):
        """Test not equals comparison."""
        stmt = parse("SELECT * FROM t WHERE a <> 1")
        assert isinstance(stmt.where, ComparisonExpression)
        assert stmt.where.operator == ComparisonOp.NE

    def test_comparison_less_than(self):
        """Test less than comparison."""
        stmt = parse("SELECT * FROM t WHERE a < 1")
        assert stmt.where.operator == ComparisonOp.LT

    def test_comparison_greater_than(self):
        """Test greater than comparison."""
        stmt = parse("SELECT * FROM t WHERE a > 1")
        assert stmt.where.operator == ComparisonOp.GT

    def test_in_expression(self):
        """Test IN expression."""
        stmt = parse("SELECT * FROM t WHERE a IN (1, 2, 3)")
        assert stmt.where is not None

    def test_between_expression(self):
        """Test BETWEEN expression."""
        stmt = parse("SELECT * FROM t WHERE a BETWEEN 1 AND 10")
        assert stmt.where is not None

    def test_like_expression(self):
        """Test LIKE expression."""
        stmt = parse("SELECT * FROM t WHERE name LIKE 'John%'")
        assert stmt.where is not None

    def test_is_null(self):
        """Test IS NULL expression."""
        stmt = parse("SELECT * FROM t WHERE a IS NULL")
        assert stmt.where is not None

    def test_is_not_null(self):
        """Test IS NOT NULL expression."""
        stmt = parse("SELECT * FROM t WHERE a IS NOT NULL")
        assert stmt.where is not None

    def test_arithmetic_expression(self):
        """Test arithmetic expression."""
        stmt = parse("SELECT a + b FROM t")
        item = stmt.select_items[0]
        assert isinstance(item, SelectItem)
        assert isinstance(item.expression, BinaryExpression)

    def test_function_call(self):
        """Test function call."""
        stmt = parse("SELECT COUNT(*) FROM t")
        assert len(stmt.select_items) == 1

    def test_case_expression(self):
        """Test CASE expression."""
        stmt = parse("SELECT CASE WHEN a = 1 THEN 'one' ELSE 'other' END FROM t")
        assert len(stmt.select_items) == 1


class TestLiterals:
    """Tests for literal parsing."""

    def test_integer_literal(self):
        """Test integer literal."""
        stmt = parse("SELECT 123 FROM t")
        item = stmt.select_items[0]
        assert isinstance(item, SelectItem)
        assert isinstance(item.expression, Literal)

    def test_float_literal(self):
        """Test float literal."""
        stmt = parse("SELECT 123.456 FROM t")
        item = stmt.select_items[0]
        assert isinstance(item.expression, Literal)

    def test_string_literal(self):
        """Test string literal."""
        stmt = parse("SELECT 'hello' FROM t")
        item = stmt.select_items[0]
        assert isinstance(item.expression, Literal)

    def test_null_literal(self):
        """Test NULL literal."""
        stmt = parse("SELECT NULL FROM t")
        item = stmt.select_items[0]
        assert isinstance(item.expression, Literal)

    def test_true_literal(self):
        """Test TRUE literal."""
        stmt = parse("SELECT TRUE FROM t")
        item = stmt.select_items[0]
        assert isinstance(item.expression, Literal)

    def test_false_literal(self):
        """Test FALSE literal."""
        stmt = parse("SELECT FALSE FROM t")
        item = stmt.select_items[0]
        assert isinstance(item.expression, Literal)


class TestParseErrors:
    """Tests for parse error handling."""

    def test_missing_from(self):
        """Test error on missing FROM."""
        with pytest.raises(ParseError):
            parse("SELECT * users")

    def test_incomplete_statement(self):
        """Test error on incomplete statement."""
        with pytest.raises(ParseError):
            parse("SELECT")

    def test_invalid_token(self):
        """Test error on invalid token."""
        with pytest.raises(ParseError):
            parse("SELECT @#$ FROM users")

    def test_error_includes_position(self):
        """Test error message includes position."""
        try:
            parse("SELECT * FROM")
        except ParseError as e:
            assert "line" in str(e).lower() or "column" in str(e).lower()


class TestParseFunction:
    """Tests for parse convenience function."""

    def test_parse_single_statement(self):
        """Test parse function with single statement."""
        stmt = parse("SELECT * FROM users")
        assert isinstance(stmt, SelectStatement)

    def test_parse_with_semicolon(self):
        """Test parse handles trailing semicolon."""
        stmt = parse("SELECT * FROM users;")
        assert isinstance(stmt, SelectStatement)
