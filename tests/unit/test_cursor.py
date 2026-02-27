"""Tests for Cursor primitive."""

import pytest

from painted import Cursor, CursorMode


class TestCursorClamp:
    def test_default_empty(self) -> None:
        c = Cursor()
        assert c.mode == CursorMode.CLAMP
        assert c.count == 0
        assert c.index == 0

    def test_clamps_negative(self) -> None:
        c = Cursor(index=-3, count=5, mode=CursorMode.CLAMP)
        assert c.index == 0

    def test_clamps_too_large(self) -> None:
        c = Cursor(index=99, count=5, mode=CursorMode.CLAMP)
        assert c.index == 4

    def test_move_respects_bounds(self) -> None:
        c = Cursor(index=0, count=2, mode=CursorMode.CLAMP).prev()
        assert c.index == 0

        c = Cursor(index=1, count=2, mode=CursorMode.CLAMP).next()
        assert c.index == 1

    def test_end_empty_is_zero(self) -> None:
        assert Cursor(count=0).end().index == 0


class TestCursorWrap:
    def test_wraps_forward(self) -> None:
        c = Cursor(index=2, count=3, mode=CursorMode.WRAP).next()
        assert c.index == 0

    def test_wraps_backward(self) -> None:
        c = Cursor(index=0, count=3, mode=CursorMode.WRAP).prev()
        assert c.index == 2

    def test_empty_wrap_stays_zero(self) -> None:
        c = Cursor(index=10, count=0, mode=CursorMode.WRAP).next()
        assert c.index == 0


def test_cursor_is_frozen() -> None:
    c = Cursor()
    with pytest.raises((AttributeError, TypeError)):
        c.index = 2  # type: ignore[misc]

