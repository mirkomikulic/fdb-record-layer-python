"""Result set for SQL query results."""

from __future__ import annotations

from collections.abc import Iterator
from dataclasses import dataclass, field
from typing import Any

from .sql.types import STRING, SQLType, infer_type


@dataclass
class ColumnMetadata:
    """Metadata for a result set column."""

    name: str
    sql_type: SQLType
    nullable: bool = True
    table_name: str | None = None
    schema_name: str | None = None

    @property
    def qualified_name(self) -> str:
        """Get the fully qualified column name."""
        parts = []
        if self.schema_name:
            parts.append(self.schema_name)
        if self.table_name:
            parts.append(self.table_name)
        parts.append(self.name)
        return ".".join(parts)


@dataclass
class ResultSetMetadata:
    """Metadata for a result set."""

    columns: list[ColumnMetadata] = field(default_factory=list)

    def get_column_count(self) -> int:
        """Get the number of columns."""
        return len(self.columns)

    def get_column_name(self, index: int) -> str:
        """Get a column name by index."""
        return self.columns[index].name

    def get_column_type(self, index: int) -> SQLType:
        """Get a column type by index."""
        return self.columns[index].sql_type

    def get_column_index(self, name: str) -> int:
        """Get a column index by name."""
        name_lower = name.lower()
        for i, col in enumerate(self.columns):
            if col.name.lower() == name_lower:
                return i
        raise KeyError(f"Column not found: {name}")

    def add_column(
        self,
        name: str,
        sql_type: SQLType,
        nullable: bool = True,
        table_name: str | None = None,
    ) -> None:
        """Add a column to the metadata."""
        self.columns.append(
            ColumnMetadata(
                name=name,
                sql_type=sql_type,
                nullable=nullable,
                table_name=table_name,
            )
        )


class Row:
    """A single row in a result set."""

    def __init__(
        self,
        values: list[Any],
        metadata: ResultSetMetadata,
    ) -> None:
        """Initialize a row.

        Args:
            values: The column values.
            metadata: The result set metadata.
        """
        self._values = values
        self._metadata = metadata

    def __getitem__(self, key: int | str) -> Any:
        """Get a value by column index or name."""
        if isinstance(key, int):
            return self._values[key]
        index = self._metadata.get_column_index(key)
        return self._values[index]

    def __len__(self) -> int:
        """Get the number of columns."""
        return len(self._values)

    def __iter__(self) -> Iterator[Any]:
        """Iterate over values."""
        return iter(self._values)

    def get(self, key: int | str, default: Any = None) -> Any:
        """Get a value with a default."""
        try:
            return self[key]
        except (IndexError, KeyError):
            return default

    def as_dict(self) -> dict[str, Any]:
        """Convert to a dictionary."""
        return {col.name: self._values[i] for i, col in enumerate(self._metadata.columns)}

    def as_tuple(self) -> tuple[Any, ...]:
        """Convert to a tuple."""
        return tuple(self._values)

    def __repr__(self) -> str:
        return f"Row({self.as_dict()})"


