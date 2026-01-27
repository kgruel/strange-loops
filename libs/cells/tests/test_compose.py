"""Tests for cells.compose: vslice."""

from cells.block import Block
from cells.cell import Style, Cell
from cells.compose import vslice


def _text_block(lines: list[str], style: Style = Style()) -> Block:
    """Helper: build a Block from lines of text, width = max line length."""
    width = max(len(l) for l in lines) if lines else 0
    rows = []
    for line in lines:
        row = [Cell(ch, style) for ch in line]
        # pad to width
        row += [Cell(" ", style)] * (width - len(line))
        rows.append(row)
    return Block(rows, width)


def _row_text(block: Block, row_idx: int) -> str:
    return "".join(c.char for c in block.row(row_idx))


class TestVslice:
    def test_basic_slice(self):
        b = _text_block(["aaa", "bbb", "ccc", "ddd", "eee"])
        result = vslice(b, 1, 2)
        assert result.height == 2
        assert result.width == 3
        assert _row_text(result, 0) == "bbb"
        assert _row_text(result, 1) == "ccc"

    def test_offset_zero(self):
        b = _text_block(["aaa", "bbb", "ccc"])
        result = vslice(b, 0, 2)
        assert result.height == 2
        assert _row_text(result, 0) == "aaa"
        assert _row_text(result, 1) == "bbb"

    def test_offset_beyond_content(self):
        b = _text_block(["aaa", "bbb"])
        result = vslice(b, 5, 2)
        assert result.height == 0
        assert result.width == 3

    def test_height_larger_than_content(self):
        b = _text_block(["aaa", "bbb", "ccc"])
        result = vslice(b, 1, 10)
        assert result.height == 2
        assert _row_text(result, 0) == "bbb"
        assert _row_text(result, 1) == "ccc"

    def test_empty_block(self):
        b = Block.empty(5, 0)
        result = vslice(b, 0, 3)
        assert result.height == 0
        assert result.width == 5

    def test_single_row_block(self):
        b = _text_block(["hello"])
        result = vslice(b, 0, 1)
        assert result.height == 1
        assert _row_text(result, 0) == "hello"

    def test_single_row_offset_past(self):
        b = _text_block(["hello"])
        result = vslice(b, 1, 1)
        assert result.height == 0

    def test_negative_offset_clamped(self):
        b = _text_block(["aaa", "bbb", "ccc"])
        result = vslice(b, -2, 2)
        assert result.height == 2
        assert _row_text(result, 0) == "aaa"
        assert _row_text(result, 1) == "bbb"

    def test_preserves_width(self):
        b = _text_block(["abcde", "fghij"])
        result = vslice(b, 0, 1)
        assert result.width == 5

    def test_full_block_slice(self):
        b = _text_block(["aa", "bb", "cc"])
        result = vslice(b, 0, 3)
        assert result.height == 3
        assert _row_text(result, 0) == "aa"
        assert _row_text(result, 1) == "bb"
        assert _row_text(result, 2) == "cc"
