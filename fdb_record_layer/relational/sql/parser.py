"""SQL Parser.

Recursive descent parser for SQL statements.
"""

from __future__ import annotations

from fdb_record_layer.relational.sql.ast import (
    AllColumns,
    BetweenExpression,
    BinaryExpression,
    BinaryOp,
    CaseExpression,
    CastExpression,
    ColumnDefinition,
    ColumnReference,
    ComparisonExpression,
    ComparisonOp,
    CreateIndexStatement,
    CreateSchemaStatement,
    CreateTableStatement,
    DataType,
    DataTypeKind,
    DeleteStatement,
    DropIndexStatement,
    DropSchemaStatement,
    DropTableStatement,
    Expression,
    FromClause,
    FunctionCall,
    GroupByClause,
    InExpression,
    InsertStatement,
    JoinClause,
    JoinType,
    Literal,
    NullOrdering,
    OrderByItem,
    Parameter,
    PrimaryKeyConstraint,
    SelectItem,
    SelectStatement,
    SetClause,
    SetOperation,
    SortOrder,
    Statement,
    Subquery,
    TableReference,
    UnaryExpression,
    UnaryOp,
    UpdateStatement,
)
from fdb_record_layer.relational.sql.lexer import Lexer, Token, TokenType


class ParseError(Exception):
    """Raised when parsing fails."""

    def __init__(self, message: str, token: Token) -> None:
        self.token = token
        super().__init__(f"{message} at line {token.line}, column {token.column}")


class RecursionLimitError(ParseError):
    """Raised when parser recursion limit is exceeded."""

    def __init__(self, token: Token) -> None:
        super().__init__("Maximum parsing depth exceeded (possible attack)", token)


class InputTooLargeError(Exception):
    """Raised when SQL input exceeds size limit."""

    def __init__(self, size: int, max_size: int) -> None:
        super().__init__(f"SQL input size ({size} bytes) exceeds maximum ({max_size} bytes)")


# Safety limits
DEFAULT_MAX_RECURSION_DEPTH = 100
DEFAULT_MAX_SQL_SIZE = 1_000_000  # 1 MB


