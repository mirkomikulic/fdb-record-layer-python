"""Tests for SQL lexer."""

from fdb_record_layer.relational.sql.lexer import (
    Lexer,
    Token,
    TokenType,
    tokenize,
)


class TestTokenType:
    """Tests for TokenType enum."""

    def test_keyword_types_exist(self):
        """Test keyword token types exist."""
        assert TokenType.SELECT is not None
        assert TokenType.FROM is not None
        assert TokenType.WHERE is not None
        assert TokenType.INSERT is not None
        assert TokenType.UPDATE is not None
        assert TokenType.DELETE is not None

    def test_operator_types_exist(self):
        """Test operator token types exist."""
        assert TokenType.EQ is not None
        assert TokenType.NE is not None
        assert TokenType.LT is not None
        assert TokenType.GT is not None
        assert TokenType.LE is not None
        assert TokenType.GE is not None

    def test_literal_types_exist(self):
        """Test literal token types exist."""
        assert TokenType.INTEGER is not None
        assert TokenType.FLOAT is not None
        assert TokenType.STRING is not None
        assert TokenType.IDENTIFIER is not None

    def test_delimiter_types_exist(self):
        """Test delimiter token types exist."""
        assert TokenType.LPAREN is not None
        assert TokenType.RPAREN is not None
        assert TokenType.COMMA is not None
        assert TokenType.DOT is not None
        assert TokenType.SEMICOLON is not None


class TestToken:
    """Tests for Token dataclass."""

    def test_token_creation(self):
        """Test token creation."""
        token = Token(
            type=TokenType.SELECT,
            value="SELECT",
            line=1,
            column=1,
        )
        assert token.type == TokenType.SELECT
        assert token.value == "SELECT"
        assert token.line == 1
        assert token.column == 1

    def test_token_repr(self):
        """Test token string representation."""
        token = Token(TokenType.SELECT, "SELECT", 1, 1)
        repr_str = repr(token)
        assert "SELECT" in repr_str


