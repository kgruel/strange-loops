"""Writer: terminal output via ANSI escape sequences."""

from __future__ import annotations

import os
import shutil
import sys
from enum import Enum
from typing import TYPE_CHECKING, TextIO

from .buffer import CellWrite
from .cell import Cell, Style, NAMED_COLORS

if TYPE_CHECKING:
    from .block import Block


class ColorDepth(Enum):
    NONE = 0
    BASIC = 16
    EIGHT_BIT = 256
    TRUECOLOR = 16_777_216


class Writer:
    """Converts cell writes to ANSI escape sequences and outputs to terminal."""

    def __init__(self, stream: TextIO = sys.stdout):
        self._stream = stream
        self._color_depth: ColorDepth | None = None

    def size(self) -> tuple[int, int]:
        """Terminal dimensions (columns, rows)."""
        sz = shutil.get_terminal_size()
        return (sz.columns, sz.lines)

    def detect_color_depth(self) -> ColorDepth:
        """Check terminal capabilities for color support."""
        if self._color_depth is not None:
            return self._color_depth

        if not hasattr(self._stream, "isatty") or not self._stream.isatty():
            self._color_depth = ColorDepth.NONE
            return self._color_depth

        colorterm = os.environ.get("COLORTERM", "").lower()
        if colorterm in ("truecolor", "24bit"):
            self._color_depth = ColorDepth.TRUECOLOR
            return self._color_depth

        term = os.environ.get("TERM", "").lower()
        if "256color" in term:
            self._color_depth = ColorDepth.EIGHT_BIT
            return self._color_depth

        if term:
            self._color_depth = ColorDepth.BASIC
            return self._color_depth

        self._color_depth = ColorDepth.BASIC
        return self._color_depth

    def apply_style(self, style: Style) -> str:
        """Convert Style to ANSI SGR escape sequence."""
        codes: list[str] = []

        if style.bold:
            codes.append("1")
        if style.dim:
            codes.append("2")
        if style.italic:
            codes.append("3")
        if style.underline:
            codes.append("4")
        if style.reverse:
            codes.append("7")

        if style.fg is not None:
            codes.extend(self._color_codes(style.fg, foreground=True))
        if style.bg is not None:
            codes.extend(self._color_codes(style.bg, foreground=False))

        if not codes:
            return ""
        return f"\x1b[{';'.join(codes)}m"

    def _color_codes(self, color: str | int, foreground: bool) -> list[str]:
        """Convert a color value to SGR parameter strings."""
        base = 30 if foreground else 40

        if isinstance(color, int):
            # 256-color
            prefix = "38" if foreground else "48"
            return [prefix, "5", str(color)]

        if isinstance(color, str):
            if color.startswith("#") and len(color) == 7:
                # Hex RGB
                r = int(color[1:3], 16)
                g = int(color[3:5], 16)
                b = int(color[5:7], 16)
                prefix = "38" if foreground else "48"
                return [prefix, "2", str(r), str(g), str(b)]

            # Named color
            idx = NAMED_COLORS.get(color.lower())
            if idx is not None:
                return [str(base + idx)]

        return []

    def reset_style(self) -> str:
        """SGR reset sequence."""
        return "\x1b[0m"

    def move_cursor(self, x: int, y: int) -> str:
        """CSI escape for cursor positioning (1-based)."""
        return f"\x1b[{y + 1};{x + 1}H"

    def write_frame(self, writes: list[CellWrite]) -> None:
        """Render cell writes to terminal. Batches into a single write call."""
        if not writes:
            return

        parts: list[str] = []

        # Synchronized output: begin (Mode 2026)
        parts.append("\x1b[?2026h")

        last_style: Style | None = None

        for w in writes:
            parts.append(self.move_cursor(w.x, w.y))

            if w.cell.style != last_style:
                parts.append(self.reset_style())
                sgr = self.apply_style(w.cell.style)
                if sgr:
                    parts.append(sgr)
                last_style = w.cell.style

            parts.append(w.cell.char)

        parts.append(self.reset_style())

        # Synchronized output: end
        parts.append("\x1b[?2026l")

        self._stream.write("".join(parts))
        self._stream.flush()

    def enter_alt_screen(self) -> None:
        self._stream.write("\x1b[?1049h")
        self._stream.flush()

    def exit_alt_screen(self) -> None:
        self._stream.write("\x1b[?1049l")
        self._stream.flush()

    def hide_cursor(self) -> None:
        self._stream.write("\x1b[?25l")
        self._stream.flush()

    def show_cursor(self) -> None:
        self._stream.write("\x1b[?25h")
        self._stream.flush()

    def enable_mouse(self, *, all_motion: bool = False) -> None:
        """Enable SGR mouse tracking.

        Args:
            all_motion: If True, report all mouse motion (mode 1003).
                        If False, only report button events and drags (mode 1002).
        """
        # Mode 1002 = button-event tracking (press, release, drag)
        # Mode 1003 = any-event tracking (all motion, high volume)
        tracking_mode = 1003 if all_motion else 1002
        self._stream.write(f"\x1b[?{tracking_mode}h")  # Enable tracking
        self._stream.write("\x1b[?1006h")  # Enable SGR encoding
        self._stream.flush()

    def disable_mouse(self) -> None:
        """Disable mouse tracking."""
        self._stream.write("\x1b[?1002l")  # Disable button-event
        self._stream.write("\x1b[?1003l")  # Disable any-event
        self._stream.write("\x1b[?1006l")  # Disable SGR encoding
        self._stream.flush()


def print_block(
    block: "Block",
    stream: TextIO = sys.stdout,
    *,
    use_ansi: bool = True,
) -> None:
    """Print a Block to a stream, optionally with ANSI styling.

    Renders the block line-by-line. When use_ansi is True, includes ANSI
    escape codes for styling. When False, outputs plain text only.

    Args:
        block: The Block to print.
        stream: Output stream (defaults to stdout).
        use_ansi: Whether to include ANSI escape codes (default True).
    """
    if use_ansi:
        writer = Writer(stream)
        _write_block_ansi(block, writer, stream)
    else:
        # Plain text: just characters, no styling
        for row_idx in range(block.height):
            for cell in block.row(row_idx):
                stream.write(cell.char)
            stream.write("\n")

    stream.flush()


def _write_block_ansi(block: "Block", writer: Writer, stream: TextIO) -> None:
    """Write a Block to a stream with ANSI styling, line-by-line.

    Shared by `print_block` and `InPlaceRenderer`.
    """
    for row_idx in range(block.height):
        parts: list[str] = []
        last_style: Style | None = None

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
