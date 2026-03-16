"""Error types for DSL parsing and validation."""

from __future__ import annotations

# pathlib deferred — only used in Location.__str__ and ValidationContext.error


class Location:
    """Source location for error reporting."""

    __slots__ = ("path", "line", "column")

    def __init__(self, path: Path | None, line: int, column: int = 0):
        self.path = path
        self.line = line
        self.column = column

    def __repr__(self):
        return f"Location(path={self.path!r}, line={self.line!r}, column={self.column!r})"

    def __eq__(self, other):
        if type(self) is not type(other):
            return NotImplemented
        return (self.path, self.line, self.column) == (other.path, other.line, other.column)

    def __str__(self) -> str:
        name = self.path.name if self.path else "<input>"
        if self.column > 0:
            return f"{name}:{self.line}:{self.column}"
        return f"{name}:{self.line}"


class DSLError(Exception):
    """Base class for DSL errors."""

    def __init__(self, message: str, location: Location | None = None, hint: str | None = None):
        self.message = message
        self.location = location
        self.hint = hint
        super().__init__(self._format())

    def _format(self) -> str:
        parts = []
        if self.location:
            parts.append(f"{self.location}: {self.message}")
        else:
            parts.append(self.message)
        if self.hint:
            parts.append(f"  hint: {self.hint}")
        return "\n".join(parts)


class LexError(DSLError):
    """Lexer error: invalid token."""

    pass


class ParseError(DSLError):
    """Parser error: unexpected token or structure."""

    pass


class ValidationError(DSLError):
    """Validation error: semantic issue (flow, types, references)."""

    pass
