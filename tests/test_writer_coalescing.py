"""Writer coalescing: adjacent cells skip redundant cursor moves."""

from __future__ import annotations

import io
import re

from fidelis.buffer import CellWrite
from fidelis.cell import Cell, Style
from fidelis.writer import Writer, ColorDepth, ScrollOp


def _capture(ops) -> str:
    """Run write_ops and return the raw output."""
    buf = io.StringIO()
    w = Writer(buf, color_depth=ColorDepth.TRUECOLOR)
    w.write_ops(ops)
    return buf.getvalue()


def _count_cursor_moves(output: str) -> int:
    """Count CSI cursor position sequences (ESC[row;colH)."""
    return len(re.findall(r"\x1b\[\d+;\d+H", output))


PLAIN = Style()
RED = Style(fg="red")


def _cell(ch: str, style: Style = PLAIN) -> Cell:
    return Cell(ch, style)


class TestAdjacentCellCoalescing:
    def test_single_cell_emits_one_move(self):
        ops = [CellWrite(0, 0, _cell("a"))]
        assert _count_cursor_moves(_capture(ops)) == 1

    def test_adjacent_cells_same_row_one_move(self):
        ops = [
            CellWrite(0, 0, _cell("a")),
            CellWrite(1, 0, _cell("b")),
            CellWrite(2, 0, _cell("c")),
        ]
        assert _count_cursor_moves(_capture(ops)) == 1

    def test_gap_in_row_emits_two_moves(self):
        ops = [
            CellWrite(0, 0, _cell("a")),
            CellWrite(5, 0, _cell("b")),
        ]
        assert _count_cursor_moves(_capture(ops)) == 2

    def test_different_rows_emit_moves(self):
        ops = [
            CellWrite(0, 0, _cell("a")),
            CellWrite(0, 1, _cell("b")),
        ]
        assert _count_cursor_moves(_capture(ops)) == 2

    def test_style_change_no_extra_move(self):
        """Style changes don't affect cursor position — no extra move needed."""
        ops = [
            CellWrite(0, 0, _cell("a", PLAIN)),
            CellWrite(1, 0, _cell("b", RED)),
            CellWrite(2, 0, _cell("c", PLAIN)),
        ]
        assert _count_cursor_moves(_capture(ops)) == 1

    def test_full_row_one_move(self):
        ops = [CellWrite(i, 0, _cell(chr(65 + i % 26))) for i in range(80)]
        assert _count_cursor_moves(_capture(ops)) == 1

    def test_characters_present_in_output(self):
        ops = [
            CellWrite(0, 0, _cell("h")),
            CellWrite(1, 0, _cell("i")),
        ]
        output = _capture(ops)
        assert "hi" in output


class TestWideCellCoalescing:
    def test_wide_char_advances_by_two(self):
        # Wide char at x=0 occupies x=0,1. Next at x=2 should not need a move.
        ops = [
            CellWrite(0, 0, _cell("\uff21")),  # fullwidth A (width 2)
            CellWrite(2, 0, _cell("b")),
        ]
        assert _count_cursor_moves(_capture(ops)) == 1

    def test_wide_char_gap_emits_move(self):
        # Wide char at x=0 occupies x=0,1. Cell at x=3 has a gap.
        ops = [
            CellWrite(0, 0, _cell("\uff21")),  # fullwidth A (width 2)
            CellWrite(3, 0, _cell("b")),
        ]
        assert _count_cursor_moves(_capture(ops)) == 2


class TestScrollResetsCursorTracking:
    def test_scroll_op_resets_cursor(self):
        """After a scroll op, cursor position is unknown — must emit a move."""
        ops = [
            CellWrite(0, 0, _cell("a")),
            CellWrite(1, 0, _cell("b")),
            ScrollOp(top=0, bottom=10, n=1),
            CellWrite(2, 0, _cell("c")),
        ]
        output = _capture(ops)
        # First cell needs a move, second is coalesced, scroll resets,
        # third needs a move.
        assert _count_cursor_moves(output) == 3  # cell a + scroll move + cell c
