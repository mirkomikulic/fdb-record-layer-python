"""Schema and SchemaTemplate for the Relational Layer.

Schemas define the structure of tables and indexes in a relational database.
SchemaTemplates allow for multi-tenant schema definitions.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from .sql.types import SQLType


@dataclass
class Column:
    """A column definition in a table."""

    name: str
    sql_type: SQLType
    nullable: bool = True
    default_value: Any | None = None
    is_primary_key: bool = False
    is_unique: bool = False

    def __post_init__(self) -> None:
        """Validate column definition."""
        if self.is_primary_key:
            self.nullable = False

    def __repr__(self) -> str:
        parts = [self.name, str(self.sql_type)]
        if not self.nullable:
            parts.append("NOT NULL")
        if self.is_primary_key:
            parts.append("PRIMARY KEY")
        if self.default_value is not None:
            parts.append(f"DEFAULT {self.default_value!r}")
        return f"Column({', '.join(parts)})"


@dataclass
class Index:
    """An index definition for a table."""

    name: str
    table_name: str
    columns: list[tuple[str, bool]]  # (column_name, descending)
    unique: bool = False

    @property
    def column_names(self) -> list[str]:
        """Get just the column names."""
        return [col for col, _ in self.columns]

    def __repr__(self) -> str:
        cols = ", ".join(f"{c} DESC" if desc else c for c, desc in self.columns)
        unique_str = "UNIQUE " if self.unique else ""
        return f"Index({self.name}: {unique_str}({cols}))"


@dataclass
class ForeignKey:
    """A foreign key constraint."""

    name: str
    columns: list[str]
    reference_table: str
    reference_columns: list[str]
    on_delete: str = "NO ACTION"  # CASCADE, SET NULL, NO ACTION
    on_update: str = "NO ACTION"


@dataclass
class Table:
    """A table definition in a schema."""

    name: str
    columns: dict[str, Column] = field(default_factory=dict)
    primary_key: list[str] = field(default_factory=list)
    indexes: dict[str, Index] = field(default_factory=dict)
    foreign_keys: dict[str, ForeignKey] = field(default_factory=dict)
    record_type_name: str | None = None  # Maps to protobuf record type

    def add_column(
        self,
        name: str,
        sql_type: SQLType,
        nullable: bool = True,
        default_value: Any | None = None,
        is_primary_key: bool = False,
    ) -> Column:
        """Add a column to the table.

        Args:
            name: Column name.
            sql_type: SQL data type.
            nullable: Whether the column allows NULL.
            default_value: Default value for the column.
            is_primary_key: Whether this column is the primary key.

        Returns:
            The created column.
        """
        column = Column(
            name=name,
            sql_type=sql_type,
            nullable=nullable,
            default_value=default_value,
            is_primary_key=is_primary_key,
        )
        self.columns[name] = column

        if is_primary_key and name not in self.primary_key:
            self.primary_key.append(name)

        return column

    def add_index(
        self,
        name: str,
        columns: list[tuple[str, bool]],
        unique: bool = False,
    ) -> Index:
        """Add an index to the table.

        Args:
            name: Index name.
            columns: List of (column_name, descending) tuples.
            unique: Whether this is a unique index.

        Returns:
            The created index.
        """
        index = Index(
            name=name,
            table_name=self.name,
            columns=columns,
            unique=unique,
        )
        self.indexes[name] = index
        return index

    def get_column(self, name: str) -> Column | None:
        """Get a column by name."""
        return self.columns.get(name)

    @property
    def column_names(self) -> list[str]:
        """Get the list of column names."""
        return list(self.columns.keys())

    def __repr__(self) -> str:
        cols = ", ".join(self.column_names)
        return f"Table({self.name}: [{cols}])"


@dataclass
class Schema:
    """A database schema containing tables and indexes.

    A schema is a namespace for tables, similar to a database schema
    in traditional SQL databases.
    """

    name: str
    tables: dict[str, Table] = field(default_factory=dict)
    version: int = 1

    def create_table(self, name: str) -> Table:
        """Create a new table in the schema.

        Args:
            name: Table name.

        Returns:
            The created table.
        """
        if name in self.tables:
            raise ValueError(f"Table already exists: {name}")

        table = Table(name=name)
        self.tables[name] = table
        return table

    def get_table(self, name: str) -> Table | None:
        """Get a table by name."""
        return self.tables.get(name)

    def drop_table(self, name: str) -> bool:
        """Drop a table from the schema.

        Args:
            name: Table name.

        Returns:
            True if the table was dropped, False if it didn't exist.
        """
        if name in self.tables:
            del self.tables[name]
            return True
        return False

    @property
    def table_names(self) -> list[str]:
        """Get the list of table names."""
        return list(self.tables.keys())

    def __repr__(self) -> str:
        return f"Schema({self.name}: {self.table_names})"


@dataclass
class SchemaTemplate:
    """A template for creating schemas.

    SchemaTemplates allow defining a schema structure once and
    instantiating it multiple times for multi-tenant scenarios.
    Each tenant gets their own schema instance with isolated data.
    """

    name: str
    base_schema: Schema
    parameters: dict[str, Any] = field(default_factory=dict)

    def instantiate(
        self,
        schema_name: str,
        parameter_values: dict[str, Any] | None = None,
    ) -> Schema:
        """Create a schema instance from this template.

        Args:
            schema_name: Name for the new schema.
            parameter_values: Values for template parameters.

        Returns:
            A new schema instance.
        """
        # Create a deep copy of the base schema with the new name
        schema = Schema(name=schema_name, version=self.base_schema.version)

        for table_name, table in self.base_schema.tables.items():
            new_table = schema.create_table(table_name)

            # Copy columns
            for col_name, column in table.columns.items():
                new_table.add_column(
                    name=col_name,
                    sql_type=column.sql_type,
                    nullable=column.nullable,
                    default_value=column.default_value,
                    is_primary_key=column.is_primary_key,
                )

            # Copy primary key
            new_table.primary_key = list(table.primary_key)

            # Copy indexes
            for idx_name, index in table.indexes.items():
                new_table.add_index(
                    name=idx_name,
                    columns=list(index.columns),
                    unique=index.unique,
                )

        return schema


class SchemaBuilder:
    """Builder for constructing schemas."""

    def __init__(self, name: str) -> None:
        """Initialize the builder.

        Args:
            name: Schema name.
        """
        self._schema = Schema(name=name)
        self._current_table: Table | None = None

    def create_table(self, name: str) -> SchemaBuilder:
        """Start defining a new table.

        Args:
            name: Table name.

        Returns:
            This builder for chaining.
        """
        self._current_table = self._schema.create_table(name)
        return self

    def add_column(
        self,
        name: str,
        sql_type: SQLType,
        nullable: bool = True,
        default_value: Any | None = None,
    ) -> SchemaBuilder:
        """Add a column to the current table.

        Args:
            name: Column name.
            sql_type: SQL data type.
            nullable: Whether the column allows NULL.
            default_value: Default value.

        Returns:
            This builder for chaining.
        """
        if self._current_table is None:
            raise RuntimeError("No table defined. Call create_table() first.")

        self._current_table.add_column(name, sql_type, nullable, default_value)
        return self

    def add_primary_key(self, *columns: str) -> SchemaBuilder:
        """Set the primary key for the current table.

        Args:
            columns: Primary key column names.

        Returns:
            This builder for chaining.
        """
        if self._current_table is None:
            raise RuntimeError("No table defined. Call create_table() first.")

        self._current_table.primary_key = list(columns)

        # Mark columns as primary key
        for col_name in columns:
            if col_name in self._current_table.columns:
                self._current_table.columns[col_name].is_primary_key = True
                self._current_table.columns[col_name].nullable = False

        return self

    def add_index(
        self,
        name: str,
        *columns: str,
        unique: bool = False,
    ) -> SchemaBuilder:
        """Add an index to the current table.

        Args:
            name: Index name.
            columns: Column names to index.
            unique: Whether this is a unique index.

        Returns:
            This builder for chaining.
        """
        if self._current_table is None:
            raise RuntimeError("No table defined. Call create_table() first.")

        cols = [(c, False) for c in columns]  # All ascending
        self._current_table.add_index(name, cols, unique)
        return self

    def set_record_type(self, record_type: str) -> SchemaBuilder:
        """Set the record type name for the current table.

        Args:
            record_type: The protobuf record type name.

        Returns:
            This builder for chaining.
        """
        if self._current_table is None:
            raise RuntimeError("No table defined. Call create_table() first.")

        self._current_table.record_type_name = record_type
        return self

    def build(self) -> Schema:
        """Build the schema.

        Returns:
            The constructed schema.
        """
        return self._schema


def schema_from_sql(sql: str) -> Schema:
    """Create a schema from SQL DDL statements.

    Args:
        sql: SQL containing CREATE TABLE statements.

    Returns:
        A schema containing the defined tables.
    """
    from .sql.ast import CreateIndexStatement, CreateTableStatement
    from .sql.parser import parse_all
    from .sql.translator import SQLTranslator, TranslatedCreateIndex, TranslatedCreateTable

    statements = parse_all(sql)
    translator = SQLTranslator()

    schema = Schema(name="default")

    for stmt in statements:
        if isinstance(stmt, CreateTableStatement):
            translated = translator.translate(stmt)
            assert isinstance(translated, TranslatedCreateTable)
            table = schema.create_table(translated.table_name)

            for col_name, sql_type, nullable, default in translated.columns:
                is_pk = col_name in translated.primary_key
                table.add_column(col_name, sql_type, nullable, default, is_pk)

            table.primary_key = translated.primary_key

        elif isinstance(stmt, CreateIndexStatement):
            translated = translator.translate(stmt)
            assert isinstance(translated, TranslatedCreateIndex)

            index_table = schema.get_table(translated.table_name)
            if index_table:
                index_table.add_index(
                    translated.index_name,
                    translated.columns,
                    translated.unique,
                )

    return schema
