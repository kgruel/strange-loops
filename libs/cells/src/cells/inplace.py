"""InPlaceRenderer: non-Surface terminal animation.

Animate Block output in-place without entering alt screen.
Uses cursor control to hide, move up, clear, and redraw.

For CLI spinners, progress bars, and live-updating status.

Usage:
    from cells.inplace import InPlaceRenderer
    from cells import Block, Style

    with InPlaceRenderer() as renderer:
        for i in range(100):
            block = Block.text(f"Progress: {i}%", Style())
            renderer.render(block)
            time.sleep(0.05)
        renderer.finalize(Block.text("Done!", Style(fg="green")))
"""

from __future__ import annotations

import sys
from typing import TYPE_CHECKING, TextIO

from .writer import Writer

if TYPE_CHECKING:
    from .block import Block


class InPlaceRenderer:
    """Animate Block output in-place without alt screen.

    Pattern: hide cursor, move up N lines, clear, redraw, show cursor.
    """

    def __init__(self, stream: TextIO = sys.stdout):
        self._stream = stream
        self._writer = Writer(stream)
        self._height = 0  # lines written by last frame
        self._active = False

    def __enter__(self) -> "InPlaceRenderer":
        """Enter context: hide cursor."""
        self._writer.hide_cursor()
        self._active = True
        return self

    def __exit__(self, *args) -> None:
        """Exit context: show cursor."""
        self._writer.show_cursor()
        self._active = False

    def render(self, block: "Block") -> None:
        """Render block, replacing previous output.

        First call: just write lines.
        Subsequent calls: move up, clear, rewrite.
        """
        # Move up and clear previous content
        if self._height > 0:
            # Move cursor up N lines
            self._stream.write(f"\x1b[{self._height}A")
            # Clear each line
            for _ in range(self._height):
                self._stream.write("\x1b[2K\n")
            # Move back up
            self._stream.write(f"\x1b[{self._height}A")

        # Write new content
        self._write_block(block)
        self._height = block.height

    def _write_block(self, block: "Block") -> None:
        """Write block content line by line with ANSI styling."""
        for row_idx in range(block.height):
            parts: list[str] = []
            last_style = None

            for cell in block.row(row_idx):
                if cell.style != last_style:
                    parts.append(self._writer.reset_style())
                    sgr = self._writer.apply_style(cell.style)
                    if sgr:
                        parts.append(sgr)
                    last_style = cell.style
                parts.append(cell.char)

            parts.append(self._writer.reset_style())
            parts.append("\n")
            self._stream.write("".join(parts))

        self._stream.flush()

    def clear(self) -> None:
        """Clear the last rendered content."""
        if self._height > 0:
            # Move up and clear
            self._stream.write(f"\x1b[{self._height}A")
            for _ in range(self._height):
                self._stream.write("\x1b[2K\n")
            self._stream.write(f"\x1b[{self._height}A")
            self._stream.flush()
            self._height = 0

    def finalize(self, block: "Block | None" = None) -> None:
        """Finalize output: clear, optionally print final block, show cursor.

        Call this to "lock in" a final state. The cursor is shown and
        positioned after the output.
        """
        if block is not None:
            self.render(block)

        # Show cursor (idempotent if already exited context)
        if self._active:
            self._writer.show_cursor()
            self._active = False


def render_inplace(block: "Block", stream: TextIO = sys.stdout) -> None:
    """One-shot render: write block without animation.

    Convenience for static output with styling.
    """
    writer = Writer(stream)

    for row_idx in range(block.height):
        parts: list[str] = []
        last_style = None

        for cell in block.row(row_idx):
            if cell.style != last_style:
                parts.append(writer.reset_style())
                sgr = writer.apply_style(cell.style)
                if sgr:
                    parts.append(sgr)
                last_style = cell.style
            parts.append(cell.char)

        parts.append(writer.reset_style())
        parts.append("\n")
        stream.write("".join(parts))

    stream.flush()
