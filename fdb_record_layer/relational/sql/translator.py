"""SQL to RecordQuery Translator.

Converts SQL AST nodes to RecordQuery objects that can be executed
by the FDB Record Layer.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from .ast import (
    AllColumns,
    BetweenExpression,
    BinaryExpression,
    BinaryOp,
    ColumnReference,
    ComparisonExpression,
    ComparisonOp,
    CreateIndexStatement,
    CreateTableStatement,
    DataType,
    DataTypeKind,
    DeleteStatement,
    Expression,
    FromClause,
    FunctionCall,
    InExpression,
    InsertStatement,
    Literal,
    SelectItem,
    SelectStatement,
    SortOrder,
    Statement,
    TableReference,
    UnaryExpression,
    UnaryOp,
    UpdateStatement,
)
from .types import (
    BIGINT,
    BOOLEAN,
    BYTES,
    DATE,
    DOUBLE,
    FLOAT,
    INT,
    SMALLINT,
    STRING,
    TIME,
    TIMESTAMP,
    TINYINT,
    ArrayType,
    DecimalType,
    SQLType,
    StructType,
    TypeChecker,
)


@dataclass
class TranslationContext:
    """Context for SQL translation.

    Tracks available tables, aliases, and column mappings.
    """

    # Map of alias -> table name
    table_aliases: dict[str, str] = field(default_factory=dict)

    # Map of table.column -> field name
    column_mappings: dict[str, str] = field(default_factory=dict)

    # Map of table name -> record type name
    table_to_record_type: dict[str, str] = field(default_factory=dict)

    # Parameter values
    parameters: dict[str, Any] = field(default_factory=dict)

    # Type checker
    type_checker: TypeChecker = field(default_factory=TypeChecker)


@dataclass
class TranslatedQuery:
    """Result of translating a SQL SELECT statement."""

    # The record types being queried
    record_types: list[str]

    # The filter component (WHERE clause)
    filter: Any | None = None  # QueryComponent

    # Sort specification
    sort_fields: list[tuple[str, bool]] = field(default_factory=list)  # (field, descending)

    # Limit
    limit: int | None = None

    # Offset
    offset: int | None = None

    # Distinct flag
    distinct: bool = False

    # Projection columns
    columns: list[str] = field(default_factory=list)

    # Aggregates: (func, field, alias)
    aggregates: list[tuple[str, str, str | None]] = field(default_factory=list)

    # Group by fields
    group_by: list[str] = field(default_factory=list)


@dataclass
class TranslatedInsert:
    """Result of translating a SQL INSERT statement."""

    record_type: str
    columns: list[str]
    values: list[list[Any]]


@dataclass
class TranslatedUpdate:
    """Result of translating a SQL UPDATE statement."""

    record_type: str
    updates: dict[str, Any]  # field -> value
    filter: Any | None = None


@dataclass
class TranslatedDelete:
    """Result of translating a SQL DELETE statement."""

    record_type: str
    filter: Any | None = None


@dataclass
class TranslatedCreateTable:
    """Result of translating a CREATE TABLE statement."""

    table_name: str
    columns: list[tuple[str, SQLType, bool, Any | None]]  # (name, type, nullable, default)
    primary_key: list[str]


@dataclass
class TranslatedCreateIndex:
    """Result of translating a CREATE INDEX statement."""

    index_name: str
    table_name: str
    columns: list[tuple[str, bool]]  # (column, descending)
    unique: bool = False


def datatype_to_sql_type(data_type: DataType) -> SQLType:
    """Convert AST DataType to SQLType."""
    type_map = {
        DataTypeKind.BOOLEAN: BOOLEAN,
        DataTypeKind.TINYINT: TINYINT,
        DataTypeKind.SMALLINT: SMALLINT,
        DataTypeKind.INTEGER: INT,
        DataTypeKind.BIGINT: BIGINT,
        DataTypeKind.FLOAT: FLOAT,
        DataTypeKind.DOUBLE: DOUBLE,
        DataTypeKind.STRING: STRING,
        DataTypeKind.VARCHAR: STRING,
        DataTypeKind.CHAR: STRING,
        DataTypeKind.BYTES: BYTES,
        DataTypeKind.DATE: DATE,
        DataTypeKind.TIME: TIME,
        DataTypeKind.TIMESTAMP: TIMESTAMP,
    }

    if data_type.kind in type_map:
        return type_map[data_type.kind]

    # Complex types
    if data_type.kind == DataTypeKind.DECIMAL:
        return DecimalType(precision=data_type.precision or 38, scale=data_type.scale or 0)
    if data_type.kind == DataTypeKind.ARRAY:
        if data_type.element_type:
            elem_type = datatype_to_sql_type(data_type.element_type)
        else:
            elem_type = STRING
        return ArrayType(element_type=elem_type)
    if data_type.kind == DataTypeKind.STRUCT:
        return StructType()

    return STRING


class SQLTranslator:
    """Translates SQL AST to RecordQuery operations."""

    def __init__(self, context: TranslationContext | None = None) -> None:
        """Initialize the translator.

        Args:
            context: Optional translation context with table mappings.
        """
        self._context = context or TranslationContext()

    def translate(
        self, statement: Statement
    ) -> (
        TranslatedQuery
        | TranslatedInsert
        | TranslatedUpdate
        | TranslatedDelete
        | TranslatedCreateTable
        | TranslatedCreateIndex
    ):
        """Translate a SQL statement.

        Args:
            statement: The SQL AST node.

        Returns:
            The translated operation.
        """
        if isinstance(statement, SelectStatement):
            return self._translate_select(statement)
        elif isinstance(statement, InsertStatement):
            return self._translate_insert(statement)
        elif isinstance(statement, UpdateStatement):
            return self._translate_update(statement)
        elif isinstance(statement, DeleteStatement):
            return self._translate_delete(statement)
        elif isinstance(statement, CreateTableStatement):
            return self._translate_create_table(statement)
        elif isinstance(statement, CreateIndexStatement):
            return self._translate_create_index(statement)
        else:
            raise ValueError(f"Unsupported statement type: {type(statement).__name__}")

    def _translate_select(self, stmt: SelectStatement) -> TranslatedQuery:
        """Translate a SELECT statement."""
        # Get record types from FROM clause
        record_types = self._get_record_types(stmt.from_clause)

        # Register table aliases from FROM clause
        if stmt.from_clause and isinstance(stmt.from_clause.source, TableReference):
            table_ref = stmt.from_clause.source
            if table_ref.alias:
                self._context.table_aliases[table_ref.alias] = table_ref.name

        # Translate WHERE clause
        filter_component = None
        if stmt.where:
            filter_component = self._translate_expression_to_filter(stmt.where)

        # Translate ORDER BY
        sort_fields: list[tuple[str, bool]] = []
        if stmt.order_by:
            for item in stmt.order_by:
                if isinstance(item.expression, ColumnReference):
                    field_name = item.expression.column
                    descending = item.order == SortOrder.DESC
                    sort_fields.append((field_name, descending))

        # Get projected columns
        columns: list[str] = []
        aggregates: list[tuple[str, str, str | None]] = []

        for select_item in stmt.select_items:
            if isinstance(select_item, AllColumns):
                columns.append("*")
            elif isinstance(select_item, SelectItem):
                if isinstance(select_item.expression, ColumnReference):
                    field_name = select_item.expression.column
                    columns.append(select_item.alias or field_name)
                elif isinstance(select_item.expression, FunctionCall):
                    func = select_item.expression
                    func_name = func.name.upper()
                    if func_name in ("COUNT", "SUM", "AVG", "MIN", "MAX"):
                        # Aggregate function
                        if func.arguments:
                            if isinstance(func.arguments[0], ColumnReference):
                                field_name = func.arguments[0].column
                                aggregates.append((func_name, field_name, select_item.alias))
                            elif isinstance(func.arguments[0], AllColumns):
                                aggregates.append((func_name, "*", select_item.alias))
                        else:
                            aggregates.append((func_name, "*", select_item.alias))

        # Translate GROUP BY
        group_by: list[str] = []
        if stmt.group_by:
            for expr in stmt.group_by.expressions:
                if isinstance(expr, ColumnReference):
                    group_by.append(expr.column)

        return TranslatedQuery(
            record_types=record_types,
            filter=filter_component,
            sort_fields=sort_fields,
            limit=stmt.limit,
            offset=stmt.offset,
            distinct=stmt.distinct,
            columns=columns,
            aggregates=aggregates,
            group_by=group_by,
        )

    def _translate_insert(self, stmt: InsertStatement) -> TranslatedInsert:
        """Translate an INSERT statement."""
        table_name = stmt.table.name
        record_type = self._context.table_to_record_type.get(table_name, table_name)

        # Get column names
        columns = list(stmt.columns) if stmt.columns else []

        # Translate values
        values: list[list[Any]] = []
        if stmt.values:
            for row in stmt.values:
                row_values: list[Any] = []
                for expr in row:
                    row_values.append(self._evaluate_literal(expr))
                values.append(row_values)

        return TranslatedInsert(
            record_type=record_type,
            columns=columns,
            values=values,
        )

    def _translate_update(self, stmt: UpdateStatement) -> TranslatedUpdate:
        """Translate an UPDATE statement."""
        table_name = stmt.table.name
        record_type = self._context.table_to_record_type.get(table_name, table_name)

        # Translate SET clause
        updates: dict[str, Any] = {}
        for set_clause in stmt.set_clauses:
            updates[set_clause.column] = self._evaluate_literal(set_clause.value)

        # Translate WHERE clause
        filter_component = None
        if stmt.where:
            filter_component = self._translate_expression_to_filter(stmt.where)

        return TranslatedUpdate(
            record_type=record_type,
            updates=updates,
            filter=filter_component,
        )

    def _translate_delete(self, stmt: DeleteStatement) -> TranslatedDelete:
        """Translate a DELETE statement."""
        table_name = stmt.table.name
        record_type = self._context.table_to_record_type.get(table_name, table_name)

        # Translate WHERE clause
        filter_component = None
        if stmt.where:
            filter_component = self._translate_expression_to_filter(stmt.where)

        return TranslatedDelete(
            record_type=record_type,
            filter=filter_component,
        )

    def _translate_create_table(self, stmt: CreateTableStatement) -> TranslatedCreateTable:
        """Translate a CREATE TABLE statement."""
        columns: list[tuple[str, SQLType, bool, Any | None]] = []
        primary_key: list[str] = []

        for col_def in stmt.columns:
            sql_type = datatype_to_sql_type(col_def.data_type)
            default_value = None
            if col_def.default:
                default_value = self._evaluate_literal(col_def.default)

            columns.append(
                (
                    col_def.name,
                    sql_type,
                    col_def.nullable,
                    default_value,
                )
            )

            if col_def.primary_key:
                primary_key.append(col_def.name)

        # Check for explicit PRIMARY KEY constraint
        if stmt.primary_key:
            primary_key = list(stmt.primary_key.columns)

        return TranslatedCreateTable(
            table_name=stmt.name,
            columns=columns,
            primary_key=primary_key,
        )

    def _translate_create_index(self, stmt: CreateIndexStatement) -> TranslatedCreateIndex:
        """Translate a CREATE INDEX statement."""
        # For now, assume all columns are ascending
        columns: list[tuple[str, bool]] = [(col, False) for col in stmt.columns]

        return TranslatedCreateIndex(
            index_name=stmt.name,
            table_name=stmt.table,
            columns=columns,
            unique=stmt.unique,
        )

    def _get_record_types(self, from_clause: FromClause | None) -> list[str]:
        """Get record types from FROM clause."""
        record_types = []
        if from_clause and isinstance(from_clause.source, TableReference):
            table_ref = from_clause.source
            table_name = table_ref.name
            record_type = self._context.table_to_record_type.get(table_name, table_name)
            record_types.append(record_type)
        return record_types

    def _resolve_column(self, col_ref: ColumnReference) -> str:
        """Resolve a column reference to a field name."""
        if col_ref.table:
            # Check if it's an alias
            table_name = self._context.table_aliases.get(col_ref.table, col_ref.table)
            full_name = f"{table_name}.{col_ref.column}"

            # Check for explicit mapping
            if full_name in self._context.column_mappings:
                return self._context.column_mappings[full_name]

        # Return just the column name
        return col_ref.column

    def _translate_expression_to_filter(self, expr: Expression) -> Any:
        """Translate a SQL expression to a QueryComponent.

        This creates the filter components that can be used with RecordQuery.
        """
        # Import here to avoid circular imports
        from fdb_record_layer.query.comparisons import Comparison, ComparisonType
        from fdb_record_layer.query.components import (
            AndComponent,
            FieldComponent,
            NotComponent,
        )

        if isinstance(expr, BinaryExpression):
            return self._translate_binary_expression(expr)

        elif isinstance(expr, UnaryExpression):
            if expr.operator == UnaryOp.NOT:
                child = self._translate_expression_to_filter(expr.operand)
                return NotComponent(child=child)
            else:
                raise ValueError(f"Unsupported unary operator in filter: {expr.operator}")

        elif isinstance(expr, ComparisonExpression):
            return self._translate_comparison_expression(expr)

        elif isinstance(expr, InExpression):
            if isinstance(expr.expression, ColumnReference):
                field_name = self._resolve_column(expr.expression)
                values = [self._evaluate_literal(v) for v in expr.values]
                comp_type = ComparisonType.NOT_IN if expr.negated else ComparisonType.IN
                return FieldComponent(field_name, Comparison(comp_type, values))
            raise ValueError("IN requires column reference")

        elif isinstance(expr, BetweenExpression):
            if isinstance(expr.expression, ColumnReference):
                field_name = self._resolve_column(expr.expression)
                low = self._evaluate_literal(expr.low)
                high = self._evaluate_literal(expr.high)

                gte = FieldComponent(
                    field_name, Comparison(ComparisonType.GREATER_THAN_OR_EQUALS, low)
                )
                lte = FieldComponent(
                    field_name, Comparison(ComparisonType.LESS_THAN_OR_EQUALS, high)
                )

                if expr.negated:
                    return NotComponent(child=AndComponent(children=[gte, lte]))
                return AndComponent(children=[gte, lte])
            raise ValueError("BETWEEN requires column reference")

        elif isinstance(expr, Literal):
            # Boolean literal in WHERE clause
            if expr.value is True:
                return None  # Always true - no filter needed
            elif expr.value is False:
                # Always false - will need special handling
                return FieldComponent("_always_false_", Comparison(ComparisonType.EQUALS, True))

        raise ValueError(f"Cannot translate expression to filter: {type(expr).__name__}")

    def _translate_comparison_expression(self, expr: ComparisonExpression) -> Any:
        """Translate a comparison expression."""
        from fdb_record_layer.query.comparisons import Comparison, ComparisonType
        from fdb_record_layer.query.components import (
            FieldComponent,
            NotComponent,
        )

        if isinstance(expr.left, ColumnReference):
            field_name = self._resolve_column(expr.left)

            # Handle IS NULL / IS NOT NULL
            if expr.operator == ComparisonOp.IS_NULL:
                return FieldComponent(field_name, Comparison(ComparisonType.IS_NULL))
            elif expr.operator == ComparisonOp.IS_NOT_NULL:
                return FieldComponent(field_name, Comparison(ComparisonType.IS_NOT_NULL))

            # Handle LIKE
            if expr.operator == ComparisonOp.LIKE:
                if expr.right is None:
                    raise ValueError("LIKE operator requires a pattern")
                pattern = self._evaluate_literal(expr.right)
                if isinstance(pattern, str):
                    if pattern.endswith("%") and not pattern.startswith("%"):
                        comp = Comparison(ComparisonType.STARTS_WITH, pattern[:-1])
                    elif pattern.startswith("%") and pattern.endswith("%"):
                        comp = Comparison(ComparisonType.CONTAINS, pattern[1:-1])
                    elif pattern.startswith("%"):
                        comp = Comparison(ComparisonType.ENDS_WITH, pattern[1:])
                    else:
                        comp = Comparison(ComparisonType.EQUALS, pattern.replace("%", ""))
                    return FieldComponent(field_name, comp)

            elif expr.operator == ComparisonOp.NOT_LIKE:
                if expr.right is None:
                    raise ValueError("NOT LIKE operator requires a pattern")
                pattern = self._evaluate_literal(expr.right)
                if isinstance(pattern, str):
                    if pattern.endswith("%") and not pattern.startswith("%"):
                        comp = Comparison(ComparisonType.STARTS_WITH, pattern[:-1])
                    elif pattern.startswith("%") and pattern.endswith("%"):
                        comp = Comparison(ComparisonType.CONTAINS, pattern[1:-1])
                    elif pattern.startswith("%"):
                        comp = Comparison(ComparisonType.ENDS_WITH, pattern[1:])
                    else:
                        comp = Comparison(ComparisonType.EQUALS, pattern.replace("%", ""))
                    return NotComponent(child=FieldComponent(field_name, comp))

            # Standard comparisons
            if expr.right is None:
                raise ValueError("Comparison operator requires a right operand")
            value = self._evaluate_literal(expr.right)
            comp_type_map = {
                ComparisonOp.EQ: ComparisonType.EQUALS,
                ComparisonOp.NE: ComparisonType.NOT_EQUALS,
                ComparisonOp.LT: ComparisonType.LESS_THAN,
                ComparisonOp.LE: ComparisonType.LESS_THAN_OR_EQUALS,
                ComparisonOp.GT: ComparisonType.GREATER_THAN,
                ComparisonOp.GE: ComparisonType.GREATER_THAN_OR_EQUALS,
            }

            if expr.operator in comp_type_map:
                comp = Comparison(comp_type_map[expr.operator], value)
                return FieldComponent(field_name, comp)

        raise ValueError(f"Cannot translate comparison: {expr}")

    def _translate_binary_expression(self, expr: BinaryExpression) -> Any:
        """Translate a binary expression to a filter component."""
        from fdb_record_layer.query.components import (
            AndComponent,
            OrComponent,
        )

        # Logical operators
        if expr.operator == BinaryOp.AND:
            left = self._translate_expression_to_filter(expr.left)
            right = self._translate_expression_to_filter(expr.right)
            children = []
            if left is not None:
                children.append(left)
            if right is not None:
                children.append(right)
            if not children:
                return None
            if len(children) == 1:
                return children[0]
            return AndComponent(children=children)

        elif expr.operator == BinaryOp.OR:
            left = self._translate_expression_to_filter(expr.left)
            right = self._translate_expression_to_filter(expr.right)
            if left is None:
                return right
            if right is None:
                return left
            return OrComponent(children=[left, right])

        raise ValueError(f"Cannot translate binary expression with operator {expr.operator}")

    def _evaluate_literal(self, expr: Expression) -> Any:
        """Evaluate an expression to a literal value."""
        if isinstance(expr, Literal):
            return expr.value
        elif isinstance(expr, UnaryExpression):
            if expr.operator == UnaryOp.MINUS:
                value = self._evaluate_literal(expr.operand)
                if isinstance(value, (int, float)):
                    return -value
            elif expr.operator == UnaryOp.PLUS:
                return self._evaluate_literal(expr.operand)

        # For non-literals, return the expression itself
        # (to be evaluated at runtime)
        return expr


def translate_sql(
    sql: str, context: TranslationContext | None = None
) -> (
    TranslatedQuery
    | TranslatedInsert
    | TranslatedUpdate
    | TranslatedDelete
    | TranslatedCreateTable
    | TranslatedCreateIndex
):
    """Parse and translate a SQL statement.

    Args:
        sql: The SQL statement text.
        context: Optional translation context.

    Returns:
        The translated operation.
    """
    from .parser import parse

    statement = parse(sql)
    translator = SQLTranslator(context)
    return translator.translate(statement)


def sql_to_record_query(
    sql: str, table_to_record_type: dict[str, str] | None = None
) -> tuple[Any, TranslatedQuery]:
    """Convert a SQL SELECT to a RecordQuery.

    Args:
        sql: The SQL SELECT statement.
        table_to_record_type: Mapping of table names to record type names.

    Returns:
        Tuple of (RecordQuery, TranslatedQuery metadata).
    """
    from fdb_record_layer.expressions.field import FieldKeyExpression
    from fdb_record_layer.query.query import RecordQuery, SortDescriptor

    context = TranslationContext()
    if table_to_record_type:
        context.table_to_record_type = table_to_record_type

    translated = translate_sql(sql, context)

    if not isinstance(translated, TranslatedQuery):
        raise ValueError(f"Expected SELECT statement, got {type(translated).__name__}")

    # Build sort descriptor
    sort = None
    if translated.sort_fields:
        field_name, descending = translated.sort_fields[0]
        sort = SortDescriptor(
            key_expression=FieldKeyExpression(field_name),
            reverse=descending,
        )

    query = RecordQuery(
        record_types=translated.record_types,
        filter=translated.filter,
        sort=sort,
        removes_duplicates=translated.distinct,
    )

    return query, translated
