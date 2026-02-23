"""Tests for TableState cursor/viewport composition."""

from fidelis import Cursor, Viewport
from fidelis.widgets import TableState


class TestTableStateCursor:
    def test_move_clamps(self) -> None:
        state = TableState(cursor=Cursor(count=3))

        assert state.selected_row == 0
        assert state.move_up().selected_row == 0
        assert state.move_down().selected_row == 1
        assert state.move_to(99).selected_row == 2

    def test_with_count_clamps_selection_and_scroll(self) -> None:
        state = TableState(
            cursor=Cursor(index=9, count=10),
            viewport=Viewport(offset=9, visible=5, content=10),
        )
        state2 = state.with_count(3)

        assert state2.row_count == 3
        assert state2.selected_row == 2
        assert state2.scroll_offset == 0


class TestTableStateViewport:
    def test_scroll_into_view_delegates_to_viewport(self) -> None:
        state = TableState(cursor=Cursor(index=15, count=30), viewport=Viewport(offset=0))
        state2 = state.scroll_into_view(visible_height=10)

        expected = Viewport(offset=0, visible=10, content=30).scroll_into_view(15).offset
        assert state2.scroll_offset == expected

