"""Buffer: 2D grid of Cells with diff and region support."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

from wcwidth import wcwidth

from .cell import Cell, Style, EMPTY_CELL


@dataclass
class CellWrite:
    """A single cell change: position + new cell value."""

    x: int
    y: int
    cell: Cell


class Buffer:
    """2D grid of Cells, row-major flat list for cache efficiency."""

    __slots__ = ("width", "height", "_cells", "_ids")

    def __init__(self, width: int, height: int):
        self.width = width
        self.height = height
        self._cells: list[Cell] = [EMPTY_CELL] * (width * height)
        self._ids: list[str | None] | None = None

    def _ensure_ids(self) -> list[str | None]:
        if self._ids is None:
            self._ids = [None] * (self.width * self.height)
        return self._ids

    def _index(self, x: int, y: int) -> Optional[int]:
        if 0 <= x < self.width and 0 <= y < self.height:
            return y * self.width + x
        return None

    def get(self, x: int, y: int) -> Cell:
        idx = self._index(x, y)
        if idx is None:
            return EMPTY_CELL
        return self._cells[idx]

    def put(self, x: int, y: int, char: str, style: Style) -> None:
        """Set a single cell. Out-of-bounds writes are silently ignored."""
        idx = self._index(x, y)
        if idx is None:
            return
        self._cells[idx] = Cell(char, style)
        if self._ids is not None:
            self._ids[idx] = None

    def put_id(self, x: int, y: int, char: str, style: Style, id: str) -> None:
        """Set a single cell and record a semantic id for hit-testing."""
        idx = self._index(x, y)
        if idx is None:
            return
        self._cells[idx] = Cell(char, style)
        self._ensure_ids()[idx] = id

    def put_text(self, x: int, y: int, text: str, style: Style) -> None:
        """Write a string horizontally, respecting wide characters."""
        col = x
        for ch in text:
            w = wcwidth(ch)
            if w < 0:
                # Non-printable — skip
                continue
            if w == 0:
                # Zero-width (combining) — skip
                continue
            # Place the character
            idx = self._index(col, y)
            if idx is not None:
                self._cells[idx] = Cell(ch, style)
                if self._ids is not None:
                    self._ids[idx] = None
            # For wide chars (w == 2), fill the next cell with a placeholder
            if w == 2:
                next_idx = self._index(col + 1, y)
                if next_idx is not None:
                    self._cells[next_idx] = Cell(" ", style)
                    if self._ids is not None:
                        self._ids[next_idx] = None
            col += w

    def fill(self, x: int, y: int, w: int, h: int, char: str, style: Style) -> None:
        """Fill a rectangular region with a character+style."""
        cell = Cell(char, style)
        for row in range(y, y + h):
            for col in range(x, x + w):
                idx = self._index(col, row)
                if idx is not None:
                    self._cells[idx] = cell
                    if self._ids is not None:
                        self._ids[idx] = None

    def region(self, x: int, y: int, w: int, h: int) -> BufferView:
        """Return a view that translates coordinates to a sub-region."""
        return BufferView(self, x, y, w, h)

    def hit(self, x: int, y: int) -> str | None:
        """Return the semantic id at (x, y), if any."""
        idx = self._index(x, y)
        if idx is None or self._ids is None:
            return None
        return self._ids[idx]

    def diff(self, other: Buffer) -> list[CellWrite]:
        """Compare with another buffer, return list of cells that differ."""
        writes: list[CellWrite] = []
        for i in range(len(self._cells)):
            if self._cells[i] != other._cells[i]:
                y, x = divmod(i, self.width)
                writes.append(CellWrite(x, y, self._cells[i]))
        return writes

    def clone(self) -> Buffer:
        """Deep copy for diff comparison."""
        buf = Buffer(self.width, self.height)
        buf._cells = list(self._cells)  # Cells are frozen, shallow copy is fine
        if self._ids is not None:
            buf._ids = list(self._ids)
        return buf


class BufferView:
    """A clipped view into a Buffer with coordinate translation."""

    __slots__ = ("_buffer", "_ox", "_oy", "_w", "_h")

    def __init__(self, buffer: Buffer, ox: int, oy: int, w: int, h: int):
        self._buffer = buffer
        self._ox = ox
        self._oy = oy
        self._w = w
        self._h = h

    @property
    def width(self) -> int:
        return self._w

    @property
    def height(self) -> int:
        return self._h

    def _clip(self, x: int, y: int) -> Optional[tuple[int, int]]:
        """Translate and clip. Returns absolute coords or None if out of bounds."""
        if 0 <= x < self._w and 0 <= y < self._h:
            return (self._ox + x, self._oy + y)
        return None

    def put(self, x: int, y: int, char: str, style: Style) -> None:
        pos = self._clip(x, y)
        if pos:
            self._buffer.put(pos[0], pos[1], char, style)

    def put_id(self, x: int, y: int, char: str, style: Style, id: str) -> None:
        pos = self._clip(x, y)
        if pos:
            self._buffer.put_id(pos[0], pos[1], char, style, id)

    def put_text(self, x: int, y: int, text: str, style: Style) -> None:
        """Write text, clipping characters that fall outside the view."""
        col = x
        for ch in text:
            w = wcwidth(ch)
            if w <= 0:
                continue
            # Only write if within clip bounds
            if 0 <= col < self._w and 0 <= y < self._h:
                self._buffer.put(self._ox + col, self._oy + y, ch, style)
                if w == 2 and col + 1 < self._w:
                    self._buffer.put(self._ox + col + 1, self._oy + y, " ", style)
            col += w

    def fill(self, x: int, y: int, w: int, h: int, char: str, style: Style) -> None:
        """Fill a region, clipping to view bounds."""
        for row in range(y, y + h):
            for col in range(x, x + w):
                pos = self._clip(col, row)
                if pos:
                    self._buffer.put(pos[0], pos[1], char, style)

    def hit(self, x: int, y: int) -> str | None:
        """Return the semantic id at a local coordinate (or None)."""
        pos = self._clip(x, y)
        if not pos:
            return None
        return self._buffer.hit(pos[0], pos[1])
