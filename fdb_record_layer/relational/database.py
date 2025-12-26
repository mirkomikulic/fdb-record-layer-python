"""Relational Database implementation.

Provides SQL interface on top of the FDB Record Layer.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from .result_set import ResultSet, ResultSetBuilder
from .schema import Schema, Table
from .sql.ast import (
    CreateIndexStatement,
    CreateTableStatement,
    DeleteStatement,
    InsertStatement,
    SelectStatement,
    UpdateStatement,
)
from .sql.parser import ParseError, parse
from .sql.translator import (
    SQLTranslator,
    TranslatedCreateIndex,
    TranslatedCreateTable,
    TranslatedDelete,
    TranslatedInsert,
    TranslatedQuery,
    TranslatedUpdate,
    TranslationContext,
)


@dataclass
class ExecutionResult:
    """Result of executing a SQL statement."""

    # Number of rows affected (for INSERT/UPDATE/DELETE)
    rows_affected: int = 0

    # Result set (for SELECT)
    result_set: ResultSet | None = None

    # Success/failure
    success: bool = True

    # Error message (if any)
    error: str | None = None

    # Warnings
    warnings: list[str] = field(default_factory=list)


class RelationalDatabase:
    """A relational database backed by FDB Record Layer.

    Provides SQL interface for querying and modifying data stored
    in FDB Record Layer record stores.

    Example:
        >>> db = RelationalDatabase("mydb")
        >>> db.execute_sql("CREATE TABLE users (id BIGINT PRIMARY KEY, name STRING)")
        >>> db.execute_sql("INSERT INTO users VALUES (1, 'Alice')")
        >>> result = db.execute_sql("SELECT * FROM users")
        >>> for row in result.result_set:
        ...     print(row['name'])
        Alice
    """

    def __init__(
        self,
        name: str,
        schema: Schema | None = None,
        record_store: Any | None = None,  # FDBRecordStore
    ) -> None:
        """Initialize the relational database.

        Args:
            name: Database name.
            schema: Optional schema definition.
            record_store: Optional FDB record store for data persistence.
        """
        self._name = name
        self._schema = schema or Schema(name=name)
        self._record_store = record_store

        # In-memory data storage (when no record store is provided)
        self._data: dict[str, list[dict[str, Any]]] = {}

        # Translation context
        self._context = TranslationContext()

        # Build table to record type mappings from schema
        for table_name, table in self._schema.tables.items():
            record_type = table.record_type_name or table_name
            self._context.table_to_record_type[table_name] = record_type

    @property
    def name(self) -> str:
        """Get the database name."""
        return self._name

    @property
    def schema(self) -> Schema:
        """Get the database schema."""
        return self._schema

    def execute_sql(self, sql: str) -> ExecutionResult:
        """Execute a SQL statement.

        Args:
            sql: The SQL statement to execute.

        Returns:
            The execution result.
        """
        try:
            statement = parse(sql)
            return self._execute_statement(statement)

        except ParseError as e:
            return ExecutionResult(success=False, error=f"Parse error: {e}")
        except Exception as e:
            return ExecutionResult(success=False, error=str(e))

    def _execute_statement(self, stmt: Any) -> ExecutionResult:
        """Execute a single parsed statement."""
        translator = SQLTranslator(self._context)

        if isinstance(stmt, SelectStatement):
            translated = translator.translate(stmt)
            assert isinstance(translated, TranslatedQuery)
            return self._execute_select(translated, stmt)

        elif isinstance(stmt, InsertStatement):
            translated = translator.translate(stmt)
            assert isinstance(translated, TranslatedInsert)
            return self._execute_insert(translated)

        elif isinstance(stmt, UpdateStatement):
            translated = translator.translate(stmt)
            assert isinstance(translated, TranslatedUpdate)
            return self._execute_update(translated)

        elif isinstance(stmt, DeleteStatement):
            translated = translator.translate(stmt)
            assert isinstance(translated, TranslatedDelete)
            return self._execute_delete(translated)

        elif isinstance(stmt, CreateTableStatement):
            translated = translator.translate(stmt)
            assert isinstance(translated, TranslatedCreateTable)
            return self._execute_create_table(translated)

        elif isinstance(stmt, CreateIndexStatement):
            translated = translator.translate(stmt)
            assert isinstance(translated, TranslatedCreateIndex)
            return self._execute_create_index(translated)

        else:
            return ExecutionResult(
                success=False, error=f"Unsupported statement type: {type(stmt).__name__}"
            )

    def _execute_select(
        self,
        translated: TranslatedQuery,
        stmt: SelectStatement,
    ) -> ExecutionResult:
        """Execute a SELECT statement."""
        import asyncio

        if not translated.record_types:
            return ExecutionResult(success=False, error="No table specified in FROM clause")

        table_name = translated.record_types[0]

        # Get data
        if self._record_store is not None:
            # Use record store (async execution)
            try:
                loop = asyncio.get_event_loop()
                if loop.is_running():
                    # We're inside an async context - create a task
                    import concurrent.futures

                    with concurrent.futures.ThreadPoolExecutor() as executor:
                        future = executor.submit(
                            asyncio.run, self._execute_select_from_store(translated)
                        )
                        return future.result()
                else:
                    return asyncio.run(self._execute_select_from_store(translated))
            except RuntimeError:
                # No event loop - create one
                return asyncio.run(self._execute_select_from_store(translated))

        # Use in-memory data
        data = self._data.get(table_name, [])

        # Apply filter
        if translated.filter is not None:
            data = [row for row in data if self._evaluate_filter(row, translated.filter)]

        # Apply sorting
        if translated.sort_fields:
            for field_name, descending in reversed(translated.sort_fields):

                def sort_key(row: dict[str, Any], fname: str = field_name) -> tuple[bool, Any]:
                    return (row.get(fname) is None, row.get(fname))

                data.sort(key=sort_key, reverse=descending)

        # Apply DISTINCT - use only projected columns for uniqueness
        if translated.distinct:
            # Determine which columns to use for distinctness
            if translated.columns and translated.columns != ["*"]:
                distinct_cols = translated.columns
            else:
                distinct_cols = None  # Use all columns

            seen = set()
            unique_data = []
            for row in data:
                if distinct_cols:
                    key = tuple(row.get(col) for col in distinct_cols)
                else:
                    key = tuple(sorted(row.items()))
                if key not in seen:
                    seen.add(key)
                    unique_data.append(row)
            data = unique_data

        # Apply LIMIT and OFFSET
        if translated.offset:
            data = data[translated.offset :]
        if translated.limit:
            data = data[: translated.limit]

        # Handle aggregates
        if translated.aggregates:
            return self._execute_aggregates(data, translated)

        # Build result set
        result_set = self._build_result_set(data, translated, table_name)

        return ExecutionResult(result_set=result_set)

    async def _execute_select_from_store(self, translated: TranslatedQuery) -> ExecutionResult:
        """Execute a SELECT against the record store.

        Builds a RecordQuery from the translated SQL and executes it
        against the FDB record store.
        """
        from fdb_record_layer.query.query import RecordQuery

        if self._record_store is None:
            return ExecutionResult(success=False, error="No record store configured")

        # Build the RecordQuery
        record_types = translated.record_types or []
        query = RecordQuery(
            record_types=record_types,
            filter=translated.filter,
            sort=None,  # TODO: convert sort_fields to SortDescriptor
        )

        # Execute the query
        try:
            cursor = await self._record_store.execute_query(query)

            # Collect results
            records: list[dict[str, Any]] = []
            async for stored_record in cursor:
                # Convert protobuf to dict
                record_dict = self._record_to_dict(stored_record)
                records.append(record_dict)

                # Apply limit if specified
                if translated.limit and len(records) >= translated.limit:
                    break

            # Apply offset
            if translated.offset:
                records = records[translated.offset :]

            # Build result set
            table_name = record_types[0] if record_types else "result"
            result_set = self._build_result_set(records, translated, table_name)

            return ExecutionResult(result_set=result_set)

        except Exception as e:
            return ExecutionResult(success=False, error=str(e))

    def _record_to_dict(self, stored_record: Any) -> dict[str, Any]:
        """Convert a stored record to a dictionary."""
        record = stored_record.record
        result: dict[str, Any] = {}

        # Handle protobuf message
        if hasattr(record, "ListFields"):
            for field, value in record.ListFields():
                result[field.name] = value
        # Handle dict-like records
        elif hasattr(record, "items"):
            result = dict(record.items())
        # Handle object with __dict__
        elif hasattr(record, "__dict__"):
            result = dict(record.__dict__)

        return result

    def _execute_aggregates(
        self,
        data: list[dict[str, Any]],
        translated: TranslatedQuery,
    ) -> ExecutionResult:
        """Execute aggregate functions."""
        # Group the data if GROUP BY is present
        if translated.group_by:
            groups: dict[tuple, list[dict[str, Any]]] = {}
            for row in data:
                key = tuple(row.get(f) for f in translated.group_by)
                if key not in groups:
                    groups[key] = []
                groups[key].append(row)
        else:
            groups = {(): data}

        # Build result
        builder = ResultSetBuilder()

        # Add GROUP BY columns
        for field_name in translated.group_by:
            builder.add_column(field_name)

        # Add aggregate columns
        for func_name, field_name, alias in translated.aggregates:
            col_name = alias or f"{func_name}({field_name})"
            builder.add_column(col_name)

        # Calculate aggregates for each group
        for group_key, group_data in groups.items():
            row_values = list(group_key)

            for func_name, field_name, alias in translated.aggregates:
                if func_name == "COUNT":
                    if field_name == "*":
                        value = len(group_data)
                    else:
                        value = sum(1 for r in group_data if r.get(field_name) is not None)

                elif func_name == "SUM":
                    numeric_values = [r.get(field_name, 0) for r in group_data]
                    value = sum(v for v in numeric_values if v is not None)

                elif func_name == "AVG":
                    numeric_values = [
                        r.get(field_name) for r in group_data if r.get(field_name) is not None
                    ]
                    if numeric_values:
                        total = sum(v for v in numeric_values if v is not None)
                        value = total / len(numeric_values)
                    else:
                        value = None

                elif func_name == "MIN":
                    comparable_values = [
                        r.get(field_name) for r in group_data if r.get(field_name) is not None
                    ]
                    value = min(comparable_values) if comparable_values else None  # type: ignore[type-var]

                elif func_name == "MAX":
                    comparable_values = [
                        r.get(field_name) for r in group_data if r.get(field_name) is not None
                    ]
                    value = max(comparable_values) if comparable_values else None  # type: ignore[type-var]

                else:
                    value = None

                row_values.append(value)

            builder.add_row(*row_values)

        return ExecutionResult(result_set=builder.build())

    def _build_result_set(
        self,
        data: list[dict[str, Any]],
        translated: TranslatedQuery,
        table_name: str,
    ) -> ResultSet:
        """Build a result set from query results."""
        builder = ResultSetBuilder()

        # Determine columns
        if translated.columns and translated.columns != ["*"]:
            columns = translated.columns
        elif data:
            columns = list(data[0].keys())
        else:
            # Get columns from schema
            table = self._schema.get_table(table_name)
            columns = table.column_names if table else []

        # Add column metadata
        for col in columns:
            builder.add_column(col)

        # Add rows
        for row in data:
            values = [row.get(col) for col in columns]
            builder.add_row(*values)

        return builder.build()

    def _execute_insert(self, translated: TranslatedInsert) -> ExecutionResult:
        """Execute an INSERT statement."""
        table_name = translated.record_type

        # Ensure table exists in data
        if table_name not in self._data:
            self._data[table_name] = []

        # Insert rows
        rows_affected = 0
        for row_values in translated.values:
            record: dict[str, Any] = {}

            if translated.columns:
                for i, col in enumerate(translated.columns):
                    if i < len(row_values):
                        record[col] = row_values[i]
            else:
                # Use schema column order
                table = self._schema.get_table(table_name)
                if table:
                    for i, col in enumerate(table.column_names):
                        if i < len(row_values):
                            record[col] = row_values[i]
                else:
                    # No schema - use numeric keys
                    for i, val in enumerate(row_values):
                        record[f"col{i}"] = val

            self._data[table_name].append(record)
            rows_affected += 1

        return ExecutionResult(rows_affected=rows_affected)

    def _execute_update(self, translated: TranslatedUpdate) -> ExecutionResult:
        """Execute an UPDATE statement."""
        table_name = translated.record_type

        if table_name not in self._data:
            return ExecutionResult(rows_affected=0)

        rows_affected = 0
        for row in self._data[table_name]:
            if translated.filter is None or self._evaluate_filter(row, translated.filter):
                for col, val in translated.updates.items():
                    row[col] = val
                rows_affected += 1

        return ExecutionResult(rows_affected=rows_affected)

    def _execute_delete(self, translated: TranslatedDelete) -> ExecutionResult:
        """Execute a DELETE statement."""
        table_name = translated.record_type

        if table_name not in self._data:
            return ExecutionResult(rows_affected=0)

        original_count = len(self._data[table_name])

        if translated.filter is None:
            # Delete all
            self._data[table_name] = []
        else:
            # Delete matching rows
            self._data[table_name] = [
                row
                for row in self._data[table_name]
                if not self._evaluate_filter(row, translated.filter)
            ]

        rows_affected = original_count - len(self._data[table_name])
        return ExecutionResult(rows_affected=rows_affected)

    def _execute_create_table(self, translated: TranslatedCreateTable) -> ExecutionResult:
        """Execute a CREATE TABLE statement."""
        table_name = translated.table_name

        if table_name in self._schema.tables:
            return ExecutionResult(success=False, error=f"Table already exists: {table_name}")

        # Create table in schema
        table = self._schema.create_table(table_name)

        for col_name, sql_type, nullable, default in translated.columns:
            is_pk = col_name in translated.primary_key
            table.add_column(col_name, sql_type, nullable, default, is_pk)

        table.primary_key = translated.primary_key

        # Initialize empty data
        self._data[table_name] = []

        # Update context
        self._context.table_to_record_type[table_name] = table_name

        return ExecutionResult()

    def _execute_create_index(self, translated: TranslatedCreateIndex) -> ExecutionResult:
        """Execute a CREATE INDEX statement."""
        table = self._schema.get_table(translated.table_name)

        if table is None:
            return ExecutionResult(success=False, error=f"Table not found: {translated.table_name}")

        table.add_index(
            translated.index_name,
            translated.columns,
            translated.unique,
        )

        return ExecutionResult()

    def _evaluate_filter(
        self,
        row: dict[str, Any],
        filter_component: Any,
    ) -> bool:
        """Evaluate a filter against a row."""
        # Import QueryComponent types
        try:
            from fdb_record_layer.query.components import (
                AndComponent,
                FieldComponent,
                NotComponent,
                OrComponent,
            )

            if isinstance(filter_component, FieldComponent):
                field_value = row.get(filter_component.field_name)
                return filter_component.comparison.evaluate(field_value)

            elif isinstance(filter_component, AndComponent):
                return all(self._evaluate_filter(row, child) for child in filter_component.children)

            elif isinstance(filter_component, OrComponent):
                return any(self._evaluate_filter(row, child) for child in filter_component.children)

            elif isinstance(filter_component, NotComponent):
                return not self._evaluate_filter(row, filter_component.child)

        except ImportError:
            pass

        return True

    def query(self, sql: str) -> ResultSet:
        """Execute a SELECT query and return the result set.

        Args:
            sql: The SELECT statement.

        Returns:
            The result set.

        Raises:
            RuntimeError: If the query fails.
        """
        result = self.execute_sql(sql)
        if not result.success:
            raise RuntimeError(result.error)
        if result.result_set is None:
            raise RuntimeError("Query did not return a result set")
        return result.result_set

    def execute(self, sql: str) -> int:
        """Execute a DML statement and return rows affected.

        Args:
            sql: The INSERT/UPDATE/DELETE statement.

        Returns:
            Number of rows affected.

        Raises:
            RuntimeError: If the statement fails.
        """
        result = self.execute_sql(sql)
        if not result.success:
            raise RuntimeError(result.error)
        return result.rows_affected

    def _escape_sql_string(self, value: str) -> str:
        """Escape a string value for SQL.

        Prevents SQL injection by escaping single quotes.

        Args:
            value: The string to escape.

        Returns:
            The escaped string.
        """
        # Escape single quotes by doubling them (SQL standard)
        return value.replace("'", "''")

    def _validate_identifier(self, name: str) -> str:
        """Validate and sanitize a SQL identifier (table/column name).

        Args:
            name: The identifier to validate.

        Returns:
            The validated identifier.

        Raises:
            ValueError: If the identifier contains invalid characters.
        """
        import re

        # Only allow alphanumeric, underscore, and dollar sign
        if not re.match(r"^[a-zA-Z_][a-zA-Z0-9_$]*$", name):
            raise ValueError(f"Invalid SQL identifier: {name}")
        return name

    def _format_sql_value(self, value: Any) -> str:
        """Format a value for SQL, with proper escaping.

        Args:
            value: The value to format.

        Returns:
            SQL-safe string representation.
        """
        if value is None:
            return "NULL"
        elif isinstance(value, bool):
            return "TRUE" if value else "FALSE"
        elif isinstance(value, str):
            return f"'{self._escape_sql_string(value)}'"
        elif isinstance(value, (int, float)):
            return str(value)
        else:
            # For other types, convert to string and escape
            return f"'{self._escape_sql_string(str(value))}'"

    def insert(
        self,
        table: str,
        values: dict[str, Any],
    ) -> int:
        """Insert a row into a table.

        Args:
            table: Table name.
            values: Column values as a dictionary.

        Returns:
            Number of rows inserted (1).

        Raises:
            ValueError: If table or column names are invalid.
        """
        # Validate identifiers
        safe_table = self._validate_identifier(table)
        safe_columns = [self._validate_identifier(k) for k in values.keys()]

        columns = ", ".join(safe_columns)
        placeholders = ", ".join(self._format_sql_value(v) for v in values.values())
        sql = f"INSERT INTO {safe_table} ({columns}) VALUES ({placeholders})"
        return self.execute(sql)

    def update(
        self,
        table: str,
        values: dict[str, Any],
        where: str | None = None,
    ) -> int:
        """Update rows in a table.

        Note: The 'where' parameter accepts raw SQL which could be vulnerable.
        For safer queries, use execute_sql() with proper parameterization.

        Args:
            table: Table name.
            values: Column values to set.
            where: Optional WHERE clause (without the WHERE keyword).
                   WARNING: This is passed directly to SQL. Use with caution.

        Returns:
            Number of rows updated.

        Raises:
            ValueError: If table or column names are invalid.
        """
        # Validate identifiers
        safe_table = self._validate_identifier(table)

        set_parts = []
        for k, v in values.items():
            safe_col = self._validate_identifier(k)
            safe_val = self._format_sql_value(v)
            set_parts.append(f"{safe_col} = {safe_val}")

        set_clause = ", ".join(set_parts)
        sql = f"UPDATE {safe_table} SET {set_clause}"

        if where:
            # Note: where clause is still vulnerable - document this limitation
            sql += f" WHERE {where}"

        return self.execute(sql)

    def delete(
        self,
        table: str,
        where: str | None = None,
    ) -> int:
        """Delete rows from a table.

        Note: The 'where' parameter accepts raw SQL which could be vulnerable.
        For safer queries, use execute_sql() with proper parameterization.

        Args:
            table: Table name.
            where: Optional WHERE clause (without the WHERE keyword).
                   WARNING: This is passed directly to SQL. Use with caution.

        Returns:
            Number of rows deleted.

        Raises:
            ValueError: If table name is invalid.
        """
        safe_table = self._validate_identifier(table)
        sql = f"DELETE FROM {safe_table}"

        if where:
            # Note: where clause is still vulnerable - document this limitation
            sql += f" WHERE {where}"

        return self.execute(sql)

    def get_tables(self) -> list[str]:
        """Get the list of table names."""
        return self._schema.table_names

    def get_table(self, name: str) -> Table | None:
        """Get a table definition."""
        return self._schema.get_table(name)

    def close(self) -> None:
        """Close the database connection."""
        # Clean up resources
        pass


def connect(
    name: str,
    schema: Schema | None = None,
) -> RelationalDatabase:
    """Create a new relational database connection.

    Args:
        name: Database name.
        schema: Optional schema definition.

    Returns:
        A RelationalDatabase instance.
    """
    return RelationalDatabase(name, schema)