class ResultSet:
    """A set of rows returned from a SQL query.

    Supports iteration, random access, and various access patterns.
    """

    def __init__(
        self,
        metadata: ResultSetMetadata | None = None,
        rows: list[list[Any]] | None = None,
    ) -> None:
        """Initialize the result set.

        Args:
            metadata: Column metadata.
            rows: List of row data.
        """
        self._metadata = metadata or ResultSetMetadata()
        self._rows = rows or []
        self._position = -1

    @property
    def metadata(self) -> ResultSetMetadata:
        """Get the result set metadata."""
        return self._metadata

    @property
    def column_names(self) -> list[str]:
        """Get the list of column names."""
        return [col.name for col in self._metadata.columns]

    @property
    def row_count(self) -> int:
        """Get the total number of rows."""
        return len(self._rows)

    def __len__(self) -> int:
        """Get the number of rows."""
        return len(self._rows)

    def __iter__(self) -> Iterator[Row]:
        """Iterate over rows."""
        for row_data in self._rows:
            yield Row(row_data, self._metadata)

    def __getitem__(self, index: int) -> Row:
        """Get a row by index."""
        return Row(self._rows[index], self._metadata)

    def next(self) -> bool:
        """Move to the next row (JDBC-style cursor).

        Returns:
            True if there is a next row, False otherwise.
        """
        self._position += 1
        return self._position < len(self._rows)

    def previous(self) -> bool:
        """Move to the previous row.

        Returns:
            True if there is a previous row, False otherwise.
        """
        if self._position > 0:
            self._position -= 1
            return True
        return False

    def first(self) -> bool:
        """Move to the first row.

        Returns:
            True if there is at least one row, False otherwise.
        """
        if len(self._rows) > 0:
            self._position = 0
            return True
        return False

    def last(self) -> bool:
        """Move to the last row.

        Returns:
            True if there is at least one row, False otherwise.
        """
        if len(self._rows) > 0:
            self._position = len(self._rows) - 1
            return True
        return False

    def get_row(self) -> Row | None:
        """Get the current row.

        Returns:
            The current row, or None if not positioned on a row.
        """
        if 0 <= self._position < len(self._rows):
            return Row(self._rows[self._position], self._metadata)
        return None

    def get_value(self, column: int | str) -> Any:
        """Get a value from the current row.

        Args:
            column: Column index or name.

        Returns:
            The column value.
        """
        row = self.get_row()
        if row is None:
            raise RuntimeError("No current row")
        return row[column]

    def get_string(self, column: int | str) -> str | None:
        """Get a string value from the current row."""
        value = self.get_value(column)
        if value is None:
            return None
        return str(value)

    def get_int(self, column: int | str) -> int | None:
        """Get an integer value from the current row."""
        value = self.get_value(column)
        if value is None:
            return None
        return int(value)

    def get_float(self, column: int | str) -> float | None:
        """Get a float value from the current row."""
        value = self.get_value(column)
        if value is None:
            return None
        return float(value)

    def get_bool(self, column: int | str) -> bool | None:
        """Get a boolean value from the current row."""
        value = self.get_value(column)
        if value is None:
            return None
        return bool(value)

    def add_row(self, values: list[Any]) -> None:
        """Add a row to the result set.

        Args:
            values: The column values.
        """
        if len(values) != len(self._metadata.columns):
            raise ValueError(
                f"Row has {len(values)} values but metadata has "
                f"{len(self._metadata.columns)} columns"
            )
        self._rows.append(values)

    def to_list(self) -> list[dict[str, Any]]:
        """Convert to a list of dictionaries."""
        return [row.as_dict() for row in self]

    def to_tuples(self) -> list[tuple[Any, ...]]:
        """Convert to a list of tuples."""
        return [tuple(row) for row in self._rows]

    def close(self) -> None:
        """Close the result set and release resources."""
        self._rows = []
        self._position = -1

    def __repr__(self) -> str:
        return f"ResultSet(columns={self.column_names}, rows={len(self._rows)})"


class ResultSetBuilder:
    """Builder for constructing result sets."""

    def __init__(self) -> None:
        """Initialize the builder."""
        self._metadata = ResultSetMetadata()
        self._rows: list[list[Any]] = []

    def add_column(
        self,
        name: str,
        sql_type: SQLType | None = None,
        nullable: bool = True,
    ) -> ResultSetBuilder:
        """Add a column.

        Args:
            name: Column name.
            sql_type: SQL type (inferred if not provided).
            nullable: Whether the column is nullable.

        Returns:
            This builder for chaining.
        """
        self._metadata.add_column(name, sql_type or STRING, nullable)
        return self

    def add_row(self, *values: Any) -> ResultSetBuilder:
        """Add a row.

        Args:
            values: Column values.

        Returns:
            This builder for chaining.
        """
        self._rows.append(list(values))
        return self

    def add_rows(self, rows: list[list[Any]]) -> ResultSetBuilder:
        """Add multiple rows.

        Args:
            rows: List of row data.

        Returns:
            This builder for chaining.
        """
        self._rows.extend(rows)
        return self

    def build(self) -> ResultSet:
        """Build the result set.

        Returns:
            The constructed result set.
        """
        return ResultSet(self._metadata, self._rows)


def from_records(
    records: list[dict[str, Any]],
    columns: list[str] | None = None,
) -> ResultSet:
    """Create a result set from a list of dictionaries.

    Args:
        records: List of record dictionaries.
        columns: Optional column order (uses first record's keys if not provided).

    Returns:
        A result set containing the data.
    """
    if not records:
        return ResultSet()

    # Determine columns
    if columns is None:
        columns = list(records[0].keys())

    # Build metadata
    metadata = ResultSetMetadata()
    for col in columns:
        # Infer type from first non-null value
        sql_type: SQLType = STRING
        for record in records:
            value = record.get(col)
            if value is not None:
                sql_type = infer_type(value)
                break
        metadata.add_column(col, sql_type)

    # Build rows
    rows = []
    for record in records:
        row = [record.get(col) for col in columns]
        rows.append(row)

    return ResultSet(metadata, rows)
