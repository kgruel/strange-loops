"""StyledBlock: immutable rectangle of styled cells with known dimensions."""

from __future__ import annotations

from enum import Enum

from .cell import Style, Cell, EMPTY_CELL
from .buffer import Buffer, BufferView


class Wrap(Enum):
    NONE = "none"        # single line, truncate at width
    CHAR = "char"        # break at any character
    WORD = "word"        # break at word boundaries
    ELLIPSIS = "ellipsis"  # truncate with "…"


class StyledBlock:
    """Immutable rectangle of styled cells with known dimensions."""

    __slots__ = ("width", "height", "_rows")

    def __init__(self, rows: list[list[Cell]], width: int):
        self.width = width
        self.height = len(rows)
        self._rows = rows

    @staticmethod
    def text(content: str, style: Style, *, width: int | None = None,
             wrap: Wrap = Wrap.NONE) -> StyledBlock:
        """Create a block from text content with optional wrapping."""
        if width is None:
            # No width constraint: single line, width = len(content)
            cells = [Cell(ch, style) for ch in content]
            return StyledBlock([cells], len(content))

        if wrap == Wrap.NONE:
            # Truncate at width, single line
            line = content[:width]
            cells = [Cell(ch, style) for ch in line]
            cells = _pad_row(cells, width, style)
            return StyledBlock([cells], width)

        if wrap == Wrap.ELLIPSIS:
            # Truncate with ellipsis if needed
            if len(content) > width:
                line = content[:width - 1] + "…"
            else:
                line = content
            cells = [Cell(ch, style) for ch in line]
            cells = _pad_row(cells, width, style)
            return StyledBlock([cells], width)

        if wrap == Wrap.CHAR:
            # Break at any character boundary
            lines: list[str] = []
            for i in range(0, len(content), width):
                lines.append(content[i:i + width])
            if not lines:
                lines = [""]
            rows = [_pad_row([Cell(ch, style) for ch in line], width, style)
                    for line in lines]
            return StyledBlock(rows, width)

        if wrap == Wrap.WORD:
            # Break at word boundaries
            lines = _word_wrap(content, width)
            rows = [_pad_row([Cell(ch, style) for ch in line], width, style)
                    for line in lines]
            return StyledBlock(rows, width)

        raise ValueError(f"Unknown wrap mode: {wrap}")

    @staticmethod
    def empty(width: int, height: int, style: Style = Style()) -> StyledBlock:
        """Create a block filled with space cells."""
        space = Cell(" ", style)
        rows = [[space] * width for _ in range(height)]
        return StyledBlock(rows, width)

    def paint(self, buffer: Buffer | BufferView, x: int = 0, y: int = 0) -> None:
        """Transfer cells into a buffer region. Clips to buffer bounds."""
        for row_idx in range(self.height):
            for col_idx in range(self.width):
                bx = x + col_idx
                by = y + row_idx
                cell = self._rows[row_idx][col_idx]
                buffer.put(bx, by, cell.char, cell.style)

    def row(self, y: int) -> list[Cell]:
        """Access a row by index."""
        return self._rows[y]


def _pad_row(cells: list[Cell], width: int, style: Style) -> list[Cell]:
    """Pad a row to the target width with space cells."""
    if len(cells) < width:
        space = Cell(" ", style)
        cells = cells + [space] * (width - len(cells))
    return cells


def _word_wrap(text: str, width: int) -> list[str]:
    """Break text at word boundaries to fit within width."""
    if not text:
        return [""]

    words = text.split(" ")
    lines: list[str] = []
    current_line = ""

    for word in words:
        if not current_line:
            # First word on line — take it even if too long
            if len(word) <= width:
                current_line = word
            else:
                # Word itself exceeds width, break it
                while len(word) > width:
                    lines.append(word[:width])
                    word = word[width:]
                current_line = word
        elif len(current_line) + 1 + len(word) <= width:
            current_line += " " + word
        else:
            lines.append(current_line)
            if len(word) <= width:
                current_line = word
            else:
                while len(word) > width:
                    lines.append(word[:width])
                    word = word[width:]
                current_line = word

    if current_line:
        lines.append(current_line)

    return lines if lines else [""]
