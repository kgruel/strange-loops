"""Primitives: Style, Cell, and EMPTY_CELL."""

from __future__ import annotations

from dataclasses import dataclass

# Color can be:
#   - Named string: "red", "green", "blue", etc.
#   - 256-color int: 0-255
#   - Hex RGB string: "#ff0000"
Color = str | int | None

NAMED_COLORS = {
    "black": 0,
    "red": 1,
    "green": 2,
    "yellow": 3,
    "blue": 4,
    "magenta": 5,
    "cyan": 6,
    "white": 7,
}


@dataclass(frozen=True)
class Style:
    """Immutable text style with color and attribute flags."""

    fg: Color = None
    bg: Color = None
    bold: bool = False
    italic: bool = False
    underline: bool = False
    reverse: bool = False
    dim: bool = False

    def merge(self, other: Style) -> Style:
        """Combine styles. `other` overrides non-None/non-False fields."""
        return Style(
            fg=other.fg if other.fg is not None else self.fg,
            bg=other.bg if other.bg is not None else self.bg,
            bold=other.bold or self.bold,
            italic=other.italic or self.italic,
            underline=other.underline or self.underline,
            reverse=other.reverse or self.reverse,
            dim=other.dim or self.dim,
        )


@dataclass(frozen=True)
class Cell:
    """Atomic display unit: a single character with style."""

    char: str
    style: Style

    def __post_init__(self):
        if len(self.char) != 1:
            raise ValueError(f"Cell char must be a single character, got {self.char!r}")


EMPTY_CELL = Cell(" ", Style())
