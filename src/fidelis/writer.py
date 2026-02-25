"""Writer: terminal output via ANSI escape sequences."""

from __future__ import annotations

from dataclasses import dataclass
import os
import shutil
import sys
from enum import Enum
from typing import TYPE_CHECKING, TextIO, Union

from wcwidth import wcwidth

from .buffer import CellWrite
from .cell import Cell, Style, NAMED_COLORS

if TYPE_CHECKING:
    from .block import Block


class ColorDepth(Enum):
    NONE = 0
    BASIC = 16
    EIGHT_BIT = 256
    TRUECOLOR = 16_777_216


_CUBE_START = 16
_GRAY_START = 232

_BASIC_RGB: tuple[tuple[int, int, int], ...] = (
    (0, 0, 0),        # 0: black
    (128, 0, 0),      # 1: red
    (0, 128, 0),      # 2: green
    (128, 128, 0),    # 3: yellow
    (0, 0, 128),      # 4: blue
    (128, 0, 128),    # 5: magenta
    (0, 128, 128),    # 6: cyan
    (192, 192, 192),  # 7: white
    (128, 128, 128),  # 8: bright black (gray)
    (255, 0, 0),      # 9: bright red
    (0, 255, 0),      # 10: bright green
    (255, 255, 0),    # 11: bright yellow
    (0, 0, 255),      # 12: bright blue
    (255, 0, 255),    # 13: bright magenta
    (0, 255, 255),    # 14: bright cyan
    (255, 255, 255),  # 15: bright white
)


def _color_distance_sq(r1: int, g1: int, b1: int, r2: int, g2: int, b2: int) -> int:
    """Squared Euclidean distance in RGB space."""
    return (r1 - r2) ** 2 + (g1 - g2) ** 2 + (b1 - b2) ** 2


