"""Relational Layer for FDB Record Layer.

Provides SQL interface on top of the FDB Record Layer.
"""

from .database import (
    ExecutionResult,
    RelationalDatabase,
    connect,
)
from .result_set import (
    ColumnMetadata,
    ResultSet,
    ResultSetBuilder,
    ResultSetMetadata,
    Row,
    from_records,
)
from .schema import (
    Column,
    ForeignKey,
    Index,
    Schema,
    SchemaBuilder,
    SchemaTemplate,
    Table,
    schema_from_sql,
)

__all__ = [
    # Database
    "ExecutionResult",
    "RelationalDatabase",
    "connect",
    # Result Set
    "ColumnMetadata",
    "ResultSet",
    "ResultSetBuilder",
    "ResultSetMetadata",
    "Row",
    "from_records",
    # Schema
    "Column",
    "ForeignKey",
    "Index",
    "Schema",
    "SchemaBuilder",
    "SchemaTemplate",
    "Table",
    "schema_from_sql",
]
