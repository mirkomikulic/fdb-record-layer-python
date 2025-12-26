"""SQL Abstract Syntax Tree (AST) nodes.

This module defines the AST nodes for representing parsed SQL statements.
Each node corresponds to a syntactic element in SQL.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from enum import Enum, auto
from typing import Any

# ============================================================================
# Base Classes
# ============================================================================


class ASTNode(ABC):
    """Base class for all AST nodes."""

    @abstractmethod
    def accept(self, visitor: ASTVisitor) -> Any:
        """Accept a visitor for tree traversal."""
        pass


class Statement(ASTNode):
    """Base class for SQL statements."""

    pass


class Expression(ASTNode):
    """Base class for SQL expressions."""

    pass


# ============================================================================
# Literals and Identifiers
# ============================================================================


@dataclass
class Identifier(Expression):
    """An identifier (table name, column name, etc.)."""

    name: str
    quoted: bool = False

    def accept(self, visitor: ASTVisitor) -> Any:
        return visitor.visit_identifier(self)

    def __repr__(self) -> str:
        if self.quoted:
            return f'"{self.name}"'
        return self.name


@dataclass
class QualifiedName(Expression):
    """A qualified name like schema.table or table.column."""

    parts: list[str]

    def accept(self, visitor: ASTVisitor) -> Any:
        return visitor.visit_qualified_name(self)

    @property
    def name(self) -> str:
        return self.parts[-1]

    @property
    def qualifier(self) -> str | None:
        return ".".join(self.parts[:-1]) if len(self.parts) > 1 else None

    def __repr__(self) -> str:
        return ".".join(self.parts)


class LiteralType(Enum):
    """Types of literal values."""

    NULL = auto()
    BOOLEAN = auto()
    INTEGER = auto()
    FLOAT = auto()
    STRING = auto()


@dataclass
class Literal(Expression):
    """A literal value."""

    value: Any
    literal_type: LiteralType

    def accept(self, visitor: ASTVisitor) -> Any:
        return visitor.visit_literal(self)

    @classmethod
    def null(cls) -> Literal:
        return cls(value=None, literal_type=LiteralType.NULL)

    @classmethod
    def boolean(cls, value: bool) -> Literal:
        return cls(value=value, literal_type=LiteralType.BOOLEAN)

    @classmethod
    def integer(cls, value: int) -> Literal:
        return cls(value=value, literal_type=LiteralType.INTEGER)

    @classmethod
    def float_(cls, value: float) -> Literal:
        return cls(value=value, literal_type=LiteralType.FLOAT)

    @classmethod
    def string(cls, value: str) -> Literal:
        return cls(value=value, literal_type=LiteralType.STRING)

    def __repr__(self) -> str:
        if self.literal_type == LiteralType.NULL:
            return "NULL"
        if self.literal_type == LiteralType.STRING:
            return f"'{self.value}'"
        if self.literal_type == LiteralType.BOOLEAN:
            return "TRUE" if self.value else "FALSE"
        return str(self.value)


@dataclass
class Parameter(Expression):
    """A parameter placeholder (? or $name)."""

    name: str | None = None
    position: int | None = None

    def accept(self, visitor: ASTVisitor) -> Any:
        return visitor.visit_parameter(self)

    def __repr__(self) -> str:
        if self.name:
            return f"${self.name}"
        return "?"


# ============================================================================
# Operators and Expressions
# ============================================================================


class ComparisonOp(Enum):
    """Comparison operators."""

    EQ = "="
    NE = "!="
    LT = "<"
    LE = "<="
    GT = ">"
    GE = ">="
    LIKE = "LIKE"
    NOT_LIKE = "NOT LIKE"
    IN = "IN"
    NOT_IN = "NOT IN"
    IS_NULL = "IS NULL"
    IS_NOT_NULL = "IS NOT NULL"
    BETWEEN = "BETWEEN"


class BinaryOp(Enum):
    """Binary operators."""

    ADD = "+"
    SUB = "-"
    MUL = "*"
    DIV = "/"
    MOD = "%"
    AND = "AND"
    OR = "OR"
    CONCAT = "||"


class UnaryOp(Enum):
    """Unary operators."""

    NOT = "NOT"
    MINUS = "-"
    PLUS = "+"


@dataclass
class BinaryExpression(Expression):
    """A binary expression (left op right)."""

    left: Expression
    operator: BinaryOp
    right: Expression

    def accept(self, visitor: ASTVisitor) -> Any:
        return visitor.visit_binary_expression(self)

    def __repr__(self) -> str:
        return f"({self.left} {self.operator.value} {self.right})"


@dataclass
class UnaryExpression(Expression):
    """A unary expression (op operand)."""

    operator: UnaryOp
    operand: Expression

    def accept(self, visitor: ASTVisitor) -> Any:
        return visitor.visit_unary_expression(self)

    def __repr__(self) -> str:
        return f"({self.operator.value} {self.operand})"


@dataclass
class ComparisonExpression(Expression):
    """A comparison expression (left op right)."""

    left: Expression
    operator: ComparisonOp
    right: Expression | None = None  # None for IS NULL, IS NOT NULL
    right2: Expression | None = None  # For BETWEEN

    def accept(self, visitor: ASTVisitor) -> Any:
        return visitor.visit_comparison_expression(self)

    def __repr__(self) -> str:
        if self.operator in (ComparisonOp.IS_NULL, ComparisonOp.IS_NOT_NULL):
            return f"({self.left} {self.operator.value})"
        if self.operator == ComparisonOp.BETWEEN:
            return f"({self.left} BETWEEN {self.right} AND {self.right2})"
        return f"({self.left} {self.operator.value} {self.right})"


@dataclass
class InExpression(Expression):
    """An IN expression (expr IN (values))."""

    expression: Expression
    values: list[Expression]
    negated: bool = False

    def accept(self, visitor: ASTVisitor) -> Any:
        return visitor.visit_in_expression(self)

    def __repr__(self) -> str:
        op = "NOT IN" if self.negated else "IN"
        vals = ", ".join(str(v) for v in self.values)
        return f"({self.expression} {op} ({vals}))"


@dataclass
class BetweenExpression(Expression):
    """A BETWEEN expression."""

    expression: Expression
    low: Expression
    high: Expression
    negated: bool = False

    def accept(self, visitor: ASTVisitor) -> Any:
        return visitor.visit_between_expression(self)

    def __repr__(self) -> str:
        op = "NOT BETWEEN" if self.negated else "BETWEEN"
        return f"({self.expression} {op} {self.low} AND {self.high})"


@dataclass
class CaseExpression(Expression):
    """A CASE expression."""

    operand: Expression | None  # Simple CASE
    when_clauses: list[tuple[Expression, Expression]]  # (condition, result)
    else_result: Expression | None

    def accept(self, visitor: ASTVisitor) -> Any:
        return visitor.visit_case_expression(self)


@dataclass
class FunctionCall(Expression):
    """A function call."""

    name: str
    arguments: list[Expression | AllColumns]
    distinct: bool = False

    def accept(self, visitor: ASTVisitor) -> Any:
        return visitor.visit_function_call(self)

    def __repr__(self) -> str:
        args = ", ".join(str(a) for a in self.arguments)
        distinct = "DISTINCT " if self.distinct else ""
        return f"{self.name}({distinct}{args})"


@dataclass
class CastExpression(Expression):
    """A CAST expression."""

    expression: Expression
    target_type: DataType

    def accept(self, visitor: ASTVisitor) -> Any:
        return visitor.visit_cast_expression(self)

    def __repr__(self) -> str:
        return f"CAST({self.expression} AS {self.target_type})"


@dataclass
class ColumnReference(Expression):
    """A reference to a column."""

    table: str | None
    column: str

    def accept(self, visitor: ASTVisitor) -> Any:
        return visitor.visit_column_reference(self)

    def __repr__(self) -> str:
        if self.table:
            return f"{self.table}.{self.column}"
        return self.column


@dataclass
class Subquery(Expression):
    """A subquery expression."""

    query: SelectStatement

    def accept(self, visitor: ASTVisitor) -> Any:
        return visitor.visit_subquery(self)


@dataclass
class ExistsExpression(Expression):
    """An EXISTS expression."""

    subquery: SelectStatement
    negated: bool = False

    def accept(self, visitor: ASTVisitor) -> Any:
        return visitor.visit_exists_expression(self)


# ============================================================================
# Data Types
# ============================================================================


class DataTypeKind(Enum):
    """SQL data type kinds."""

    BOOLEAN = "BOOLEAN"
    TINYINT = "TINYINT"
    SMALLINT = "SMALLINT"
    INTEGER = "INTEGER"
    BIGINT = "BIGINT"
    FLOAT = "FLOAT"
    DOUBLE = "DOUBLE"
    DECIMAL = "DECIMAL"
    STRING = "STRING"
    VARCHAR = "VARCHAR"
    CHAR = "CHAR"
    BYTES = "BYTES"
    DATE = "DATE"
    TIME = "TIME"
    TIMESTAMP = "TIMESTAMP"
    ARRAY = "ARRAY"
    STRUCT = "STRUCT"
    MAP = "MAP"


@dataclass
class DataType:
    """A SQL data type."""

    kind: DataTypeKind
    precision: int | None = None
    scale: int | None = None
    element_type: DataType | None = None  # For ARRAY
    fields: list[tuple[str, DataType]] | None = None  # For STRUCT

    def __repr__(self) -> str:
        if self.kind == DataTypeKind.ARRAY:
            return f"ARRAY<{self.element_type}>"
        if self.kind == DataTypeKind.STRUCT:
            fields = ", ".join(f"{n} {t}" for n, t in (self.fields or []))
            return f"STRUCT<{fields}>"
        if self.precision is not None and self.scale is not None:
            return f"{self.kind.value}({self.precision}, {self.scale})"
        if self.precision is not None:
            return f"{self.kind.value}({self.precision})"
        return self.kind.value


# ============================================================================
# SELECT Statement
# ============================================================================


class JoinType(Enum):
    """Types of joins."""

    INNER = "INNER"
    LEFT = "LEFT"
    RIGHT = "RIGHT"
    FULL = "FULL"
    CROSS = "CROSS"


class SetOperation(Enum):
    """Set operations."""

    UNION = "UNION"
    UNION_ALL = "UNION ALL"
    INTERSECT = "INTERSECT"
    EXCEPT = "EXCEPT"


class SortOrder(Enum):
    """Sort order."""

    ASC = "ASC"
    DESC = "DESC"


class NullOrdering(Enum):
    """Null ordering."""

    NULLS_FIRST = "NULLS FIRST"
    NULLS_LAST = "NULLS LAST"


@dataclass
class SelectItem:
    """A single item in the SELECT list."""

    expression: Expression
    alias: str | None = None

    def __repr__(self) -> str:
        if self.alias:
            return f"{self.expression} AS {self.alias}"
        return str(self.expression)


@dataclass
class AllColumns:
    """SELECT * or table.*"""

    table: str | None = None

    def __repr__(self) -> str:
        if self.table:
            return f"{self.table}.*"
        return "*"


@dataclass
class TableReference(ASTNode):
    """A table reference in FROM clause."""

    name: str
    schema: str | None = None
    alias: str | None = None

    def accept(self, visitor: ASTVisitor) -> Any:
        return visitor.visit_table_reference(self)

    def __repr__(self) -> str:
        full_name = f"{self.schema}.{self.name}" if self.schema else self.name
        if self.alias:
            return f"{full_name} AS {self.alias}"
        return full_name


@dataclass
class JoinClause(ASTNode):
    """A JOIN clause."""

    join_type: JoinType
    right: FromClause
    condition: Expression | None = None  # ON condition
    using_columns: list[str] | None = None  # USING columns

    def accept(self, visitor: ASTVisitor) -> Any:
        return visitor.visit_join_clause(self)


@dataclass
class FromClause(ASTNode):
    """A FROM clause element."""

    source: TableReference | SelectStatement | FromClause
    alias: str | None = None
    joins: list[JoinClause] = field(default_factory=list)

    def accept(self, visitor: ASTVisitor) -> Any:
        return visitor.visit_from_clause(self)


@dataclass
class OrderByItem:
    """An ORDER BY item."""

    expression: Expression
    order: SortOrder = SortOrder.ASC
    null_ordering: NullOrdering | None = None

    def __repr__(self) -> str:
        result = f"{self.expression} {self.order.value}"
        if self.null_ordering:
            result += f" {self.null_ordering.value}"
        return result


@dataclass
class GroupByClause:
    """A GROUP BY clause."""

    expressions: list[Expression]


@dataclass
class SelectStatement(Statement):
    """A SELECT statement."""

    select_items: list[SelectItem | AllColumns]
    from_clause: FromClause | None = None
    where: Expression | None = None
    group_by: GroupByClause | None = None
    having: Expression | None = None
    order_by: list[OrderByItem] | None = None
    limit: int | None = None
    offset: int | None = None
    distinct: bool = False

    # Set operations
    set_operation: SetOperation | None = None
    right_query: SelectStatement | None = None

    def accept(self, visitor: ASTVisitor) -> Any:
        return visitor.visit_select_statement(self)

    def __repr__(self) -> str:
        parts = ["SELECT"]
        if self.distinct:
            parts.append("DISTINCT")

        items = ", ".join(str(i) for i in self.select_items)
        parts.append(items)

        if self.from_clause:
            parts.append(f"FROM {self.from_clause.source}")

        if self.where:
            parts.append(f"WHERE {self.where}")

        if self.group_by:
            exprs = ", ".join(str(e) for e in self.group_by.expressions)
            parts.append(f"GROUP BY {exprs}")

        if self.having:
            parts.append(f"HAVING {self.having}")

        if self.order_by:
            order = ", ".join(str(o) for o in self.order_by)
            parts.append(f"ORDER BY {order}")

        if self.limit is not None:
            parts.append(f"LIMIT {self.limit}")

        if self.offset is not None:
            parts.append(f"OFFSET {self.offset}")

        return " ".join(parts)


# ============================================================================
# INSERT Statement
# ============================================================================


@dataclass
class InsertStatement(Statement):
    """An INSERT statement."""

    table: TableReference
    columns: list[str] | None = None
    values: list[list[Expression]] | None = None  # VALUES clause
    query: SelectStatement | None = None  # INSERT ... SELECT

    def accept(self, visitor: ASTVisitor) -> Any:
        return visitor.visit_insert_statement(self)

    def __repr__(self) -> str:
        parts = [f"INSERT INTO {self.table}"]
        if self.columns:
            cols = ", ".join(self.columns)
            parts.append(f"({cols})")
        if self.values:
            rows = []
            for row in self.values:
                vals = ", ".join(str(v) for v in row)
                rows.append(f"({vals})")
            parts.append(f"VALUES {', '.join(rows)}")
        elif self.query:
            parts.append(str(self.query))
        return " ".join(parts)


# ============================================================================
# UPDATE Statement
# ============================================================================


@dataclass
class SetClause:
    """A SET clause in UPDATE."""

    column: str
    value: Expression


@dataclass
class UpdateStatement(Statement):
    """An UPDATE statement."""

    table: TableReference
    set_clauses: list[SetClause]
    where: Expression | None = None

    def accept(self, visitor: ASTVisitor) -> Any:
        return visitor.visit_update_statement(self)

    def __repr__(self) -> str:
        parts = [f"UPDATE {self.table} SET"]
        sets = ", ".join(f"{s.column} = {s.value}" for s in self.set_clauses)
        parts.append(sets)
        if self.where:
            parts.append(f"WHERE {self.where}")
        return " ".join(parts)


# ============================================================================
# DELETE Statement
# ============================================================================


@dataclass
class DeleteStatement(Statement):
    """A DELETE statement."""

    table: TableReference
    where: Expression | None = None

    def accept(self, visitor: ASTVisitor) -> Any:
        return visitor.visit_delete_statement(self)

    def __repr__(self) -> str:
        parts = [f"DELETE FROM {self.table}"]
        if self.where:
            parts.append(f"WHERE {self.where}")
        return " ".join(parts)


# ============================================================================
# DDL Statements
# ============================================================================


@dataclass
class ColumnDefinition:
    """A column definition in CREATE TABLE."""

    name: str
    data_type: DataType
    nullable: bool = True
    primary_key: bool = False
    default: Expression | None = None

    def __repr__(self) -> str:
        parts = [self.name, str(self.data_type)]
        if not self.nullable:
            parts.append("NOT NULL")
        if self.primary_key:
            parts.append("PRIMARY KEY")
        if self.default:
            parts.append(f"DEFAULT {self.default}")
        return " ".join(parts)


@dataclass
class PrimaryKeyConstraint:
    """A PRIMARY KEY constraint."""

    columns: list[str]
    name: str | None = None


@dataclass
class ForeignKeyConstraint:
    """A FOREIGN KEY constraint."""

    columns: list[str]
    ref_table: str
    ref_columns: list[str]
    name: str | None = None


@dataclass
class CreateTableStatement(Statement):
    """A CREATE TABLE statement."""

    name: str
    schema: str | None = None
    columns: list[ColumnDefinition] = field(default_factory=list)
    primary_key: PrimaryKeyConstraint | None = None
    foreign_keys: list[ForeignKeyConstraint] = field(default_factory=list)
    if_not_exists: bool = False

    def accept(self, visitor: ASTVisitor) -> Any:
        return visitor.visit_create_table_statement(self)

    def __repr__(self) -> str:
        parts = ["CREATE TABLE"]
        if self.if_not_exists:
            parts.append("IF NOT EXISTS")
        name = f"{self.schema}.{self.name}" if self.schema else self.name
        parts.append(name)
        cols = ", ".join(str(c) for c in self.columns)
        parts.append(f"({cols})")
        return " ".join(parts)


@dataclass
class DropTableStatement(Statement):
    """A DROP TABLE statement."""

    name: str
    schema: str | None = None
    if_exists: bool = False

    def accept(self, visitor: ASTVisitor) -> Any:
        return visitor.visit_drop_table_statement(self)


@dataclass
class CreateIndexStatement(Statement):
    """A CREATE INDEX statement."""

    name: str
    table: str
    columns: list[str]
    unique: bool = False
    if_not_exists: bool = False

    def accept(self, visitor: ASTVisitor) -> Any:
        return visitor.visit_create_index_statement(self)

    def __repr__(self) -> str:
        parts = ["CREATE"]
        if self.unique:
            parts.append("UNIQUE")
        parts.append("INDEX")
        if self.if_not_exists:
            parts.append("IF NOT EXISTS")
        parts.append(self.name)
        parts.append(f"ON {self.table}")
        cols = ", ".join(self.columns)
        parts.append(f"({cols})")
        return " ".join(parts)


@dataclass
class DropIndexStatement(Statement):
    """A DROP INDEX statement."""

    name: str
    if_exists: bool = False

    def accept(self, visitor: ASTVisitor) -> Any:
        return visitor.visit_drop_index_statement(self)


# ============================================================================
# Schema Statements
# ============================================================================


@dataclass
class CreateSchemaStatement(Statement):
    """A CREATE SCHEMA statement."""

    name: str
    if_not_exists: bool = False

    def accept(self, visitor: ASTVisitor) -> Any:
        return visitor.visit_create_schema_statement(self)


@dataclass
class DropSchemaStatement(Statement):
    """A DROP SCHEMA statement."""

    name: str
    if_exists: bool = False
    cascade: bool = False

    def accept(self, visitor: ASTVisitor) -> Any:
        return visitor.visit_drop_schema_statement(self)


# ============================================================================
# Visitor Pattern
# ============================================================================


class ASTVisitor(ABC):
    """Visitor for traversing the AST."""

    def visit_identifier(self, node: Identifier) -> Any:
        pass

    def visit_qualified_name(self, node: QualifiedName) -> Any:
        pass

    def visit_literal(self, node: Literal) -> Any:
        pass

    def visit_parameter(self, node: Parameter) -> Any:
        pass

    def visit_binary_expression(self, node: BinaryExpression) -> Any:
        pass

    def visit_unary_expression(self, node: UnaryExpression) -> Any:
        pass

    def visit_comparison_expression(self, node: ComparisonExpression) -> Any:
        pass

    def visit_in_expression(self, node: InExpression) -> Any:
        pass

    def visit_between_expression(self, node: BetweenExpression) -> Any:
        pass

    def visit_case_expression(self, node: CaseExpression) -> Any:
        pass

    def visit_function_call(self, node: FunctionCall) -> Any:
        pass

    def visit_cast_expression(self, node: CastExpression) -> Any:
        pass

    def visit_column_reference(self, node: ColumnReference) -> Any:
        pass

    def visit_subquery(self, node: Subquery) -> Any:
        pass

    def visit_exists_expression(self, node: ExistsExpression) -> Any:
        pass

    def visit_table_reference(self, node: TableReference) -> Any:
        pass

    def visit_join_clause(self, node: JoinClause) -> Any:
        pass

    def visit_from_clause(self, node: FromClause) -> Any:
        pass

    def visit_select_statement(self, node: SelectStatement) -> Any:
        pass

    def visit_insert_statement(self, node: InsertStatement) -> Any:
        pass

    def visit_update_statement(self, node: UpdateStatement) -> Any:
        pass

    def visit_delete_statement(self, node: DeleteStatement) -> Any:
        pass

    def visit_create_table_statement(self, node: CreateTableStatement) -> Any:
        pass

    def visit_drop_table_statement(self, node: DropTableStatement) -> Any:
        pass

    def visit_create_index_statement(self, node: CreateIndexStatement) -> Any:
        pass

    def visit_drop_index_statement(self, node: DropIndexStatement) -> Any:
        pass

    def visit_create_schema_statement(self, node: CreateSchemaStatement) -> Any:
        pass

    def visit_drop_schema_statement(self, node: DropSchemaStatement) -> Any:
        pass
