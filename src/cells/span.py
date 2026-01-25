"""Span and Line: styled text primitives for the render layer."""

from __future__ import annotations

from dataclasses import dataclass

from wcwidth import wcswidth

from .buffer import BufferView
from .cell import Style


@dataclass(frozen=True, slots=True)
class Span:
    """A run of text with a single style."""

    text: str
    style: Style = Style()

    @property
    def width(self) -> int:
        """Display width, accounting for wide characters."""
        w = wcswidth(self.text)
        if w < 0:
            # Fallback for strings containing non-printable chars
            return len(self.text)
        return w


@dataclass(frozen=True, slots=True)
class Line:
    """A sequence of spans forming a single line of styled text."""

    spans: tuple[Span, ...] = ()
    style: Style = Style()

    @classmethod
    def plain(cls, text: str, style: Style = Style()) -> Line:
        """Create a Line from a single unstyled (or uniformly styled) string."""
        return cls((Span(text, style),))

    @property
    def width(self) -> int:
        """Total display width across all spans."""
        return sum(s.width for s in self.spans)

    def paint(self, view: BufferView, x: int, y: int) -> None:
        """Render spans into a BufferView, merging base style onto each span."""
        col = x
        for span in self.spans:
            merged = self.style.merge(span.style)
            view.put_text(col, y, span.text, merged)
            col += span.width

    def truncate(self, max_width: int) -> Line:
        """Return a new Line truncated to max_width display columns."""
        remaining = max_width
        kept: list[Span] = []
        for span in self.spans:
            sw = span.width
            if sw <= remaining:
                kept.append(span)
                remaining -= sw
            else:
                # Cut this span character by character
                chars: list[str] = []
                used = 0
                for ch in span.text:
                    cw = wcswidth(ch)
                    if cw < 0:
                        cw = 1
                    if used + cw > remaining:
                        break
                    chars.append(ch)
                    used += cw
                if chars:
                    kept.append(Span("".join(chars), span.style))
                break
        return Line(spans=tuple(kept), style=self.style)
