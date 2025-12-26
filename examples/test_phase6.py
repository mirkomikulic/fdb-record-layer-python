#!/usr/bin/env python3
"""Phase 6 Test - Relational Layer (SQL Support)

Tests:
- SQL Lexer/Tokenizer
- SQL Parser
- SQL Type System
- SQL to RecordQuery Translation
- Schema and Table definitions
- RelationalDatabase with in-memory storage

This test can run without FDB installed.
"""

import os
import sys
import importlib.util

# Add the parent directory to the path
parent_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, parent_dir)


def import_module_directly(module_path: str, module_name: str):
    """Import a module directly without going through package __init__.py."""
    spec = importlib.util.spec_from_file_location(module_name, module_path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[module_name] = module
    spec.loader.exec_module(module)
    return module


# Pre-import modules to avoid fdb_record_layer.__init__.py
frl_base = os.path.join(parent_dir, "fdb_record_layer")
relational_base = os.path.join(frl_base, "relational")
sql_base = os.path.join(relational_base, "sql")

# Import SQL modules
import_module_directly(
    os.path.join(sql_base, "ast.py"),
    "fdb_record_layer.relational.sql.ast"
)
import_module_directly(
    os.path.join(sql_base, "lexer.py"),
    "fdb_record_layer.relational.sql.lexer"
)
import_module_directly(
    os.path.join(sql_base, "parser.py"),
    "fdb_record_layer.relational.sql.parser"
)
import_module_directly(
    os.path.join(sql_base, "types.py"),
    "fdb_record_layer.relational.sql.types"
)

# Import query components (needed for translator)
query_base = os.path.join(frl_base, "query")
import_module_directly(
    os.path.join(query_base, "comparisons.py"),
    "fdb_record_layer.query.comparisons"
)
import_module_directly(
    os.path.join(query_base, "components.py"),
    "fdb_record_layer.query.components"
)
import_module_directly(
    os.path.join(query_base, "predicates.py"),
    "fdb_record_layer.query.predicates"
)
import_module_directly(
    os.path.join(query_base, "query.py"),
    "fdb_record_layer.query.query"
)

# Import expressions
expressions_base = os.path.join(frl_base, "expressions")
import_module_directly(
    os.path.join(expressions_base, "base.py"),
    "fdb_record_layer.expressions.base"
)
import_module_directly(
    os.path.join(expressions_base, "field.py"),
    "fdb_record_layer.expressions.field"
)

# Import translator and other relational modules
import_module_directly(
    os.path.join(sql_base, "translator.py"),
    "fdb_record_layer.relational.sql.translator"
)
import_module_directly(
    os.path.join(relational_base, "result_set.py"),
    "fdb_record_layer.relational.result_set"
)
import_module_directly(
    os.path.join(relational_base, "schema.py"),
    "fdb_record_layer.relational.schema"
)
import_module_directly(
    os.path.join(relational_base, "database.py"),
    "fdb_record_layer.relational.database"
)


def test_lexer():
    """Test 1: SQL Lexer."""
    print("\n1. Testing SQL Lexer...")

    from fdb_record_layer.relational.sql.lexer import tokenize, TokenType

    # Simple SELECT
    tokens = tokenize("SELECT * FROM users")
    token_types = [t.type for t in tokens]
    assert TokenType.SELECT in token_types
    assert TokenType.STAR in token_types
    assert TokenType.FROM in token_types
    assert TokenType.IDENTIFIER in token_types
    assert TokenType.EOF in token_types
    print("   Simple SELECT tokenized: OK")

    # SELECT with WHERE
    tokens = tokenize("SELECT id, name FROM users WHERE age > 21")
    token_types = [t.type for t in tokens]
    assert TokenType.WHERE in token_types
    assert TokenType.GT in token_types
    assert TokenType.INTEGER in token_types
    print("   SELECT with WHERE tokenized: OK")

    # String literals
    tokens = tokenize("SELECT * FROM users WHERE name = 'Alice'")
    token_types = [t.type for t in tokens]
    assert TokenType.STRING in token_types
    string_tokens = [t for t in tokens if t.type == TokenType.STRING]
    assert string_tokens[0].value == "Alice"
    print("   String literals tokenized: OK")

    # INSERT
    tokens = tokenize("INSERT INTO users (id, name) VALUES (1, 'Bob')")
    token_types = [t.type for t in tokens]
    assert TokenType.INSERT in token_types
    assert TokenType.INTO in token_types
    assert TokenType.VALUES in token_types
    print("   INSERT tokenized: OK")

    print("   SQL Lexer working!")


def test_parser():
    """Test 2: SQL Parser."""
    print("\n2. Testing SQL Parser...")

    from fdb_record_layer.relational.sql.parser import parse
    from fdb_record_layer.relational.sql.ast import (
        AllColumns,
        SelectStatement,
        InsertStatement,
        UpdateStatement,
        DeleteStatement,
        CreateTableStatement,
        ComparisonExpression,
        ColumnReference,
        Literal,
        SortOrder,
    )

    # Simple SELECT
    stmt = parse("SELECT * FROM users")
    assert isinstance(stmt, SelectStatement)
    assert len(stmt.select_items) == 1
    assert isinstance(stmt.select_items[0], AllColumns)
    assert stmt.from_clause is not None
    assert stmt.from_clause.source.name == "users"
    print("   Simple SELECT parsed: OK")

    # SELECT with columns
    stmt = parse("SELECT id, name, email FROM users")
    assert len(stmt.select_items) == 3
    print("   SELECT with columns parsed: OK")

    # SELECT with WHERE
    stmt = parse("SELECT * FROM users WHERE age > 21")
    assert stmt.where is not None
    assert isinstance(stmt.where, ComparisonExpression)
    print("   SELECT with WHERE parsed: OK")

    # SELECT with ORDER BY
    stmt = parse("SELECT * FROM users ORDER BY name ASC, age DESC")
    assert stmt.order_by is not None
    assert len(stmt.order_by) == 2
    assert stmt.order_by[0].order == SortOrder.ASC
    assert stmt.order_by[1].order == SortOrder.DESC
    print("   SELECT with ORDER BY parsed: OK")

    # SELECT with LIMIT
    stmt = parse("SELECT * FROM users LIMIT 10 OFFSET 5")
    assert stmt.limit == 10
    assert stmt.offset == 5
    print("   SELECT with LIMIT/OFFSET parsed: OK")

    # INSERT
    stmt = parse("INSERT INTO users (id, name) VALUES (1, 'Alice')")
    assert isinstance(stmt, InsertStatement)
    assert stmt.table.name == "users"
    assert stmt.columns == ["id", "name"]
    assert len(stmt.values) == 1
    print("   INSERT parsed: OK")

    # UPDATE
    stmt = parse("UPDATE users SET name = 'Bob' WHERE id = 1")
    assert isinstance(stmt, UpdateStatement)
    assert stmt.table.name == "users"
    assert len(stmt.set_clauses) == 1
    assert stmt.where is not None
    print("   UPDATE parsed: OK")

    # DELETE
    stmt = parse("DELETE FROM users WHERE id = 1")
    assert isinstance(stmt, DeleteStatement)
    assert stmt.table.name == "users"
    assert stmt.where is not None
    print("   DELETE parsed: OK")

    # CREATE TABLE
    stmt = parse("""
        CREATE TABLE users (
            id BIGINT PRIMARY KEY,
            name VARCHAR(100) NOT NULL,
            email STRING,
            age INT DEFAULT 0
        )
    """)
    assert isinstance(stmt, CreateTableStatement)
    assert stmt.name == "users"
    assert len(stmt.columns) == 4
    print("   CREATE TABLE parsed: OK")

    print("   SQL Parser working!")


def test_type_system():
    """Test 3: SQL Type System."""
    print("\n3. Testing SQL Type System...")

    from fdb_record_layer.relational.sql.types import (
        BOOLEAN, BIGINT, INT, DOUBLE, STRING, NULL,
        IntegerType, FloatType, StringType, ArrayType,
        common_type, infer_type, coerce_value,
        TypeChecker,
    )

    # Type instances
    assert BOOLEAN.name == "BOOLEAN"
    assert BIGINT.name == "BIGINT"
    assert STRING.name == "STRING"
    print("   Type instances: OK")

    # Type compatibility
    assert BIGINT.is_compatible(INT)
    assert DOUBLE.is_compatible(BIGINT)
    assert NULL.is_compatible(STRING)
    print("   Type compatibility: OK")

    # Type inference
    assert infer_type(42).name in ("TINYINT", "SMALLINT", "INT", "BIGINT")
    assert infer_type(3.14).name == "DOUBLE"
    assert infer_type("hello").name == "STRING"
    assert infer_type(True).name == "BOOLEAN"
    assert infer_type(None).name == "NULL"
    print("   Type inference: OK")

    # Common type (for coercion)
    assert common_type(INT, BIGINT) is not None
    assert common_type(INT, DOUBLE) is not None
    assert common_type(INT, NULL) is not None
    print("   Common type: OK")

    # Value coercion
    assert coerce_value(42, STRING) == "42"
    assert coerce_value("100", INT) == 100
    assert coerce_value(1, BOOLEAN) == True
    print("   Value coercion: OK")

    # Type checker
    checker = TypeChecker()
    result_type, error = checker.check_binary_op(INT, BIGINT, "+")
    assert result_type is not None
    assert error is None
    print("   Type checker: OK")

    # Function type checking
    result_type, error = checker.check_function("COUNT", [STRING])
    assert result_type == BIGINT
    result_type, error = checker.check_function("SUM", [INT])
    assert result_type is not None
    print("   Function type checking: OK")

    print("   SQL Type System working!")


def test_translator():
    """Test 4: SQL to RecordQuery Translator."""
    print("\n4. Testing SQL Translator...")

    from fdb_record_layer.relational.sql.translator import (
        SQLTranslator,
        TranslationContext,
        TranslatedQuery,
        TranslatedInsert,
        TranslatedUpdate,
        TranslatedDelete,
        TranslatedCreateTable,
        translate_sql,
    )

    # SELECT translation
    translated = translate_sql("SELECT * FROM users WHERE age > 21")
    assert isinstance(translated, TranslatedQuery)
    assert "users" in translated.record_types
    assert translated.filter is not None
    print("   SELECT translated: OK")

    # SELECT with ORDER BY
    translated = translate_sql("SELECT * FROM users ORDER BY name DESC")
    assert len(translated.sort_fields) == 1
    assert translated.sort_fields[0] == ("name", True)
    print("   ORDER BY translated: OK")

    # SELECT with LIMIT
    translated = translate_sql("SELECT * FROM users LIMIT 10 OFFSET 5")
    assert translated.limit == 10
    assert translated.offset == 5
    print("   LIMIT/OFFSET translated: OK")

    # INSERT translation
    translated = translate_sql("INSERT INTO users (id, name) VALUES (1, 'Alice')")
    assert isinstance(translated, TranslatedInsert)
    assert translated.record_type == "users"
    assert translated.columns == ["id", "name"]
    assert translated.values == [[1, "Alice"]]
    print("   INSERT translated: OK")

    # UPDATE translation
    translated = translate_sql("UPDATE users SET name = 'Bob' WHERE id = 1")
    assert isinstance(translated, TranslatedUpdate)
    assert translated.record_type == "users"
    assert "name" in translated.updates
    print("   UPDATE translated: OK")

    # DELETE translation
    translated = translate_sql("DELETE FROM users WHERE id = 1")
    assert isinstance(translated, TranslatedDelete)
    assert translated.record_type == "users"
    print("   DELETE translated: OK")

    # CREATE TABLE translation
    translated = translate_sql("""
        CREATE TABLE users (
            id BIGINT PRIMARY KEY,
            name STRING NOT NULL
        )
    """)
    assert isinstance(translated, TranslatedCreateTable)
    assert translated.table_name == "users"
    assert len(translated.columns) == 2
    assert "id" in translated.primary_key
    print("   CREATE TABLE translated: OK")

    # Table to record type mapping
    context = TranslationContext()
    context.table_to_record_type["users"] = "UserRecord"
    translator = SQLTranslator(context)

    from fdb_record_layer.relational.sql.parser import parse
    stmt = parse("SELECT * FROM users")
    translated = translator.translate(stmt)
    assert "UserRecord" in translated.record_types
    print("   Table mapping: OK")

    print("   SQL Translator working!")


def test_schema():
    """Test 5: Schema and Table definitions."""
    print("\n5. Testing Schema...")

    from fdb_record_layer.relational.schema import (
        Schema, Table, Column, Index,
        SchemaBuilder, SchemaTemplate,
        schema_from_sql,
    )
    from fdb_record_layer.relational.sql.types import BIGINT, STRING, INT

    # Create schema manually
    schema = Schema(name="mydb")
    table = schema.create_table("users")
    table.add_column("id", BIGINT, nullable=False, is_primary_key=True)
    table.add_column("name", STRING)
    table.add_column("age", INT)
    table.add_index("users_name_idx", [("name", False)])

    assert "users" in schema.table_names
    assert "id" in table.column_names
    assert table.columns["id"].is_primary_key
    assert "users_name_idx" in table.indexes
    print("   Manual schema creation: OK")

    # Schema builder
    schema2 = (SchemaBuilder("testdb")
        .create_table("products")
        .add_column("id", BIGINT)
        .add_column("name", STRING)
        .add_column("price", INT)
        .add_primary_key("id")
        .add_index("products_name_idx", "name")
        .build())

    assert "products" in schema2.table_names
    product_table = schema2.get_table("products")
    assert product_table.primary_key == ["id"]
    print("   Schema builder: OK")

    # Schema from SQL
    schema3 = schema_from_sql("""
        CREATE TABLE customers (
            id BIGINT PRIMARY KEY,
            name STRING NOT NULL,
            email STRING
        );
        CREATE INDEX customers_email_idx ON customers (email);
    """)

    assert "customers" in schema3.table_names
    customer_table = schema3.get_table("customers")
    assert "id" in customer_table.column_names
    assert "customers_email_idx" in customer_table.indexes
    print("   Schema from SQL: OK")

    # Schema template
    template = SchemaTemplate(
        name="tenant_template",
        base_schema=schema,
    )
    tenant_schema = template.instantiate("tenant_1")
    assert tenant_schema.name == "tenant_1"
    assert "users" in tenant_schema.table_names
    print("   Schema template: OK")

    print("   Schema working!")


def test_result_set():
    """Test 6: Result Set."""
    print("\n6. Testing Result Set...")

    from fdb_record_layer.relational.result_set import (
        ResultSet, ResultSetBuilder, Row,
        from_records,
    )
    from fdb_record_layer.relational.sql.types import BIGINT, STRING

    # Build result set
    builder = (ResultSetBuilder()
        .add_column("id", BIGINT)
        .add_column("name", STRING)
        .add_row(1, "Alice")
        .add_row(2, "Bob")
        .add_row(3, "Charlie"))

    rs = builder.build()
    assert len(rs) == 3
    assert rs.column_names == ["id", "name"]
    print("   Result set builder: OK")

    # Row access
    row = rs[0]
    assert row["id"] == 1
    assert row["name"] == "Alice"
    assert row[0] == 1
    print("   Row access: OK")

    # Iteration
    names = [row["name"] for row in rs]
    assert names == ["Alice", "Bob", "Charlie"]
    print("   Iteration: OK")

    # JDBC-style cursor
    rs2 = builder.build()
    assert rs2.next()
    assert rs2.get_value("name") == "Alice"
    assert rs2.next()
    assert rs2.get_string("name") == "Bob"
    print("   JDBC-style cursor: OK")

    # To list/dict
    data = rs.to_list()
    assert len(data) == 3
    assert data[0] == {"id": 1, "name": "Alice"}
    print("   To list: OK")

    # From records
    records = [
        {"id": 1, "name": "Alice"},
        {"id": 2, "name": "Bob"},
    ]
    rs3 = from_records(records)
    assert len(rs3) == 2
    assert rs3[0]["name"] == "Alice"
    print("   From records: OK")

    print("   Result Set working!")


def test_relational_database():
    """Test 7: Relational Database."""
    print("\n7. Testing Relational Database...")

    from fdb_record_layer.relational.database import (
        RelationalDatabase,
        ExecutionResult,
        connect,
    )

    # Create database
    db = connect("testdb")
    assert db.name == "testdb"
    print("   Database created: OK")

    # CREATE TABLE
    result = db.execute_sql("""
        CREATE TABLE users (
            id BIGINT PRIMARY KEY,
            name STRING NOT NULL,
            age INT
        )
    """)
    if not result.success:
        print(f"   CREATE TABLE error: {result.error}")
    assert result.success, f"CREATE TABLE failed: {result.error}"
    assert "users" in db.get_tables()
    print("   CREATE TABLE: OK")

    # INSERT
    result = db.execute_sql("INSERT INTO users (id, name, age) VALUES (1, 'Alice', 30)")
    assert result.success
    assert result.rows_affected == 1
    print("   INSERT single row: OK")

    result = db.execute_sql("INSERT INTO users (id, name, age) VALUES (2, 'Bob', 25)")
    result = db.execute_sql("INSERT INTO users (id, name, age) VALUES (3, 'Charlie', 35)")
    print("   INSERT multiple rows: OK")

    # SELECT all
    result = db.execute_sql("SELECT * FROM users")
    assert result.success
    assert result.result_set is not None
    assert len(result.result_set) == 3
    print("   SELECT all: OK")

    # SELECT with WHERE
    result = db.execute_sql("SELECT * FROM users WHERE age > 28")
    assert len(result.result_set) == 2
    print("   SELECT with WHERE: OK")

    # SELECT with ORDER BY
    result = db.execute_sql("SELECT * FROM users ORDER BY age DESC")
    rows = list(result.result_set)
    assert rows[0]["name"] == "Charlie"
    assert rows[1]["name"] == "Alice"
    assert rows[2]["name"] == "Bob"
    print("   SELECT with ORDER BY: OK")

    # SELECT with LIMIT
    result = db.execute_sql("SELECT * FROM users ORDER BY id LIMIT 2")
    assert len(result.result_set) == 2
    print("   SELECT with LIMIT: OK")

    # SELECT with aggregate
    result = db.execute_sql("SELECT COUNT(*) FROM users")
    assert result.result_set is not None
    row = list(result.result_set)[0]
    assert row[0] == 3
    print("   SELECT COUNT: OK")

    result = db.execute_sql("SELECT AVG(age) FROM users")
    row = list(result.result_set)[0]
    assert row[0] == 30.0
    print("   SELECT AVG: OK")

    # UPDATE
    result = db.execute_sql("UPDATE users SET age = 31 WHERE name = 'Alice'")
    assert result.success
    assert result.rows_affected == 1
    print("   UPDATE: OK")

    # Verify update
    result = db.execute_sql("SELECT age FROM users WHERE name = 'Alice'")
    row = list(result.result_set)[0]
    assert row["age"] == 31
    print("   UPDATE verified: OK")

    # DELETE
    result = db.execute_sql("DELETE FROM users WHERE name = 'Bob'")
    assert result.success
    assert result.rows_affected == 1
    print("   DELETE: OK")

    # Verify delete
    result = db.execute_sql("SELECT COUNT(*) FROM users")
    row = list(result.result_set)[0]
    assert row[0] == 2
    print("   DELETE verified: OK")

    # Convenience methods
    db.insert("users", {"id": 4, "name": "Diana", "age": 28})
    result = db.query("SELECT * FROM users WHERE id = 4")
    assert len(result) == 1
    print("   Convenience insert: OK")

    rows_updated = db.update("users", {"age": 29}, "id = 4")
    assert rows_updated == 1
    print("   Convenience update: OK")

    rows_deleted = db.delete("users", "id = 4")
    assert rows_deleted == 1
    print("   Convenience delete: OK")

    db.close()
    print("   Relational Database working!")


def test_complex_queries():
    """Test 8: Complex SQL queries."""
    print("\n8. Testing Complex Queries...")

    from fdb_record_layer.relational.database import connect

    db = connect("complexdb")

    # Create tables
    db.execute_sql("""
        CREATE TABLE products (
            id BIGINT PRIMARY KEY,
            name STRING,
            category STRING,
            price INT
        )
    """)

    # Insert test data
    products = [
        (1, "Laptop", "Electronics", 1000),
        (2, "Phone", "Electronics", 500),
        (3, "Shirt", "Clothing", 30),
        (4, "Pants", "Clothing", 50),
        (5, "Book", "Media", 20),
    ]
    for p in products:
        db.execute_sql(f"INSERT INTO products (id, name, category, price) VALUES ({p[0]}, '{p[1]}', '{p[2]}', {p[3]})")

    # Complex WHERE with AND
    result = db.query("SELECT * FROM products WHERE category = 'Electronics' AND price > 700")
    assert len(result) == 1
    assert list(result)[0]["name"] == "Laptop"
    print("   WHERE with AND: OK")

    # DISTINCT
    result = db.query("SELECT DISTINCT category FROM products")
    categories = [r["category"] for r in result]
    assert len(categories) == 3
    print("   DISTINCT: OK")

    # Aggregates with GROUP BY
    result = db.query("SELECT category, COUNT(*) FROM products GROUP BY category")
    data = result.to_list()
    assert len(data) == 3
    print("   GROUP BY with COUNT: OK")

    result = db.query("SELECT category, SUM(price) FROM products GROUP BY category")
    data = result.to_list()
    electronics_sum = next(r for r in data if r["category"] == "Electronics")
    assert electronics_sum["SUM(price)"] == 1500
    print("   GROUP BY with SUM: OK")

    # MIN/MAX
    result = db.query("SELECT MIN(price), MAX(price) FROM products")
    row = list(result)[0]
    assert row[0] == 20
    assert row[1] == 1000
    print("   MIN/MAX: OK")

    db.close()
    print("   Complex Queries working!")


def main():
    """Run Phase 6 tests."""
    print("=" * 60)
    print("Phase 6: Relational Layer (SQL Support)")
    print("=" * 60)

    test_lexer()
    test_parser()
    test_type_system()
    test_translator()
    test_schema()
    test_result_set()
    test_relational_database()
    test_complex_queries()

    print("\n" + "=" * 60)
    print("Phase 6 Test Complete!")
    print("=" * 60)
    print("\nPhase 6 successfully implemented:")
    print("  - SQL Lexer with full token support")
    print("  - Recursive descent SQL Parser")
    print("  - SELECT, INSERT, UPDATE, DELETE parsing")
    print("  - CREATE TABLE, CREATE INDEX parsing")
    print("  - WHERE clauses with AND/OR/NOT")
    print("  - ORDER BY, LIMIT, OFFSET, DISTINCT")
    print("  - SQL Type System with coercion")
    print("  - Type checking for operations and functions")
    print("  - SQL to RecordQuery translation")
    print("  - Schema and Table definitions")
    print("  - SchemaBuilder and SchemaTemplate")
    print("  - ResultSet with JDBC-style cursor")
    print("  - RelationalDatabase with in-memory storage")
    print("  - Aggregate functions (COUNT, SUM, AVG, MIN, MAX)")
    print("  - GROUP BY support")
    print("  - Full SQL CRUD operations")


if __name__ == "__main__":
    main()
