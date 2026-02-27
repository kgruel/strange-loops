"""Scroll optimization integration tests.

These tests validate the writer-level scroll commands and the Surface flush
path that detects and applies scroll operations instead of full repaint.
"""

from __future__ import annotations

import io
import re

from painted.buffer import Buffer
from painted.cell import Style
from painted.tui import Surface
from painted.writer import ScrollOp, Writer


def _count_cups(output: str) -> int:
    """Count CUP (cursor position) sequences in raw ANSI output."""
    return len(re.findall(r"\x1b\[\d+;\d+H", output))


def _fill_line(buf: Buffer, y: int, ch: str) -> None:
    buf.put_text(0, y, ch * buf.width, Style())


class TestWriterScrollOps:
    def test_scroll_up_emits_region_and_su(self):
        stream = io.StringIO()
        w = Writer(stream)

        w.write_ops([ScrollOp(top=1, bottom=3, n=1)])

        out = stream.getvalue()
        assert "\x1b[?2026h" in out
        assert "\x1b[2;4r" in out  # DECSTBM (1-based)
        assert "\x1b[4;1H" in out  # move to bottom of region
        assert "\x1b[1S" in out  # SU
        assert "\x1b[r" in out  # reset margins
        assert "\x1b[?2026l" in out

    def test_scroll_down_emits_region_and_sd(self):
        stream = io.StringIO()
        w = Writer(stream)

        w.write_ops([ScrollOp(top=2, bottom=5, n=-2)])

        out = stream.getvalue()
        assert "\x1b[3;6r" in out  # DECSTBM (1-based)
        assert "\x1b[3;1H" in out  # move to top of region
        assert "\x1b[2T" in out  # SD
        assert "\x1b[r" in out


class TestSurfaceScrollOptimization:
    def test_surface_flush_uses_scroll_op_for_vertical_shift(self):
        width, height = 8, 10
        stream = io.StringIO()

        surface = Surface(scroll_optimization=True)
        surface._writer = Writer(stream)  # test-only: capture output

        prev = Buffer(width, height)
        cur = Buffer(width, height)

        # Stable chrome
        _fill_line(prev, 0, "H")
        _fill_line(cur, 0, "H")
        _fill_line(prev, 9, "F")
        _fill_line(cur, 9, "F")

        # Scrollable region y=1..8 shifts up by 1.
        _fill_line(prev, 1, "A")
        _fill_line(prev, 2, "B")
        _fill_line(prev, 3, "C")
        _fill_line(prev, 4, "D")
        _fill_line(prev, 5, "E")
        _fill_line(prev, 6, "F")
        _fill_line(prev, 7, "G")
        _fill_line(prev, 8, "H")

        _fill_line(cur, 1, "B")
        _fill_line(cur, 2, "C")
        _fill_line(cur, 3, "D")
        _fill_line(cur, 4, "E")
        _fill_line(cur, 5, "F")
        _fill_line(cur, 6, "G")
        _fill_line(cur, 7, "H")
        _fill_line(cur, 8, "Z")  # inserted line

        surface._prev = prev
        surface._buf = cur

        surface._flush()

        out = stream.getvalue()
        assert "\x1b[2;9r" in out  # scroll region
        assert "\x1b[1S" in out  # scroll up by 1

        # With coalescing, the inserted line needs only 1 CUP (not 8).
        # Scroll ops add 2 more (region top/bottom positioning).
        cup_count = _count_cups(out)
        assert 1 <= cup_count <= 5

    def test_surface_flush_falls_back_when_disabled(self):
        width, height = 8, 10
        stream = io.StringIO()

        surface = Surface(scroll_optimization=False)
        surface._writer = Writer(stream)

        prev = Buffer(width, height)
        cur = Buffer(width, height)

        _fill_line(prev, 0, "H")
        _fill_line(cur, 0, "H")
        _fill_line(prev, 9, "F")
        _fill_line(cur, 9, "F")

        _fill_line(prev, 1, "A")
        _fill_line(prev, 2, "B")
        _fill_line(prev, 3, "C")
        _fill_line(prev, 4, "D")
        _fill_line(prev, 5, "E")
        _fill_line(prev, 6, "F")
        _fill_line(prev, 7, "G")
        _fill_line(prev, 8, "H")

        _fill_line(cur, 1, "B")
        _fill_line(cur, 2, "C")
        _fill_line(cur, 3, "D")
        _fill_line(cur, 4, "E")
        _fill_line(cur, 5, "F")
        _fill_line(cur, 6, "G")
        _fill_line(cur, 7, "H")
        _fill_line(cur, 8, "Z")

        surface._prev = prev
        surface._buf = cur
        surface._flush()

        out = stream.getvalue()
        assert "\x1b[1S" not in out
        assert "\x1b[2;9r" not in out

        # Without scroll optimization, every changed row gets a CUP.
        # 8 changed lines = 8 CUPs (one per line with coalescing).
        cup_count = _count_cups(out)
        assert cup_count >= 8