class TestLexer:
    """Tests for Lexer class."""

    def test_empty_input(self):
        """Test lexer with empty input."""
        lexer = Lexer("")
        tokens = lexer.tokenize()
        assert len(tokens) == 1
        assert tokens[0].type == TokenType.EOF

    def test_whitespace_only(self):
        """Test lexer with whitespace only returns only EOF."""
        lexer = Lexer("   \n\t  ")
        tokens = lexer.tokenize()
        # Should only have EOF token(s)
        assert all(t.type == TokenType.EOF for t in tokens)

    def test_select_keyword(self):
        """Test lexer recognizes SELECT keyword."""
        lexer = Lexer("SELECT")
        tokens = lexer.tokenize()
        assert tokens[0].type == TokenType.SELECT
        assert tokens[0].value == "SELECT"

    def test_case_insensitive_keywords(self):
        """Test keywords are case insensitive."""
        for keyword in ["SELECT", "select", "Select", "sElEcT"]:
            lexer = Lexer(keyword)
            tokens = lexer.tokenize()
            assert tokens[0].type == TokenType.SELECT

    def test_identifier(self):
        """Test lexer recognizes identifiers."""
        lexer = Lexer("my_table")
        tokens = lexer.tokenize()
        assert tokens[0].type == TokenType.IDENTIFIER
        assert tokens[0].value == "my_table"

    def test_identifier_with_numbers(self):
        """Test identifier can contain numbers."""
        lexer = Lexer("table123")
        tokens = lexer.tokenize()
        assert tokens[0].type == TokenType.IDENTIFIER
        assert tokens[0].value == "table123"

    def test_quoted_identifier(self):
        """Test quoted identifier."""
        lexer = Lexer('"my table"')
        tokens = lexer.tokenize()
        assert tokens[0].type == TokenType.QUOTED_IDENTIFIER
        assert tokens[0].value == "my table"

    def test_integer_literal(self):
        """Test integer literal."""
        lexer = Lexer("12345")
        tokens = lexer.tokenize()
        assert tokens[0].type == TokenType.INTEGER
        assert tokens[0].value == "12345"

    def test_negative_integer(self):
        """Test negative integer as minus operator + integer."""
        lexer = Lexer("-123")
        tokens = lexer.tokenize()
        assert tokens[0].type == TokenType.MINUS
        assert tokens[1].type == TokenType.INTEGER

    def test_float_literal(self):
        """Test float literal."""
        lexer = Lexer("123.456")
        tokens = lexer.tokenize()
        assert tokens[0].type == TokenType.FLOAT
        assert tokens[0].value == "123.456"

    def test_float_with_exponent(self):
        """Test float literal with exponent."""
        lexer = Lexer("1.5e10")
        tokens = lexer.tokenize()
        assert tokens[0].type == TokenType.FLOAT
        assert tokens[0].value == "1.5e10"

    def test_string_literal_single_quotes(self):
        """Test string literal with single quotes."""
        lexer = Lexer("'hello world'")
        tokens = lexer.tokenize()
        assert tokens[0].type == TokenType.STRING
        assert tokens[0].value == "hello world"

    def test_string_literal_escaped_quote(self):
        """Test string with escaped quote."""
        lexer = Lexer("'it''s a test'")
        tokens = lexer.tokenize()
        assert tokens[0].type == TokenType.STRING
        assert tokens[0].value == "it's a test"

    def test_operators(self):
        """Test operator tokens."""
        operators = [
            ("=", TokenType.EQ),
            ("<>", TokenType.NE),
            ("!=", TokenType.NE),
            ("<", TokenType.LT),
            (">", TokenType.GT),
            ("<=", TokenType.LE),
            (">=", TokenType.GE),
            ("+", TokenType.PLUS),
            ("-", TokenType.MINUS),
            ("*", TokenType.STAR),
            ("/", TokenType.SLASH),
            ("%", TokenType.PERCENT),
            ("||", TokenType.CONCAT),
        ]
        for op, expected_type in operators:
            lexer = Lexer(op)
            tokens = lexer.tokenize()
            assert tokens[0].type == expected_type, f"Failed for operator {op}"

    def test_punctuation(self):
        """Test punctuation tokens."""
        punctuation = [
            ("(", TokenType.LPAREN),
            (")", TokenType.RPAREN),
            (",", TokenType.COMMA),
            (";", TokenType.SEMICOLON),
            (".", TokenType.DOT),
            ("[", TokenType.LBRACKET),
            ("]", TokenType.RBRACKET),
            (":", TokenType.COLON),
            ("?", TokenType.QUESTION),
        ]
        for punct, expected_type in punctuation:
            lexer = Lexer(punct)
            tokens = lexer.tokenize()
            assert tokens[0].type == expected_type

    def test_simple_select_statement(self):
        """Test tokenizing a simple SELECT statement."""
        lexer = Lexer("SELECT * FROM users")
        tokens = lexer.tokenize()

        assert tokens[0].type == TokenType.SELECT
        assert tokens[1].type == TokenType.STAR
        assert tokens[2].type == TokenType.FROM
        assert tokens[3].type == TokenType.IDENTIFIER
        assert tokens[3].value == "users"
        assert tokens[4].type == TokenType.EOF

    def test_select_with_where(self):
        """Test SELECT with WHERE clause."""
        lexer = Lexer("SELECT id FROM users WHERE age > 18")
        tokens = lexer.tokenize()

        token_types = [t.type for t in tokens]
        assert TokenType.SELECT in token_types
        assert TokenType.FROM in token_types
        assert TokenType.WHERE in token_types
        assert TokenType.GT in token_types
        assert TokenType.INTEGER in token_types

    def test_insert_statement(self):
        """Test INSERT statement."""
        lexer = Lexer("INSERT INTO users (id, name) VALUES (1, 'John')")
        tokens = lexer.tokenize()

        token_types = [t.type for t in tokens]
        assert TokenType.INSERT in token_types
        assert TokenType.INTO in token_types
        assert TokenType.VALUES in token_types

    def test_line_tracking(self):
        """Test line number tracking."""
        lexer = Lexer("SELECT\n*\nFROM\nusers")
        tokens = lexer.tokenize()

        assert tokens[0].line == 1  # SELECT
        assert tokens[1].line == 2  # *
        assert tokens[2].line == 3  # FROM
        assert tokens[3].line == 4  # users

    def test_column_tracking(self):
        """Test column number tracking."""
        lexer = Lexer("SELECT id FROM users")
        tokens = lexer.tokenize()

        # Column tracking starts at 1
        assert tokens[0].column == 1  # SELECT
        assert tokens[1].column == 8  # id

    def test_comments_single_line(self):
        """Test single-line comments are skipped."""
        lexer = Lexer("SELECT -- this is a comment\n* FROM users")
        tokens = lexer.tokenize()

        token_types = [t.type for t in tokens]
        assert TokenType.SELECT in token_types
        assert TokenType.STAR in token_types
        assert TokenType.FROM in token_types

    def test_comments_multi_line(self):
        """Test multi-line comments are skipped."""
        lexer = Lexer("SELECT /* comment */ * FROM users")
        tokens = lexer.tokenize()

        token_types = [t.type for t in tokens]
        assert TokenType.SELECT in token_types
        assert TokenType.STAR in token_types
        assert TokenType.FROM in token_types

    def test_all_keywords(self):
        """Test all SQL keywords are recognized."""
        keywords = [
            "SELECT",
            "FROM",
            "WHERE",
            "AND",
            "OR",
            "NOT",
            "INSERT",
            "INTO",
            "VALUES",
            "UPDATE",
            "SET",
            "DELETE",
            "CREATE",
            "DROP",
            "TABLE",
            "INDEX",
            "SCHEMA",
            "JOIN",
            "LEFT",
            "RIGHT",
            "INNER",
            "OUTER",
            "ON",
            "ORDER",
            "BY",
            "ASC",
            "DESC",
            "LIMIT",
            "OFFSET",
            "GROUP",
            "HAVING",
            "DISTINCT",
            "AS",
            "NULL",
            "TRUE",
            "FALSE",
            "IN",
            "BETWEEN",
            "LIKE",
            "IS",
            "CASE",
            "WHEN",
            "THEN",
            "ELSE",
            "END",
            "CAST",
        ]
        for keyword in keywords:
            lexer = Lexer(keyword)
            tokens = lexer.tokenize()
            assert tokens[0].type != TokenType.IDENTIFIER, f"{keyword} not recognized as keyword"


class TestTokenizeFunction:
    """Tests for tokenize convenience function."""

    def test_tokenize_function(self):
        """Test tokenize convenience function."""
        tokens = tokenize("SELECT * FROM users")
        assert len(tokens) > 0
        assert tokens[0].type == TokenType.SELECT

    def test_tokenize_returns_eof(self):
        """Test tokenize includes EOF token."""
        tokens = tokenize("SELECT")
        assert tokens[-1].type == TokenType.EOF
