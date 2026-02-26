"""Tests for ListState cursor/viewport composition."""

from painted import Cursor, Viewport
from painted.views import ListState


class TestListStateCursor:
    def test_move_clamps(self) -> None:
        state = ListState(cursor=Cursor(count=3))

        assert state.selected == 0
        assert state.move_up().selected == 0
        assert state.move_down().selected == 1
        assert state.move_to(99).selected == 2

    def test_with_count_clamps_selection_and_scroll(self) -> None:
        state = ListState(
            cursor=Cursor(index=9, count=10),
            viewport=Viewport(offset=9, visible=5, content=10),
        )
        state2 = state.with_count(3)

        assert state2.item_count == 3
        assert state2.selected == 2
        assert state2.scroll_offset == 0  # max_offset = max(0, 3-5) = 0


class TestListStateViewport:
    def test_scroll_into_view_delegates_to_viewport(self) -> None:
        state = ListState(cursor=Cursor(index=15, count=30), viewport=Viewport(offset=0))
        state2 = state.scroll_into_view(visible_height=10)

        expected = Viewport(offset=0, visible=10, content=30).scroll_into_view(15).offset
        assert state2.scroll_offset == expected
