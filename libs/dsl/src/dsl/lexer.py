"""Lexer for .loop and .vertex DSL files.

The DSL uses a line-oriented format:
- Key-value pairs: `key: value`
- Indented blocks for nested structures
- Comments with `#`
- Pipeline syntax in parse blocks
- Combinator syntax in fold blocks
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from enum import Enum, auto
from pathlib import Path
from typing import Iterator

from .errors import LexError, Location


class TokenType(Enum):
    """Token types for the DSL."""

    # Structure
    KEY = auto()  # identifier followed by colon
    COLON = auto()  # :
    INDENT = auto()  # increase in indentation
    DEDENT = auto()  # decrease in indentation
    NEWLINE = auto()  # end of line
    EOF = auto()  # end of file

    # Values
    STRING = auto()  # quoted string
    NUMBER = auto()  # integer or float
    DURATION = auto()  # 5s, 1m, etc.
    IDENTIFIER = auto()  # bare word
    GLOB = auto()  # glob pattern like ./**/*.loop

    # Parse operations
    SKIP = auto()  # skip keyword
    SPLIT = auto()  # split keyword
    PICK = auto()  # pick keyword

    # Fold operations
    BY = auto()  # by keyword
    PLUS = auto()  # +
    LATEST = auto()  # latest keyword
    COLLECT = auto()  # collect keyword
    MAX = auto()  # max keyword
    MIN = auto()  # min keyword

    # Boundary
    WHEN = auto()  # when keyword

    # Transform operations
    STRIP = auto()  # strip keyword
    LSTRIP = auto()  # lstrip keyword
    RSTRIP = auto()  # rstrip keyword
    REPLACE = auto()  # replace keyword
    INT = auto()  # int keyword
    FLOAT = auto()  # float keyword
    BOOL = auto()  # bool keyword
    STR = auto()  # str keyword

    # Punctuation
    ARROW = auto()  # ->
    PIPE = auto()  # |
    COMMA = auto()  # ,
    DASH = auto()  # - (for list items)
    LBRACKET = auto()  # [
    RBRACKET = auto()  # ]


# Keywords that get special token types
KEYWORDS = {
    "skip": TokenType.SKIP,
    "split": TokenType.SPLIT,
    "pick": TokenType.PICK,
    "by": TokenType.BY,
    "latest": TokenType.LATEST,
    "collect": TokenType.COLLECT,
    "max": TokenType.MAX,
    "min": TokenType.MIN,
    "when": TokenType.WHEN,
    "strip": TokenType.STRIP,
    "lstrip": TokenType.LSTRIP,
    "rstrip": TokenType.RSTRIP,
    "replace": TokenType.REPLACE,
    "int": TokenType.INT,
    "float": TokenType.FLOAT,
    "bool": TokenType.BOOL,
    "str": TokenType.STR,
}


@dataclass
class Token:
    """A token from the lexer."""

    type: TokenType
    value: str
    location: Location

    def __repr__(self) -> str:
        return f"Token({self.type.name}, {self.value!r}, line={self.location.line})"


class Lexer:
    """Lexer for DSL files."""

    def __init__(self, text: str, path: Path | None = None):
        self.text = text
        self.path = path
        self.pos = 0
        self.line = 1
        self.column = 1
        self.indent_stack = [0]  # Track indentation levels

    def location(self) -> Location:
        """Current source location."""
        return Location(self.path, self.line, self.column)

    def peek(self, n: int = 0) -> str:
        """Peek at character at current position + n."""
        pos = self.pos + n
        if pos >= len(self.text):
            return ""
        return self.text[pos]

    def advance(self) -> str:
        """Advance one character."""
        if self.pos >= len(self.text):
            return ""
        c = self.text[self.pos]
        self.pos += 1
        if c == "\n":
            self.line += 1
            self.column = 1
        else:
            self.column += 1
        return c

    def skip_whitespace_on_line(self) -> None:
        """Skip spaces and tabs (not newlines)."""
        while self.peek() in " \t":
            self.advance()

    def skip_comment(self) -> None:
        """Skip comment to end of line."""
        while self.peek() and self.peek() != "\n":
            self.advance()

    def read_string(self) -> str:
        """Read a quoted string."""
        quote = self.advance()  # consume opening quote
        result = []
        while self.peek() and self.peek() != quote:
            c = self.advance()
            if c == "\\":
                next_c = self.advance()
                if next_c == "n":
                    result.append("\n")
                elif next_c == "t":
                    result.append("\t")
                elif next_c == "\\":
                    result.append("\\")
                elif next_c == quote:
                    result.append(quote)
                else:
                    result.append(c + next_c)
            else:
                result.append(c)
        if not self.peek():
            raise LexError("Unterminated string", self.location())
        self.advance()  # consume closing quote
        return "".join(result)

    def read_identifier_or_keyword(self) -> tuple[TokenType, str]:
        """Read an identifier or keyword."""
        start = self.pos
        while self.peek() and (self.peek().isalnum() or self.peek() in "_-."):
            self.advance()
        value = self.text[start : self.pos]
        token_type = KEYWORDS.get(value, TokenType.IDENTIFIER)
        return token_type, value

    def read_number(self) -> tuple[TokenType, str]:
        """Read a number or duration."""
        start = self.pos
        while self.peek() and self.peek().isdigit():
            self.advance()
        # Check for duration suffix (must be non-empty peek)
        if self.peek() and self.peek() in "hms":
            while self.peek() and (self.peek().isdigit() or self.peek() in "hms"):
                self.advance()
            return TokenType.DURATION, self.text[start : self.pos]
        # Check for decimal
        if self.peek() == ".":
            self.advance()
            while self.peek() and self.peek().isdigit():
                self.advance()
        return TokenType.NUMBER, self.text[start : self.pos]

    def read_glob_or_path(self) -> str:
        """Read a glob pattern or path (starts with . or /)."""
        start = self.pos
        # Consume until whitespace, newline, or comment
        while self.peek() and self.peek() not in " \t\n#":
            self.advance()
        return self.text[start : self.pos]

    def tokenize_line(self) -> Iterator[Token]:
        """Tokenize a single logical line."""
        self.skip_whitespace_on_line()

        # Skip empty lines and comment-only lines
        if not self.peek() or self.peek() == "\n":
            return
        if self.peek() == "#":
            self.skip_comment()
            return

        while self.peek() and self.peek() != "\n":
            loc = self.location()

            # Skip inline whitespace
            if self.peek() in " \t":
                self.skip_whitespace_on_line()
                continue

            # Comments
            if self.peek() == "#":
                self.skip_comment()
                break

            # Strings
            if self.peek() in '"\'':
                value = self.read_string()
                yield Token(TokenType.STRING, value, loc)
                continue

            # Punctuation
            if self.peek() == ":":
                self.advance()
                yield Token(TokenType.COLON, ":", loc)
                continue

            if self.peek() == ",":
                self.advance()
                yield Token(TokenType.COMMA, ",", loc)
                continue

            if self.peek() == "|":
                self.advance()
                yield Token(TokenType.PIPE, "|", loc)
                continue

            if self.peek() == "[":
                self.advance()
                yield Token(TokenType.LBRACKET, "[", loc)
                continue

            if self.peek() == "]":
                self.advance()
                yield Token(TokenType.RBRACKET, "]", loc)
                continue

            if self.peek() == "+" and self.peek(1).isdigit():
                # +1 case
                self.advance()
                yield Token(TokenType.PLUS, "+", loc)
                continue

            if self.peek() == "+":
                self.advance()
                yield Token(TokenType.PLUS, "+", loc)
                continue

            if self.peek() == "-" and self.peek(1) == ">":
                self.advance()
                self.advance()
                yield Token(TokenType.ARROW, "->", loc)
                continue

            if self.peek() == "-" and self.peek(1) == " ":
                # List item marker
                self.advance()
                yield Token(TokenType.DASH, "-", loc)
                continue

            # Bare dash followed by alphanumeric (like -h flag)
            if self.peek() == "-" and self.peek(1).isalnum():
                start = self.pos
                self.advance()  # consume -
                while self.peek() and (self.peek().isalnum() or self.peek() in "_-"):
                    self.advance()
                value = self.text[start : self.pos]
                yield Token(TokenType.IDENTIFIER, value, loc)
                continue

            # Glob patterns or paths (start with . or /)
            if self.peek() in "./":
                value = self.read_glob_or_path()
                yield Token(TokenType.GLOB, value, loc)
                continue

            # Numbers or durations
            if self.peek().isdigit():
                token_type, value = self.read_number()
                yield Token(token_type, value, loc)
                continue

            # Identifiers or keywords
            if self.peek().isalpha() or self.peek() == "_":
                token_type, value = self.read_identifier_or_keyword()
                yield Token(token_type, value, loc)
                continue

            # Regex patterns (for skip)
            if self.peek() == "^":
                # Read until whitespace or newline
                start = self.pos
                while self.peek() and self.peek() not in " \t\n#":
                    self.advance()
                value = self.text[start : self.pos]
                yield Token(TokenType.IDENTIFIER, value, loc)
                continue

            raise LexError(f"Unexpected character: {self.peek()!r}", loc)

    def tokenize(self) -> Iterator[Token]:
        """Tokenize the entire input."""
        while self.pos < len(self.text):
            # Handle line start - check indentation
            line_start = self.pos
            line_num = self.line

            # Count leading spaces/tabs
            indent = 0
            while self.peek() in " \t":
                if self.peek() == " ":
                    indent += 1
                else:
                    indent += 4  # Tab = 4 spaces
                self.advance()

            # Skip blank lines and comment-only lines
            if self.peek() == "\n":
                self.advance()
                continue
            if self.peek() == "#":
                self.skip_comment()
                if self.peek() == "\n":
                    self.advance()
                continue
            if not self.peek():
                break

            # Emit indent/dedent tokens
            loc = Location(self.path, line_num, 1)
            if indent > self.indent_stack[-1]:
                self.indent_stack.append(indent)
                yield Token(TokenType.INDENT, "", loc)
            else:
                while indent < self.indent_stack[-1]:
                    self.indent_stack.pop()
                    yield Token(TokenType.DEDENT, "", loc)
                if indent != self.indent_stack[-1]:
                    raise LexError(
                        f"Inconsistent indentation: expected {self.indent_stack[-1]}, got {indent}",
                        loc,
                    )

            # Tokenize the rest of the line
            yield from self.tokenize_line()

            # Emit newline
            if self.peek() == "\n":
                yield Token(TokenType.NEWLINE, "\n", self.location())
                self.advance()

        # Emit remaining dedents
        loc = self.location()
        while len(self.indent_stack) > 1:
            self.indent_stack.pop()
            yield Token(TokenType.DEDENT, "", loc)

        yield Token(TokenType.EOF, "", loc)


def tokenize(text: str, path: Path | None = None) -> list[Token]:
    """Tokenize DSL text into a list of tokens."""
    return list(Lexer(text, path).tokenize())
