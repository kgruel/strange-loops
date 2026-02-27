"""Tests for list_view() render function."""

from painted import Style
from painted.span import Line, Span
from painted.views import ListState, list_view
from painted import Cursor, Viewport


def _row_text(block, idx: int) -> str:
    """Extract the text content of a block row."""
    return "".join(cell.char for cell in block.row(idx))


class TestListViewEmpty:
    def test_empty_items_returns_empty_block(self) -> None:
        state = ListState()
        block = list_view(state, [], visible_height=5)

        assert block.width == 1
        assert block.height == 5

    def test_empty_items_all_spaces(self) -> None:
        state = ListState()
        block = list_view(state, [], visible_height=3)

        for y in range(block.height):
            text = _row_text(block, y)
            assert text.strip() == ""


class TestListViewBasicRender:
    def test_renders_items_with_prefix(self) -> None:
        items = [Line.plain("alpha"), Line.plain("beta"), Line.plain("gamma")]
        state = ListState(cursor=Cursor(index=0, count=3))
        block = list_view(state, items, visible_height=3)

        row0 = _row_text(block, 0)
        row1 = _row_text(block, 1)
        row2 = _row_text(block, 2)

        assert "alpha" in row0
        assert "beta" in row1
        assert "gamma" in row2

    def test_block_dimensions(self) -> None:
        items = [Line.plain("abc"), Line.plain("de")]
        state = ListState(cursor=Cursor(index=0, count=2))
        block = list_view(state, items, visible_height=3)

        assert block.height == 3
        # Width = max item width (3) + 2 for cursor prefix
        assert block.width == 5


class TestListViewCursor:
    def test_cursor_char_on_selected(self) -> None:
        items = [Line.plain("first"), Line.plain("second")]
        state = ListState(cursor=Cursor(index=0, count=2))
        block = list_view(state, items, visible_height=2)

        row0 = _row_text(block, 0)
        assert row0.startswith("\u25b8 ")  # default cursor_char

    def test_space_on_unselected(self) -> None:
        items = [Line.plain("first"), Line.plain("second")]
        state = ListState(cursor=Cursor(index=0, count=2))
        block = list_view(state, items, visible_height=2)

        row1 = _row_text(block, 1)
        assert row1.startswith("  ")  # space prefix, not cursor

    def test_custom_cursor_char(self) -> None:
        items = [Line.plain("item")]
        state = ListState(cursor=Cursor(index=0, count=1))
        block = list_view(state, items, visible_height=1, cursor_char=">")

        row0 = _row_text(block, 0)
        assert row0.startswith("> ")

    def test_cursor_moves_with_selection(self) -> None:
        items = [Line.plain("a"), Line.plain("b"), Line.plain("c")]
        state = ListState(cursor=Cursor(index=2, count=3))
        block = list_view(state, items, visible_height=3)

        row0 = _row_text(block, 0)
        row2 = _row_text(block, 2)
        assert row0.startswith("  ")
        assert row2.startswith("\u25b8 ")


class TestListViewSelectedStyle:
    def test_selected_row_has_reverse_style(self) -> None:
        items = [Line.plain("one"), Line.plain("two")]
        state = ListState(cursor=Cursor(index=0, count=2))
        sel_style = Style(reverse=True)
        block = list_view(state, items, visible_height=2, selected_style=sel_style)

        # All cells in the selected row should have reverse=True
        for cell in block.row(0):
            assert cell.style.reverse is True

    def test_unselected_row_no_reverse(self) -> None:
        items = [Line.plain("one"), Line.plain("two")]
        state = ListState(cursor=Cursor(index=0, count=2))
        block = list_view(state, items, visible_height=2)

        # Unselected row cells should not have reverse
        for cell in block.row(1):
            assert cell.style.reverse is not True

    def test_custom_selected_style(self) -> None:
        items = [Line.plain("x")]
        state = ListState(cursor=Cursor(index=0, count=1))
        custom = Style(bold=True)
        block = list_view(state, items, visible_height=1, selected_style=custom)

        # The prefix cell should have bold
        assert block.row(0)[0].style.bold is True

    def test_fill_cells_have_selected_style(self) -> None:
        """Selected row fill (beyond text) should also carry selected_style."""
        items = [Line.plain("ab"), Line.plain("long item")]
        state = ListState(cursor=Cursor(index=0, count=2))
        sel_style = Style(reverse=True)
        block = list_view(state, items, visible_height=2, selected_style=sel_style)

        # Row 0 is selected; all cells (including fill) should be reverse
        for cell in block.row(0):
            assert cell.style.reverse is True


class TestListViewScrolling:
    def test_viewport_offset_shows_correct_items(self) -> None:
        items = [Line.plain(f"item-{i}") for i in range(10)]
        state = ListState(
            cursor=Cursor(index=5, count=10),
            viewport=Viewport(offset=3, visible=4, content=10),
        )
        block = list_view(state, items, visible_height=4)

        # Visible window: items 3, 4, 5, 6
        assert "item-3" in _row_text(block, 0)
        assert "item-4" in _row_text(block, 1)
        assert "item-5" in _row_text(block, 2)
        assert "item-6" in _row_text(block, 3)

    def test_cursor_in_scrolled_view(self) -> None:
        items = [Line.plain(f"item-{i}") for i in range(10)]
        state = ListState(
            cursor=Cursor(index=5, count=10),
            viewport=Viewport(offset=3, visible=4, content=10),
        )
        block = list_view(state, items, visible_height=4)

        # item-5 is selected, which is at visual row 2 (offset=3, 5-3=2)
        row2 = _row_text(block, 2)
        assert row2.startswith("\u25b8 ")

    def test_items_exceeding_visible_height(self) -> None:
        items = [Line.plain(f"row-{i}") for i in range(20)]
        state = ListState(
            cursor=Cursor(index=0, count=20),
            viewport=Viewport(offset=0, visible=5, content=20),
        )
        block = list_view(state, items, visible_height=5)

        # Only 5 rows rendered
        assert block.height == 5
        assert "row-0" in _row_text(block, 0)
        assert "row-4" in _row_text(block, 4)

    def test_scroll_near_end(self) -> None:
        items = [Line.plain(f"n{i}") for i in range(10)]
        state = ListState(
            cursor=Cursor(index=9, count=10),
            viewport=Viewport(offset=7, visible=3, content=10),
        )
        block = list_view(state, items, visible_height=3)

        assert "n7" in _row_text(block, 0)
        assert "n8" in _row_text(block, 1)
        assert "n9" in _row_text(block, 2)

        # n9 is selected (index=9, offset=7, visual row=2)
        assert _row_text(block, 2).startswith("\u25b8 ")


class TestListStateWithVisible:
    def test_with_visible_updates_viewport(self) -> None:
        state = ListState(cursor=Cursor(count=10))
        state2 = state.with_visible(5)

        assert state2.viewport.visible == 5


class TestListViewWidthCalculation:
    def test_width_accounts_for_widest_visible_item(self) -> None:
        items = [Line.plain("short"), Line.plain("a longer item")]
        state = ListState(cursor=Cursor(index=0, count=2))
        block = list_view(state, items, visible_height=2)

        # max visible item width = 13 ("a longer item") + 2 cursor prefix = 15
        assert block.width == 15

    def test_single_item(self) -> None:
        items = [Line.plain("only")]
        state = ListState(cursor=Cursor(index=0, count=1))
        block = list_view(state, items, visible_height=3)

        assert block.height == 3
        assert "only" in _row_text(block, 0)
