"""Minimal IR for reactive CLI rendering."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable, TYPE_CHECKING

if TYPE_CHECKING:
    from rich.text import Text


@dataclass(frozen=True, slots=True)
class Segment:
    """A piece of styled text."""

    text: str
    style: str = ""


@dataclass(frozen=True, slots=True)
class Line:
    """A line of segments."""

    segments: tuple[Segment, ...]

    def plain(self) -> str:
        return "".join(s.text for s in self.segments)

    def to_rich(self) -> "Text":
        from rich.text import Text

        text = Text()
        for seg in self.segments:
            text.append(seg.text, style=seg.style or None)
        return text


def lines_to_rich(lines: Iterable[Line]) -> "Text":
    """Convert lines to a Rich Text object."""
    from rich.text import Text

    result = Text()
    for i, line in enumerate(lines):
        if i > 0:
            result.append("\n")
        result.append_text(line.to_rich())
    return result