class Parser:
    """SQL Parser using recursive descent.

    Includes safety limits to prevent DoS attacks:
    - Maximum recursion depth for nested expressions
    - Maximum SQL input size

    Example:
        >>> parser = Parser("SELECT * FROM users WHERE id = 1")
        >>> stmt = parser.parse()
    """

    def __init__(
        self,
        sql: str,
        max_depth: int = DEFAULT_MAX_RECURSION_DEPTH,
        max_size: int = DEFAULT_MAX_SQL_SIZE,
    ) -> None:
        """Initialize the parser.

        Args:
            sql: The SQL string to parse.
            max_depth: Maximum recursion depth (default 100).
            max_size: Maximum SQL size in bytes (default 1MB).

        Raises:
            InputTooLargeError: If SQL exceeds max_size.
        """
        # Check input size
        if len(sql) > max_size:
            raise InputTooLargeError(len(sql), max_size)

        self._tokens = Lexer(sql).tokenize()
        self._pos = 0
        self._max_depth = max_depth
        self._current_depth = 0

    def _enter_recursion(self) -> None:
        """Enter a recursive parsing context."""
        self._current_depth += 1
        if self._current_depth > self._max_depth:
            raise RecursionLimitError(self._current())

    def _exit_recursion(self) -> None:
        """Exit a recursive parsing context."""
        self._current_depth -= 1

    def parse(self) -> Statement:
        """Parse a single SQL statement."""
        stmt = self._parse_statement()
        if not self._is_at_end():
            if self._check(TokenType.SEMICOLON):
                self._advance()
            if not self._is_at_end():
                raise ParseError("Unexpected token after statement", self._current())
        return stmt

    def parse_all(self) -> list[Statement]:
        """Parse multiple SQL statements."""
        statements = []
        while not self._is_at_end():
            statements.append(self._parse_statement())
            if self._check(TokenType.SEMICOLON):
                self._advance()
        return statements

    # ========================================================================
    # Statement Parsing
    # ========================================================================

    def _parse_statement(self) -> Statement:
        """Parse a statement."""
        if self._check(TokenType.SELECT):
            return self._parse_select()
        if self._check(TokenType.INSERT):
            return self._parse_insert()
        if self._check(TokenType.UPDATE):
            return self._parse_update()
        if self._check(TokenType.DELETE):
            return self._parse_delete()
        if self._check(TokenType.CREATE):
            return self._parse_create()
        if self._check(TokenType.DROP):
            return self._parse_drop()

        raise ParseError(f"Unexpected token: {self._current().value}", self._current())

    def _parse_select(self) -> SelectStatement:
        """Parse a SELECT statement.

        Tracks recursion depth when parsing subqueries to prevent DoS attacks.
        """
        self._enter_recursion()
        try:
            return self._parse_select_inner()
        finally:
            self._exit_recursion()

    def _parse_select_inner(self) -> SelectStatement:
        """Internal SELECT parsing."""
        self._expect(TokenType.SELECT)

        distinct = False
        if self._match(TokenType.DISTINCT):
            distinct = True
        elif self._match(TokenType.ALL):
            pass  # Default

        # SELECT items
        select_items = self._parse_select_items()

        # FROM clause
        from_clause = None
        if self._match(TokenType.FROM):
            from_clause = self._parse_from_clause()

        # WHERE clause
        where = None
        if self._match(TokenType.WHERE):
            where = self._parse_expression()

        # GROUP BY clause
        group_by = None
        if self._match(TokenType.GROUP):
            self._expect(TokenType.BY)
            group_by = GroupByClause(expressions=self._parse_expression_list())

        # HAVING clause
        having = None
        if self._match(TokenType.HAVING):
            having = self._parse_expression()

        # Set operations (UNION, INTERSECT, EXCEPT)
        set_operation = None
        right_query = None
        if self._check(TokenType.UNION):
            self._advance()
            if self._match(TokenType.ALL):
                set_operation = SetOperation.UNION_ALL
            else:
                set_operation = SetOperation.UNION
            right_query = self._parse_select()
        elif self._match(TokenType.INTERSECT):
            set_operation = SetOperation.INTERSECT
            right_query = self._parse_select()
        elif self._match(TokenType.EXCEPT):
            set_operation = SetOperation.EXCEPT
            right_query = self._parse_select()

        # ORDER BY clause
        order_by = None
        if self._match(TokenType.ORDER):
            self._expect(TokenType.BY)
            order_by = self._parse_order_by()

        # LIMIT clause
        limit = None
        if self._match(TokenType.LIMIT):
            limit = int(self._expect(TokenType.INTEGER).value)

        # OFFSET clause
        offset = None
        if self._match(TokenType.OFFSET):
            offset = int(self._expect(TokenType.INTEGER).value)

        return SelectStatement(
            select_items=select_items,
            from_clause=from_clause,
            where=where,
            group_by=group_by,
            having=having,
            order_by=order_by,
            limit=limit,
            offset=offset,
            distinct=distinct,
            set_operation=set_operation,
            right_query=right_query,
        )

    def _parse_select_items(self) -> list[SelectItem | AllColumns]:
        """Parse SELECT items."""
        items: list[SelectItem | AllColumns] = []

        while True:
            if self._check(TokenType.STAR):
                self._advance()
                items.append(AllColumns())
            elif self._check(TokenType.IDENTIFIER) and self._peek().type == TokenType.DOT:
                # table.* or table.column
                table = self._advance().value
                self._expect(TokenType.DOT)
                if self._check(TokenType.STAR):
                    self._advance()
                    items.append(AllColumns(table=table))
                else:
                    col = self._expect(TokenType.IDENTIFIER).value
                    col_ref = ColumnReference(table=table, column=col)
                    alias = self._parse_alias()
                    items.append(SelectItem(expression=col_ref, alias=alias))
            else:
                parsed_expr = self._parse_expression()
                alias = self._parse_alias()
                items.append(SelectItem(expression=parsed_expr, alias=alias))

            if not self._match(TokenType.COMMA):
                break

        return items

    def _parse_alias(self) -> str | None:
        """Parse an optional alias."""
        if self._match(TokenType.AS):
            return self._expect_identifier().value
        if self._check(TokenType.IDENTIFIER):
            # Alias without AS
            next_token = self._current()
            if next_token.value.upper() not in (
                "FROM",
                "WHERE",
                "GROUP",
                "HAVING",
                "ORDER",
                "LIMIT",
                "OFFSET",
                "UNION",
                "INTERSECT",
                "EXCEPT",
                "JOIN",
                "INNER",
                "LEFT",
                "RIGHT",
                "FULL",
                "CROSS",
                "ON",
            ):
                return self._advance().value
        return None

    def _parse_from_clause(self) -> FromClause:
        """Parse FROM clause."""
        source = self._parse_table_or_subquery()
        alias = self._parse_alias()
        joins = []

        while True:
            join = self._parse_join()
            if join is None:
                break
            joins.append(join)

        return FromClause(source=source, alias=alias, joins=joins)

    def _parse_table_or_subquery(self) -> TableReference | SelectStatement | FromClause:
        """Parse a table reference or subquery."""
        if self._match(TokenType.LPAREN):
            if self._check(TokenType.SELECT):
                query = self._parse_select()
                self._expect(TokenType.RPAREN)
                return query
            else:
                # Parenthesized table reference
                result = self._parse_from_clause()
                self._expect(TokenType.RPAREN)
                return result

        return self._parse_table_reference()

    def _parse_table_reference(self) -> TableReference:
        """Parse a table reference."""
        name = self._expect_identifier().value
        schema = None

        if self._match(TokenType.DOT):
            schema = name
            name = self._expect_identifier().value

        alias = self._parse_alias()
        return TableReference(name=name, schema=schema, alias=alias)

    def _parse_join(self) -> JoinClause | None:
        """Parse a JOIN clause."""
        join_type = None

        if self._match(TokenType.CROSS):
            self._expect(TokenType.JOIN)
            join_type = JoinType.CROSS
        elif self._match(TokenType.INNER):
            self._expect(TokenType.JOIN)
            join_type = JoinType.INNER
        elif self._match(TokenType.LEFT):
            self._match(TokenType.OUTER)
            self._expect(TokenType.JOIN)
            join_type = JoinType.LEFT
        elif self._match(TokenType.RIGHT):
            self._match(TokenType.OUTER)
            self._expect(TokenType.JOIN)
            join_type = JoinType.RIGHT
        elif self._match(TokenType.FULL):
            self._match(TokenType.OUTER)
            self._expect(TokenType.JOIN)
            join_type = JoinType.FULL
        elif self._match(TokenType.JOIN):
            join_type = JoinType.INNER
        else:
            return None

        right = self._parse_from_clause()
        condition = None
        using_columns = None

        if self._match(TokenType.ON):
            condition = self._parse_expression()
        elif self._match(TokenType.USING):
            self._expect(TokenType.LPAREN)
            using_columns = []
            while True:
                using_columns.append(self._expect_identifier().value)
                if not self._match(TokenType.COMMA):
                    break
            self._expect(TokenType.RPAREN)

        return JoinClause(
            join_type=join_type,
            right=right,
            condition=condition,
            using_columns=using_columns,
        )

    def _parse_order_by(self) -> list[OrderByItem]:
        """Parse ORDER BY items."""
        items = []

        while True:
            expr = self._parse_expression()
            order = SortOrder.ASC
            null_ordering = None

            if self._match(TokenType.ASC):
                order = SortOrder.ASC
            elif self._match(TokenType.DESC):
                order = SortOrder.DESC

            if self._match(TokenType.NULLS):
                if self._match(TokenType.FIRST):
                    null_ordering = NullOrdering.NULLS_FIRST
                elif self._match(TokenType.LAST):
                    null_ordering = NullOrdering.NULLS_LAST

            items.append(OrderByItem(expression=expr, order=order, null_ordering=null_ordering))

            if not self._match(TokenType.COMMA):
                break

        return items

    def _parse_insert(self) -> InsertStatement:
        """Parse an INSERT statement."""
        self._expect(TokenType.INSERT)
        self._expect(TokenType.INTO)

        table = self._parse_table_reference()
        columns = None
        values = None
        query = None

        # Optional column list
        if self._match(TokenType.LPAREN):
            columns = []
            while True:
                columns.append(self._expect_identifier().value)
                if not self._match(TokenType.COMMA):
                    break
            self._expect(TokenType.RPAREN)

        if self._match(TokenType.VALUES):
            values = []
            while True:
                self._expect(TokenType.LPAREN)
                row = self._parse_expression_list()
                self._expect(TokenType.RPAREN)
                values.append(row)
                if not self._match(TokenType.COMMA):
                    break
        elif self._check(TokenType.SELECT):
            query = self._parse_select()

        return InsertStatement(table=table, columns=columns, values=values, query=query)

    def _parse_update(self) -> UpdateStatement:
        """Parse an UPDATE statement."""
        self._expect(TokenType.UPDATE)
        table = self._parse_table_reference()
        self._expect(TokenType.SET)

        set_clauses = []
        while True:
            column = self._expect_identifier().value
            self._expect(TokenType.EQ)
            value = self._parse_expression()
            set_clauses.append(SetClause(column=column, value=value))
            if not self._match(TokenType.COMMA):
                break

        where = None
        if self._match(TokenType.WHERE):
            where = self._parse_expression()

        return UpdateStatement(table=table, set_clauses=set_clauses, where=where)

    def _parse_delete(self) -> DeleteStatement:
        """Parse a DELETE statement."""
        self._expect(TokenType.DELETE)
        self._expect(TokenType.FROM)
        table = self._parse_table_reference()

        where = None
        if self._match(TokenType.WHERE):
            where = self._parse_expression()

        return DeleteStatement(table=table, where=where)

    def _parse_create(self) -> Statement:
        """Parse a CREATE statement."""
        self._expect(TokenType.CREATE)

        if self._check(TokenType.UNIQUE) or self._check(TokenType.INDEX):
            return self._parse_create_index()
        if self._check(TokenType.TABLE):
            return self._parse_create_table()
        if self._check(TokenType.SCHEMA) or self._check(TokenType.DATABASE):
            return self._parse_create_schema()

        raise ParseError("Expected TABLE, INDEX, or SCHEMA", self._current())

    def _parse_create_table(self) -> CreateTableStatement:
        """Parse a CREATE TABLE statement."""
        self._expect(TokenType.TABLE)

        if_not_exists = False
        if self._match(TokenType.IF):
            self._expect(TokenType.NOT)
            self._expect(TokenType.EXISTS)
            if_not_exists = True

        name = self._expect_identifier().value
        schema = None
        if self._match(TokenType.DOT):
            schema = name
            name = self._expect_identifier().value

        self._expect(TokenType.LPAREN)
        columns = []
        primary_key = None

        while True:
            if self._match(TokenType.PRIMARY):
                self._expect(TokenType.KEY)
                self._expect(TokenType.LPAREN)
                pk_columns = []
                while True:
                    pk_columns.append(self._expect_identifier().value)
                    if not self._match(TokenType.COMMA):
                        break
                self._expect(TokenType.RPAREN)
                primary_key = PrimaryKeyConstraint(columns=pk_columns)
            else:
                col = self._parse_column_definition()
                columns.append(col)

            if not self._match(TokenType.COMMA):
                break

        self._expect(TokenType.RPAREN)

        return CreateTableStatement(
            name=name,
            schema=schema,
            columns=columns,
            primary_key=primary_key,
            if_not_exists=if_not_exists,
        )

    def _parse_column_definition(self) -> ColumnDefinition:
        """Parse a column definition."""
        name = self._expect_identifier().value
        data_type = self._parse_data_type()
        nullable = True
        primary_key = False
        default = None

        while True:
            if self._match(TokenType.NOT):
                self._expect(TokenType.NULL)
                nullable = False
            elif self._match(TokenType.NULL):
                nullable = True
            elif self._match(TokenType.PRIMARY):
                self._expect(TokenType.KEY)
                primary_key = True
            elif self._match(TokenType.DEFAULT):
                default = self._parse_expression()
            else:
                break

        return ColumnDefinition(
            name=name,
            data_type=data_type,
            nullable=nullable,
            primary_key=primary_key,
            default=default,
        )

    def _parse_data_type(self) -> DataType:
        """Parse a data type."""
        type_map = {
            TokenType.BOOLEAN: DataTypeKind.BOOLEAN,
            TokenType.TINYINT: DataTypeKind.TINYINT,
            TokenType.SMALLINT: DataTypeKind.SMALLINT,
            TokenType.INT: DataTypeKind.INTEGER,
            TokenType.INTEGER_KW: DataTypeKind.INTEGER,
            TokenType.BIGINT: DataTypeKind.BIGINT,
            TokenType.FLOAT_KW: DataTypeKind.FLOAT,
            TokenType.DOUBLE: DataTypeKind.DOUBLE,
            TokenType.DECIMAL: DataTypeKind.DECIMAL,
            TokenType.STRING_KW: DataTypeKind.STRING,
            TokenType.VARCHAR: DataTypeKind.VARCHAR,
            TokenType.CHAR: DataTypeKind.CHAR,
            TokenType.BYTES: DataTypeKind.BYTES,
            TokenType.DATE: DataTypeKind.DATE,
            TokenType.TIME: DataTypeKind.TIME,
            TokenType.TIMESTAMP: DataTypeKind.TIMESTAMP,
        }

        token = self._current()
        if token.type in type_map:
            self._advance()
            kind = type_map[token.type]
            precision = None
            scale = None

            if self._match(TokenType.LPAREN):
                precision = int(self._expect(TokenType.INTEGER).value)
                if self._match(TokenType.COMMA):
                    scale = int(self._expect(TokenType.INTEGER).value)
                self._expect(TokenType.RPAREN)

            return DataType(kind=kind, precision=precision, scale=scale)

        if self._match(TokenType.ARRAY):
            self._expect(TokenType.LT) if self._check(TokenType.LT) else None
            element_type = self._parse_data_type()
            self._expect(TokenType.GT) if self._check(TokenType.GT) else None
            return DataType(kind=DataTypeKind.ARRAY, element_type=element_type)

        raise ParseError(f"Expected data type, got {token.value}", token)

    def _parse_create_index(self) -> CreateIndexStatement:
        """Parse a CREATE INDEX statement."""
        unique = False
        if self._match(TokenType.UNIQUE):
            unique = True

        self._expect(TokenType.INDEX)

        if_not_exists = False
        if self._match(TokenType.IF):
            self._expect(TokenType.NOT)
            self._expect(TokenType.EXISTS)
            if_not_exists = True

        name = self._expect_identifier().value
        self._expect(TokenType.ON)
        table = self._expect_identifier().value

        self._expect(TokenType.LPAREN)
        columns = []
        while True:
            columns.append(self._expect_identifier().value)
            if not self._match(TokenType.COMMA):
                break
        self._expect(TokenType.RPAREN)

        return CreateIndexStatement(
            name=name,
            table=table,
            columns=columns,
            unique=unique,
            if_not_exists=if_not_exists,
        )

    def _parse_create_schema(self) -> CreateSchemaStatement:
        """Parse a CREATE SCHEMA statement."""
        self._advance()  # SCHEMA or DATABASE

        if_not_exists = False
        if self._match(TokenType.IF):
            self._expect(TokenType.NOT)
            self._expect(TokenType.EXISTS)
            if_not_exists = True

        name = self._expect_identifier().value
        return CreateSchemaStatement(name=name, if_not_exists=if_not_exists)

    def _parse_drop(self) -> Statement:
        """Parse a DROP statement."""
        self._expect(TokenType.DROP)

        if self._match(TokenType.TABLE):
            return self._parse_drop_table()
        if self._match(TokenType.INDEX):
            return self._parse_drop_index()
        if self._match(TokenType.SCHEMA) or self._match(TokenType.DATABASE):
            return self._parse_drop_schema()

        raise ParseError("Expected TABLE, INDEX, or SCHEMA", self._current())

    def _parse_drop_table(self) -> DropTableStatement:
        """Parse DROP TABLE."""
        if_exists = False
        if self._match(TokenType.IF):
            self._expect(TokenType.EXISTS)
            if_exists = True

        name = self._expect_identifier().value
        schema = None
        if self._match(TokenType.DOT):
            schema = name
            name = self._expect_identifier().value

        return DropTableStatement(name=name, schema=schema, if_exists=if_exists)

    def _parse_drop_index(self) -> DropIndexStatement:
        """Parse DROP INDEX."""
        if_exists = False
        if self._match(TokenType.IF):
            self._expect(TokenType.EXISTS)
            if_exists = True

        name = self._expect_identifier().value
        return DropIndexStatement(name=name, if_exists=if_exists)

    def _parse_drop_schema(self) -> DropSchemaStatement:
        """Parse DROP SCHEMA."""
        if_exists = False
        cascade = False

        if self._match(TokenType.IF):
            self._expect(TokenType.EXISTS)
            if_exists = True

        name = self._expect_identifier().value

        if self._match(TokenType.CASCADE):
            cascade = True

        return DropSchemaStatement(name=name, if_exists=if_exists, cascade=cascade)

    # ========================================================================
    # Expression Parsing
    # ========================================================================

    def _parse_expression(self) -> Expression:
        """Parse an expression.

        Tracks recursion depth to prevent DoS attacks via deeply nested expressions.
        """
        self._enter_recursion()
        try:
            return self._parse_or_expression()
        finally:
            self._exit_recursion()

    def _parse_or_expression(self) -> Expression:
        """Parse OR expression."""
        left = self._parse_and_expression()

        while self._match(TokenType.OR):
            right = self._parse_and_expression()
            left = BinaryExpression(left=left, operator=BinaryOp.OR, right=right)

        return left

    def _parse_and_expression(self) -> Expression:
        """Parse AND expression."""
        left = self._parse_not_expression()

        while self._match(TokenType.AND):
            right = self._parse_not_expression()
            left = BinaryExpression(left=left, operator=BinaryOp.AND, right=right)

        return left

    def _parse_not_expression(self) -> Expression:
        """Parse NOT expression."""
        if self._match(TokenType.NOT):
            return UnaryExpression(operator=UnaryOp.NOT, operand=self._parse_not_expression())
        return self._parse_comparison_expression()

    def _parse_comparison_expression(self) -> Expression:
        """Parse comparison expression."""
        left = self._parse_additive_expression()

        if self._match(TokenType.EQ):
            right = self._parse_additive_expression()
            return ComparisonExpression(left=left, operator=ComparisonOp.EQ, right=right)
        if self._match(TokenType.NE):
            right = self._parse_additive_expression()
            return ComparisonExpression(left=left, operator=ComparisonOp.NE, right=right)
        if self._match(TokenType.LT):
            right = self._parse_additive_expression()
            return ComparisonExpression(left=left, operator=ComparisonOp.LT, right=right)
        if self._match(TokenType.LE):
            right = self._parse_additive_expression()
            return ComparisonExpression(left=left, operator=ComparisonOp.LE, right=right)
        if self._match(TokenType.GT):
            right = self._parse_additive_expression()
            return ComparisonExpression(left=left, operator=ComparisonOp.GT, right=right)
        if self._match(TokenType.GE):
            right = self._parse_additive_expression()
            return ComparisonExpression(left=left, operator=ComparisonOp.GE, right=right)

        if self._match(TokenType.LIKE):
            right = self._parse_additive_expression()
            return ComparisonExpression(left=left, operator=ComparisonOp.LIKE, right=right)

        if self._check(TokenType.NOT) and self._peek().type == TokenType.LIKE:
            self._advance()
            self._advance()
            right = self._parse_additive_expression()
            return ComparisonExpression(left=left, operator=ComparisonOp.NOT_LIKE, right=right)

        if self._match(TokenType.IS):
            negated = self._match(TokenType.NOT)
            self._expect(TokenType.NULL)
            op = ComparisonOp.IS_NOT_NULL if negated else ComparisonOp.IS_NULL
            return ComparisonExpression(left=left, operator=op)

        if self._check(TokenType.NOT) and self._peek().type in (TokenType.IN, TokenType.BETWEEN):
            self._advance()
            if self._match(TokenType.IN):
                return self._parse_in_expression(left, negated=True)
            if self._match(TokenType.BETWEEN):
                return self._parse_between_expression(left, negated=True)

        if self._match(TokenType.IN):
            return self._parse_in_expression(left, negated=False)

        if self._match(TokenType.BETWEEN):
            return self._parse_between_expression(left, negated=False)

        return left

    def _parse_in_expression(self, left: Expression, negated: bool) -> InExpression:
        """Parse IN expression."""
        self._expect(TokenType.LPAREN)
        values = self._parse_expression_list()
        self._expect(TokenType.RPAREN)
        return InExpression(expression=left, values=values, negated=negated)

    def _parse_between_expression(self, left: Expression, negated: bool) -> BetweenExpression:
        """Parse BETWEEN expression."""
        low = self._parse_additive_expression()
        self._expect(TokenType.AND)
        high = self._parse_additive_expression()
        return BetweenExpression(expression=left, low=low, high=high, negated=negated)

    def _parse_additive_expression(self) -> Expression:
        """Parse additive expression (+, -)."""
        left = self._parse_multiplicative_expression()

        while True:
            if self._match(TokenType.PLUS):
                right = self._parse_multiplicative_expression()
                left = BinaryExpression(left=left, operator=BinaryOp.ADD, right=right)
            elif self._match(TokenType.MINUS):
                right = self._parse_multiplicative_expression()
                left = BinaryExpression(left=left, operator=BinaryOp.SUB, right=right)
            elif self._match(TokenType.CONCAT):
                right = self._parse_multiplicative_expression()
                left = BinaryExpression(left=left, operator=BinaryOp.CONCAT, right=right)
            else:
                break

        return left

    def _parse_multiplicative_expression(self) -> Expression:
        """Parse multiplicative expression (*, /, %)."""
        left = self._parse_unary_expression()

        while True:
            if self._match(TokenType.STAR):
                right = self._parse_unary_expression()
                left = BinaryExpression(left=left, operator=BinaryOp.MUL, right=right)
            elif self._match(TokenType.SLASH):
                right = self._parse_unary_expression()
                left = BinaryExpression(left=left, operator=BinaryOp.DIV, right=right)
            elif self._match(TokenType.PERCENT):
                right = self._parse_unary_expression()
                left = BinaryExpression(left=left, operator=BinaryOp.MOD, right=right)
            else:
                break

        return left

    def _parse_unary_expression(self) -> Expression:
        """Parse unary expression."""
        if self._match(TokenType.MINUS):
            return UnaryExpression(operator=UnaryOp.MINUS, operand=self._parse_unary_expression())
        if self._match(TokenType.PLUS):
            return UnaryExpression(operator=UnaryOp.PLUS, operand=self._parse_unary_expression())
        return self._parse_primary_expression()

    def _parse_primary_expression(self) -> Expression:
        """Parse primary expression."""
        # Literals
        if self._match(TokenType.NULL):
            return Literal.null()
        if self._match(TokenType.TRUE):
            return Literal.boolean(True)
        if self._match(TokenType.FALSE):
            return Literal.boolean(False)
        if self._check(TokenType.INTEGER):
            return Literal.integer(int(self._advance().value))
        if self._check(TokenType.FLOAT):
            return Literal.float_(float(self._advance().value))
        if self._check(TokenType.STRING):
            return Literal.string(self._advance().value)

        # Parameter
        if self._match(TokenType.QUESTION):
            return Parameter()
        if self._match(TokenType.COLON):
            name = self._expect_identifier().value
            return Parameter(name=name)

        # CASE expression
        if self._match(TokenType.CASE):
            return self._parse_case_expression()

        # CAST expression
        if self._match(TokenType.CAST):
            return self._parse_cast_expression()

        # EXISTS
        if self._match(TokenType.EXISTS):
            self._expect(TokenType.LPAREN)
            query = self._parse_select()
            self._expect(TokenType.RPAREN)
            return Subquery(query=query)

        # Parenthesized expression or subquery
        if self._match(TokenType.LPAREN):
            if self._check(TokenType.SELECT):
                query = self._parse_select()
                self._expect(TokenType.RPAREN)
                return Subquery(query=query)
            expr = self._parse_expression()
            self._expect(TokenType.RPAREN)
            return expr

        # Function call or column reference
        if self._check(TokenType.IDENTIFIER) or self._check(TokenType.QUOTED_IDENTIFIER):
            return self._parse_identifier_or_function()

        raise ParseError(f"Unexpected token: {self._current().value}", self._current())

    def _parse_identifier_or_function(self) -> Expression:
        """Parse identifier, column reference, or function call."""
        name = self._advance().value

        # Function call
        if self._match(TokenType.LPAREN):
            distinct = self._match(TokenType.DISTINCT)
            if self._check(TokenType.RPAREN):
                self._advance()
                return FunctionCall(name=name, arguments=[], distinct=distinct)

            if self._check(TokenType.STAR):
                self._advance()
                self._expect(TokenType.RPAREN)
                return FunctionCall(name=name, arguments=[AllColumns()], distinct=distinct)

            expr_args = self._parse_expression_list()
            args: list[Expression | AllColumns] = list(expr_args)
            self._expect(TokenType.RPAREN)
            return FunctionCall(name=name, arguments=args, distinct=distinct)

        # Qualified name (table.column)
        if self._match(TokenType.DOT):
            column = self._expect_identifier().value
            return ColumnReference(table=name, column=column)

        return ColumnReference(table=None, column=name)

    def _parse_case_expression(self) -> CaseExpression:
        """Parse CASE expression."""
        operand = None

        # Simple CASE: CASE expr WHEN ...
        if not self._check(TokenType.WHEN):
            operand = self._parse_expression()

        when_clauses = []
        while self._match(TokenType.WHEN):
            condition = self._parse_expression()
            self._expect(TokenType.THEN)
            result = self._parse_expression()
            when_clauses.append((condition, result))

        else_result = None
        if self._match(TokenType.ELSE):
            else_result = self._parse_expression()

        self._expect(TokenType.END)

        return CaseExpression(
            operand=operand,
            when_clauses=when_clauses,
            else_result=else_result,
        )

    def _parse_cast_expression(self) -> CastExpression:
        """Parse CAST expression."""
        self._expect(TokenType.LPAREN)
        expr = self._parse_expression()
        self._expect(TokenType.AS)
        target_type = self._parse_data_type()
        self._expect(TokenType.RPAREN)
        return CastExpression(expression=expr, target_type=target_type)

    def _parse_expression_list(self) -> list[Expression]:
        """Parse a comma-separated list of expressions."""
        expressions: list[Expression] = [self._parse_expression()]
        while self._match(TokenType.COMMA):
            expressions.append(self._parse_expression())
        return expressions

    # ========================================================================
    # Helper Methods
    # ========================================================================

    def _current(self) -> Token:
        """Get current token."""
        return self._tokens[self._pos]

    def _peek(self, offset: int = 1) -> Token:
        """Peek at token at offset."""
        pos = self._pos + offset
        if pos < len(self._tokens):
            return self._tokens[pos]
        return self._tokens[-1]

    def _is_at_end(self) -> bool:
        """Check if at end of input."""
        return self._current().type == TokenType.EOF

    def _check(self, token_type: TokenType) -> bool:
        """Check if current token is of given type."""
        return self._current().type == token_type

    def _match(self, token_type: TokenType) -> bool:
        """Match and consume token if it's the expected type."""
        if self._check(token_type):
            self._advance()
            return True
        return False

    def _advance(self) -> Token:
        """Advance to next token and return current."""
        token = self._current()
        if not self._is_at_end():
            self._pos += 1
        return token

    def _expect(self, token_type: TokenType) -> Token:
        """Expect and consume a token of given type."""
        if not self._check(token_type):
            raise ParseError(
                f"Expected {token_type.name}, got {self._current().type.name}",
                self._current(),
            )
        return self._advance()

    def _expect_identifier(self) -> Token:
        """Expect and consume an identifier."""
        if self._check(TokenType.IDENTIFIER) or self._check(TokenType.QUOTED_IDENTIFIER):
            return self._advance()
        raise ParseError(
            f"Expected identifier, got {self._current().type.name}",
            self._current(),
        )


def parse(sql: str) -> Statement:
    """Convenience function to parse SQL."""
    return Parser(sql).parse()


def parse_all(sql: str) -> list[Statement]:
    """Parse multiple SQL statements."""
    return Parser(sql).parse_all()
