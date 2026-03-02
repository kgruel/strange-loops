"""Wide-character display-width correctness tests.

These tests assert that display-critical code paths use wcwidth/wcswidth
semantics (terminal columns), not code-point counts.
"""

from __future__ import annotations

from painted import Block, Style, Wrap, border
from painted._components.text_input import TextInputState, text_input
from painted._text_width import display_width
from painted.block import _word_wrap


def _row_chars(block: Block, y: int = 0) -> list[str]:
    return [c.char for c in block.row(y)]


class TestBlockTextWide:
    def test_width_none_uses_display_width(self):
        content = "A世界B"  # widths: 1 + 4 + 1 = 6
        b = Block.text(content, Style())
        assert b.width == 6
        assert len(b.row(0)) == 6

    def test_wrap_none_truncates_by_columns(self):
        content = "A世B"  # widths: 1 + 2 + 1 = 4
        b = Block.text(content, Style(), width=3, wrap=Wrap.NONE)
        assert b.width == 3
        assert b.height == 1
        assert _row_chars(b)[:2] == ["A", "世"]

    def test_wrap_ellipsis_truncates_by_columns(self):
        content = "A世界B"  # width 6
        b = Block.text(content, Style(), width=4, wrap=Wrap.ELLIPSIS)
        assert b.width == 4
        row = _row_chars(b)
        assert "…" in row

    def test_wrap_char_breaks_on_wide_boundary(self):
        content = "A世B"
        b = Block.text(content, Style(), width=3, wrap=Wrap.CHAR)
        assert b.width == 3
        assert b.height == 2
        assert _row_chars(b, 0)[:2] == ["A", "世"]
        assert _row_chars(b, 1)[0] == "B"

    def test_wrap_word_respects_display_width(self):
        text = "hello 世界 there"
        b = Block.text(text, Style(), width=6, wrap=Wrap.WORD)
        assert b.width == 6
        assert b.height == 3


class TestWordWrapWide:
    def test_word_wrap_wide_words(self):
        lines = _word_wrap("hello 世界 there", 6)
        assert lines == ["hello", "世界", "there"]
        assert all(display_width(line) <= 6 for line in lines)

    def test_word_wrap_breaks_long_wide_word(self):
        lines = _word_wrap("世界世界", 3)
        assert lines == ["世", "界", "世", "界"]
        assert all(display_width(line) <= 3 for line in lines)


class TestBorderTitleWide:
    def test_title_painted_with_wide_chars(self):
        b = Block.empty(7, 1)
        framed = border(b, title="世界")
        top = _row_chars(framed, 0)
        assert top[3] == "世"
        assert top[5] == "界"

    def test_title_guard_uses_display_width(self):
        b = Block.empty(6, 1)
        framed = border(b, title="世界")
        top = _row_chars(framed, 0)
        assert "世" not in top
        assert "界" not in top


class TestTextInputWide:
    def test_set_text_end_cursor_scrolls_by_columns(self):
        state = TextInputState().set_text("A世界B")
        state = state._ensure_visible(4)
        assert state.scroll_offset == 2  # start at "界"

        block = text_input(state, 4, focused=True)
        assert block.width == 4
        last = block.row(0)[-1]
        assert last.char == " "
        assert last.style.reverse is True

    def test_cursor_on_wide_char_styles_both_cells(self):
        state = TextInputState(text="A世界B", cursor=1, scroll_offset=0)
        block = text_input(state, 4, focused=True)
        row = block.row(0)
        # cursor at index 1 points at "世" (2 columns)
        assert row[1].char == "世"
        assert row[1].style.reverse is True
        assert row[2].char == " "
        assert row[2].style.reverse is True