def _idx_to_rgb(idx: int) -> tuple[int, int, int]:
    """Convert a 256-color index to approximate RGB."""
    if idx < 16:
        return _BASIC_RGB[idx]
    if idx < _GRAY_START:
        idx -= _CUBE_START
        b = (idx % 6) * 51
        idx //= 6
        g = (idx % 6) * 51
        r = (idx // 6) * 51
        return (r, g, b)
    gray = 8 + (idx - _GRAY_START) * 10
    return (gray, gray, gray)


def _rgb_to_256(r: int, g: int, b: int) -> int:
    """Find nearest 256-color index for an RGB value."""
    best_idx = 16
    best_dist = _color_distance_sq(r, g, b, *_idx_to_rgb(16))
    for i in range(17, 256):
        ir, ig, ib = _idx_to_rgb(i)
        d = _color_distance_sq(r, g, b, ir, ig, ib)
        if d < best_dist:
            best_dist = d
            best_idx = i
    return best_idx


def _rgb_to_basic(r: int, g: int, b: int) -> int:
    """Find nearest basic 16-color index for an RGB value."""
    best_idx = 0
    best_dist = _color_distance_sq(r, g, b, *_BASIC_RGB[0])
    for i in range(1, 16):
        d = _color_distance_sq(r, g, b, *_BASIC_RGB[i])
        if d < best_dist:
            best_dist = d
            best_idx = i
    return best_idx


def _nearest_basic(idx_256: int) -> int:
    """Convert a 256-color index to the nearest basic 16-color index."""
    r, g, b = _idx_to_rgb(idx_256)
    return _rgb_to_basic(r, g, b)


class Writer:
    """Converts cell writes to ANSI escape sequences and outputs to terminal.

    Automatically downgrades colors when terminal color depth is limited.
    Capabilities resolve at this boundary — views express intent (Style),
    Writer resolves against detected terminal capability.
    """

    def __init__(self, stream: TextIO = sys.stdout, *, color_depth: ColorDepth | None = None):
        self._stream = stream
        # When provided, forces color capability resolution (useful for tests and
        # non-interactive environments where isatty() is false).
        self._color_depth: ColorDepth | None = color_depth

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
        """Convert a color value to SGR parameter strings.

        Automatically downgrades colors when terminal color depth is limited:
        - Hex RGB -> truecolor / 256-color / 16-color, as needed
        - 256-color index -> 16-color, as needed
        - Named colors always emit as basic SGR (already safe)
        """
        depth = self.detect_color_depth()
        base = 30 if foreground else 40

        if isinstance(color, int):
            if depth.value >= ColorDepth.EIGHT_BIT.value:
                prefix = "38" if foreground else "48"
                return [prefix, "5", str(color)]
            return [str(base + _nearest_basic(color))]

        if isinstance(color, str):
            if color.startswith("#") and len(color) == 7:
                r = int(color[1:3], 16)
                g = int(color[3:5], 16)
                b = int(color[5:7], 16)
                if depth == ColorDepth.TRUECOLOR:
                    prefix = "38" if foreground else "48"
                    return [prefix, "2", str(r), str(g), str(b)]
                if depth == ColorDepth.EIGHT_BIT:
                    prefix = "38" if foreground else "48"
                    return [prefix, "5", str(_rgb_to_256(r, g, b))]
                return [str(base + _rgb_to_basic(r, g, b))]

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

    def set_scroll_region(self, top: int, bottom: int) -> str:
        """Set scroll region via DECSTBM (top/bottom margins, 0-based inclusive)."""
        return f"\x1b[{top + 1};{bottom + 1}r"

    def reset_scroll_region(self) -> str:
        """Reset scroll region to full screen (DECSTBM with no params)."""
        return "\x1b[r"

    def scroll_up(self, n: int) -> str:
        """Scroll up (content moves up) by n lines: CSI n S."""
        return f"\x1b[{n}S"

    def scroll_down(self, n: int) -> str:
        """Scroll down (content moves down) by n lines: CSI n T."""
        return f"\x1b[{n}T"

    def write_ops(self, ops: list[RenderOp]) -> None:
        """Render a mixed stream of operations (scroll + cell writes)."""
        if not ops:
            return

        parts: list[str] = []
        parts.append("\x1b[?2026h")  # synchronized output begin

        last_style: Style | None = None
        covered: set[tuple[int, int]] = set()  # trailing cells of wide chars written this frame

        for op in ops:
            if isinstance(op, ScrollOp):
                if op.top > op.bottom or op.n == 0:
                    continue

                top = max(0, op.top)
                bottom = max(top, op.bottom)
                n = op.n

                parts.append(self.reset_style())
                last_style = None

                parts.append(self.set_scroll_region(top, bottom))
                if n > 0:
                    parts.append(self.move_cursor(0, bottom))
                    parts.append(self.scroll_up(n))
                else:
                    parts.append(self.move_cursor(0, top))
                    parts.append(self.scroll_down(-n))
                parts.append(self.reset_scroll_region())
                continue

            # CellWrite
            w = op

            if (w.x, w.y) in covered:
                continue

            parts.append(self.move_cursor(w.x, w.y))

            if w.cell.style != last_style:
                parts.append(self.reset_style())
                sgr = self.apply_style(w.cell.style)
                if sgr:
                    parts.append(sgr)
                last_style = w.cell.style

            parts.append(w.cell.char)

            width = wcwidth(w.cell.char)
            if width and width > 1:
                for dx in range(1, width):
                    covered.add((w.x + dx, w.y))

        parts.append(self.reset_style())
        parts.append("\x1b[?2026l")  # synchronized output end

        self._stream.write("".join(parts))
        self._stream.flush()

    def write_frame(self, writes: list[CellWrite]) -> None:
        """Render cell writes to terminal. Batches into a single write call."""
        self.write_ops(writes)

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


@dataclass(frozen=True)
class ScrollOp:
    """Scroll a region vertically by n lines.

    Coordinates are 0-based, inclusive. Positive n scrolls up (content moves up).
    """

    top: int
    bottom: int
    n: int


RenderOp = Union[CellWrite, ScrollOp]
