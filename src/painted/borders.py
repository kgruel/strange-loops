"""Border character sets for styled block composition."""

from dataclasses import dataclass


@dataclass(frozen=True)
class BorderChars:
    top_left: str
    top_right: str
    bottom_left: str
    bottom_right: str
    horizontal: str
    vertical: str


ROUNDED = BorderChars("╭", "╮", "╰", "╯", "─", "│")
HEAVY = BorderChars("┏", "┓", "┗", "┛", "━", "┃")
DOUBLE = BorderChars("╔", "╗", "╚", "╝", "═", "║")
LIGHT = BorderChars("┌", "┐", "└", "┘", "─", "│")
ASCII = BorderChars("+", "+", "+", "+", "-", "|")
