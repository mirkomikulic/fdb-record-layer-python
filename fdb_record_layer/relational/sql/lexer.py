"""SQL Lexer (Tokenizer).

Converts SQL text into a stream of tokens for parsing.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum, auto


class TokenType(Enum):
    """SQL token types."""

    # Literals
    INTEGER = auto()
    FLOAT = auto()
    STRING = auto()
    IDENTIFIER = auto()
    QUOTED_IDENTIFIER = auto()

    # Keywords
    SELECT = auto()
    FROM = auto()
    WHERE = auto()
    AND = auto()
    OR = auto()
    NOT = auto()
    IN = auto()
    BETWEEN = auto()
    LIKE = auto()
    IS = auto()
    NULL = auto()
    TRUE = auto()
    FALSE = auto()
    AS = auto()
    ON = auto()
    USING = auto()
    JOIN = auto()
    INNER = auto()
    LEFT = auto()
    RIGHT = auto()
    FULL = auto()
    OUTER = auto()
    CROSS = auto()
    ORDER = auto()
    BY = auto()
    ASC = auto()
    DESC = auto()
    NULLS = auto()
    FIRST = auto()
    LAST = auto()
    GROUP = auto()
    HAVING = auto()
    LIMIT = auto()
    OFFSET = auto()
    DISTINCT = auto()
    ALL = auto()
    UNION = auto()
    INTERSECT = auto()
    EXCEPT = auto()
    EXISTS = auto()
    CASE = auto()
    WHEN = auto()
    THEN = auto()
    ELSE = auto()
    END = auto()
    CAST = auto()

    # DML
    INSERT = auto()
    INTO = auto()
    VALUES = auto()
    UPDATE = auto()
    SET = auto()
    DELETE = auto()

    # DDL
    CREATE = auto()
    DROP = auto()
    TABLE = auto()
    INDEX = auto()
    SCHEMA = auto()
    DATABASE = auto()
    IF = auto()
    CASCADE = auto()
    UNIQUE = auto()
    PRIMARY = auto()
    KEY = auto()
    FOREIGN = auto()
    REFERENCES = auto()
    DEFAULT = auto()

    # Data types
    BOOLEAN = auto()
    TINYINT = auto()
    SMALLINT = auto()
    INT = auto()
    INTEGER_KW = auto()
    BIGINT = auto()
    FLOAT_KW = auto()
    DOUBLE = auto()
    DECIMAL = auto()
    STRING_KW = auto()
    VARCHAR = auto()
    CHAR = auto()
    BYTES = auto()
    DATE = auto()
    TIME = auto()
    TIMESTAMP = auto()
    ARRAY = auto()
    STRUCT = auto()
    MAP = auto()

    # Operators
    EQ = auto()  # =
    NE = auto()  # != or <>
    LT = auto()  # <
    LE = auto()  # <=
    GT = auto()  # >
    GE = auto()  # >=
    PLUS = auto()  # +
    MINUS = auto()  # -
    STAR = auto()  # *
    SLASH = auto()  # /
    PERCENT = auto()  # %
    CONCAT = auto()  # ||

    # Delimiters
    LPAREN = auto()  # (
    RPAREN = auto()  # )
    LBRACKET = auto()  # [
    RBRACKET = auto()  # ]
    COMMA = auto()  # ,
    DOT = auto()  # .
    SEMICOLON = auto()  # ;
    COLON = auto()  # :
    QUESTION = auto()  # ?

    # Special
    EOF = auto()
    ERROR = auto()


# Keywords mapping
KEYWORDS = {
    "SELECT": TokenType.SELECT,
    "FROM": TokenType.FROM,
    "WHERE": TokenType.WHERE,
    "AND": TokenType.AND,
    "OR": TokenType.OR,
    "NOT": TokenType.NOT,
    "IN": TokenType.IN,
    "BETWEEN": TokenType.BETWEEN,
    "LIKE": TokenType.LIKE,
    "IS": TokenType.IS,
    "NULL": TokenType.NULL,
    "TRUE": TokenType.TRUE,
    "FALSE": TokenType.FALSE,
    "AS": TokenType.AS,
    "ON": TokenType.ON,
    "USING": TokenType.USING,
    "JOIN": TokenType.JOIN,
    "INNER": TokenType.INNER,
    "LEFT": TokenType.LEFT,
    "RIGHT": TokenType.RIGHT,
    "FULL": TokenType.FULL,
    "OUTER": TokenType.OUTER,
    "CROSS": TokenType.CROSS,
    "ORDER": TokenType.ORDER,
    "BY": TokenType.BY,
    "ASC": TokenType.ASC,
    "DESC": TokenType.DESC,
    "NULLS": TokenType.NULLS,
    "FIRST": TokenType.FIRST,
    "LAST": TokenType.LAST,
    "GROUP": TokenType.GROUP,
    "HAVING": TokenType.HAVING,
    "LIMIT": TokenType.LIMIT,
    "OFFSET": TokenType.OFFSET,
    "DISTINCT": TokenType.DISTINCT,
    "ALL": TokenType.ALL,
    "UNION": TokenType.UNION,
    "INTERSECT": TokenType.INTERSECT,
    "EXCEPT": TokenType.EXCEPT,
    "EXISTS": TokenType.EXISTS,
    "CASE": TokenType.CASE,
    "WHEN": TokenType.WHEN,
    "THEN": TokenType.THEN,
    "ELSE": TokenType.ELSE,
    "END": TokenType.END,
    "CAST": TokenType.CAST,
    "INSERT": TokenType.INSERT,
    "INTO": TokenType.INTO,
    "VALUES": TokenType.VALUES,
    "UPDATE": TokenType.UPDATE,
    "SET": TokenType.SET,
    "DELETE": TokenType.DELETE,
    "CREATE": TokenType.CREATE,
    "DROP": TokenType.DROP,
    "TABLE": TokenType.TABLE,
    "INDEX": TokenType.INDEX,
    "SCHEMA": TokenType.SCHEMA,
    "DATABASE": TokenType.DATABASE,
    "IF": TokenType.IF,
    "CASCADE": TokenType.CASCADE,
    "UNIQUE": TokenType.UNIQUE,
    "PRIMARY": TokenType.PRIMARY,
    "KEY": TokenType.KEY,
    "FOREIGN": TokenType.FOREIGN,
    "REFERENCES": TokenType.REFERENCES,
    "DEFAULT": TokenType.DEFAULT,
    "BOOLEAN": TokenType.BOOLEAN,
    "TINYINT": TokenType.TINYINT,
    "SMALLINT": TokenType.SMALLINT,
    "INT": TokenType.INT,
    "INTEGER": TokenType.INTEGER_KW,
    "BIGINT": TokenType.BIGINT,
    "FLOAT": TokenType.FLOAT_KW,
    "DOUBLE": TokenType.DOUBLE,
    "DECIMAL": TokenType.DECIMAL,
    "STRING": TokenType.STRING_KW,
    "VARCHAR": TokenType.VARCHAR,
    "CHAR": TokenType.CHAR,
    "BYTES": TokenType.BYTES,
    "DATE": TokenType.DATE,
    "TIME": TokenType.TIME,
    "TIMESTAMP": TokenType.TIMESTAMP,
    "ARRAY": TokenType.ARRAY,
    "STRUCT": TokenType.STRUCT,
    "MAP": TokenType.MAP,
}


@dataclass
class Token:
    """A single token."""

    type: TokenType
    value: str
    line: int
    column: int

    def __repr__(self) -> str:
        return f"Token({self.type.name}, {self.value!r}, {self.line}:{self.column})"


class Lexer:
    """SQL Lexer that tokenizes SQL text."""

    def __init__(self, text: str) -> None:
        self._text = text
        self._pos = 0
        self._line = 1
        self._column = 1
        self._tokens: list[Token] = []

    def tokenize(self) -> list[Token]:
        """Tokenize the entire input."""
        while self._pos < len(self._text):
            token = self._next_token()
            if token.type != TokenType.ERROR or token.value.strip():
                self._tokens.append(token)

        self._tokens.append(Token(TokenType.EOF, "", self._line, self._column))
        return self._tokens

    def _next_token(self) -> Token:
        """Get the next token."""
        self._skip_whitespace_and_comments()

        if self._pos >= len(self._text):
            return Token(TokenType.EOF, "", self._line, self._column)

        start_line = self._line
        start_col = self._column
        ch = self._text[self._pos]

        # String literal
        if ch == "'":
            return self._read_string(start_line, start_col)

        # Quoted identifier
        if ch == '"':
            return self._read_quoted_identifier(start_line, start_col)

        # Number
        if ch.isdigit():
            return self._read_number(start_line, start_col)

        # Identifier or keyword
        if ch.isalpha() or ch == "_":
            return self._read_identifier(start_line, start_col)

        # Operators and delimiters
        return self._read_operator(start_line, start_col)

    def _skip_whitespace_and_comments(self) -> None:
        """Skip whitespace and comments."""
        while self._pos < len(self._text):
            ch = self._text[self._pos]

            if ch.isspace():
                if ch == "\n":
                    self._line += 1
                    self._column = 1
                else:
                    self._column += 1
                self._pos += 1

            elif ch == "-" and self._peek(1) == "-":
                # Single-line comment
                while self._pos < len(self._text) and self._text[self._pos] != "\n":
                    self._pos += 1

            elif ch == "/" and self._peek(1) == "*":
                # Multi-line comment
                self._pos += 2
                self._column += 2
                while self._pos < len(self._text) - 1:
                    if self._text[self._pos] == "*" and self._text[self._pos + 1] == "/":
                        self._pos += 2
                        self._column += 2
                        break
                    if self._text[self._pos] == "\n":
                        self._line += 1
                        self._column = 1
                    else:
                        self._column += 1
                    self._pos += 1

            else:
                break

    def _peek(self, offset: int = 0) -> str:
        """Peek at character at offset from current position."""
        pos = self._pos + offset
        if pos < len(self._text):
            return self._text[pos]
        return ""

    def _advance(self) -> str:
        """Advance and return current character."""
        ch = self._text[self._pos]
        self._pos += 1
        self._column += 1
        return ch

    def _read_string(self, line: int, col: int) -> Token:
        """Read a string literal."""
        self._advance()  # Skip opening quote
        value = []

        while self._pos < len(self._text):
            ch = self._text[self._pos]

            if ch == "'":
                if self._peek(1) == "'":
                    # Escaped quote
                    value.append("'")
                    self._pos += 2
                    self._column += 2
                else:
                    self._advance()  # Skip closing quote
                    return Token(TokenType.STRING, "".join(value), line, col)
            elif ch == "\n":
                self._line += 1
                self._column = 1
                value.append(ch)
                self._pos += 1
            else:
                value.append(self._advance())

        return Token(TokenType.ERROR, "Unterminated string", line, col)

    def _read_quoted_identifier(self, line: int, col: int) -> Token:
        """Read a quoted identifier."""
        self._advance()  # Skip opening quote
        value = []

        while self._pos < len(self._text):
            ch = self._text[self._pos]

            if ch == '"':
                if self._peek(1) == '"':
                    # Escaped quote
                    value.append('"')
                    self._pos += 2
                    self._column += 2
                else:
                    self._advance()  # Skip closing quote
                    return Token(TokenType.QUOTED_IDENTIFIER, "".join(value), line, col)
            else:
                value.append(self._advance())

        return Token(TokenType.ERROR, "Unterminated identifier", line, col)

    def _read_number(self, line: int, col: int) -> Token:
        """Read a number literal."""
        value = []
        has_dot = False

        while self._pos < len(self._text):
            ch = self._text[self._pos]

            if ch.isdigit():
                value.append(self._advance())
            elif ch == "." and not has_dot:
                if self._peek(1).isdigit():
                    has_dot = True
                    value.append(self._advance())
                else:
                    break
            elif ch.lower() == "e" and value:
                value.append(self._advance())
                if self._pos < len(self._text) and self._text[self._pos] in "+-":
                    value.append(self._advance())
                has_dot = True  # Exponent makes it a float
            else:
                break

        token_type = TokenType.FLOAT if has_dot else TokenType.INTEGER
        return Token(token_type, "".join(value), line, col)

    def _read_identifier(self, line: int, col: int) -> Token:
        """Read an identifier or keyword."""
        value = []

        while self._pos < len(self._text):
            ch = self._text[self._pos]
            if ch.isalnum() or ch == "_":
                value.append(self._advance())
            else:
                break

        text = "".join(value)
        upper = text.upper()

        # Check if it's a keyword
        if upper in KEYWORDS:
            return Token(KEYWORDS[upper], text, line, col)

        return Token(TokenType.IDENTIFIER, text, line, col)

    def _read_operator(self, line: int, col: int) -> Token:
        """Read an operator or delimiter."""
        ch = self._advance()

        # Two-character operators
        if ch == "!" and self._peek() == "=":
            self._advance()
            return Token(TokenType.NE, "!=", line, col)
        if ch == "<":
            if self._peek() == "=":
                self._advance()
                return Token(TokenType.LE, "<=", line, col)
            if self._peek() == ">":
                self._advance()
                return Token(TokenType.NE, "<>", line, col)
            return Token(TokenType.LT, "<", line, col)
        if ch == ">":
            if self._peek() == "=":
                self._advance()
                return Token(TokenType.GE, ">=", line, col)
            return Token(TokenType.GT, ">", line, col)
        if ch == "|" and self._peek() == "|":
            self._advance()
            return Token(TokenType.CONCAT, "||", line, col)

        # Single-character operators
        operators = {
            "=": TokenType.EQ,
            "+": TokenType.PLUS,
            "-": TokenType.MINUS,
            "*": TokenType.STAR,
            "/": TokenType.SLASH,
            "%": TokenType.PERCENT,
            "(": TokenType.LPAREN,
            ")": TokenType.RPAREN,
            "[": TokenType.LBRACKET,
            "]": TokenType.RBRACKET,
            ",": TokenType.COMMA,
            ".": TokenType.DOT,
            ";": TokenType.SEMICOLON,
            ":": TokenType.COLON,
            "?": TokenType.QUESTION,
        }

        if ch in operators:
            return Token(operators[ch], ch, line, col)

        return Token(TokenType.ERROR, f"Unexpected character: {ch}", line, col)


def tokenize(sql: str) -> list[Token]:
    """Convenience function to tokenize SQL."""
    return Lexer(sql).tokenize()
