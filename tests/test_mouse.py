"""Tests for mouse input parsing."""

import pytest
from fidelis.mouse import (
    MouseEvent,
    MouseButton,
    MouseAction,
)
from fidelis._mouse import parse_sgr_mouse


class TestMouseEvent:
    def test_is_frozen(self):
        event = MouseEvent(MouseAction.PRESS, MouseButton.LEFT, 10, 5)
        with pytest.raises(AttributeError):
            event.x = 20

    def test_is_scroll(self):
        scroll = MouseEvent(MouseAction.SCROLL, MouseButton.SCROLL_UP, 0, 0)
        click = MouseEvent(MouseAction.PRESS, MouseButton.LEFT, 0, 0)
        assert scroll.is_scroll
        assert not click.is_scroll

    def test_is_click(self):
        click = MouseEvent(MouseAction.PRESS, MouseButton.LEFT, 0, 0)
        release = MouseEvent(MouseAction.RELEASE, MouseButton.LEFT, 0, 0)
        scroll = MouseEvent(MouseAction.SCROLL, MouseButton.SCROLL_UP, 0, 0)
        assert click.is_click
        assert not release.is_click
        assert not scroll.is_click

    def test_scroll_delta(self):
        up = MouseEvent(MouseAction.SCROLL, MouseButton.SCROLL_UP, 0, 0)
        down = MouseEvent(MouseAction.SCROLL, MouseButton.SCROLL_DOWN, 0, 0)
        click = MouseEvent(MouseAction.PRESS, MouseButton.LEFT, 0, 0)
        assert up.scroll_delta == -1
        assert down.scroll_delta == 1
        assert click.scroll_delta == 0

    def test_translate(self):
        event = MouseEvent(MouseAction.PRESS, MouseButton.LEFT, 10, 5)
        translated = event.translate(3, 2)
        assert translated.x == 7
        assert translated.y == 3
        assert translated.action == MouseAction.PRESS
        assert translated.button == MouseButton.LEFT


class TestParseSgrMouse:
    def test_left_click(self):
        # CSI < 0 ; 10 ; 5 M
        event = parse_sgr_mouse("0;10;5", "M")
        assert event is not None
        assert event.action == MouseAction.PRESS
        assert event.button == MouseButton.LEFT
        assert event.x == 9  # 0-indexed
        assert event.y == 4

    def test_left_release(self):
        # CSI < 0 ; 10 ; 5 m
        event = parse_sgr_mouse("0;10;5", "m")
        assert event is not None
        assert event.action == MouseAction.RELEASE
        assert event.button == MouseButton.LEFT

    def test_middle_click(self):
        event = parse_sgr_mouse("1;5;3", "M")
        assert event is not None
        assert event.button == MouseButton.MIDDLE

    def test_right_click(self):
        event = parse_sgr_mouse("2;5;3", "M")
        assert event is not None
        assert event.button == MouseButton.RIGHT

    def test_scroll_up(self):
        # Button 64 = scroll up
        event = parse_sgr_mouse("64;15;8", "M")
        assert event is not None
        assert event.action == MouseAction.SCROLL
        assert event.button == MouseButton.SCROLL_UP
        assert event.x == 14
        assert event.y == 7

    def test_scroll_down(self):
        # Button 65 = scroll down
        event = parse_sgr_mouse("65;15;8", "M")
        assert event is not None
        assert event.action == MouseAction.SCROLL
        assert event.button == MouseButton.SCROLL_DOWN

    def test_left_drag(self):
        # Button 32 = left drag (motion with button held)
        event = parse_sgr_mouse("32;12;6", "M")
        assert event is not None
        assert event.action == MouseAction.MOVE
        assert event.button == MouseButton.LEFT

    def test_ctrl_modifier(self):
        # Ctrl adds 16 to button code
        event = parse_sgr_mouse("16;5;3", "M")
        assert event is not None
        assert event.ctrl
        assert not event.shift
        assert not event.meta
        assert event.button == MouseButton.LEFT

    def test_shift_modifier(self):
        # Shift adds 4 to button code
        event = parse_sgr_mouse("4;5;3", "M")
        assert event is not None
        assert event.shift
        assert not event.ctrl

    def test_meta_modifier(self):
        # Meta adds 8 to button code
        event = parse_sgr_mouse("8;5;3", "M")
        assert event is not None
        assert event.meta

    def test_combined_modifiers(self):
        # Ctrl+Shift = 16 + 4 = 20
        event = parse_sgr_mouse("20;5;3", "M")
        assert event is not None
        assert event.ctrl
        assert event.shift
        assert not event.meta

    def test_malformed_missing_params(self):
        event = parse_sgr_mouse("0;10", "M")
        assert event is None

    def test_malformed_not_numbers(self):
        event = parse_sgr_mouse("a;b;c", "M")
        assert event is None

    def test_large_coordinates(self):
        # SGR supports large coordinates (unlike legacy protocol)
        event = parse_sgr_mouse("0;500;200", "M")
        assert event is not None
        assert event.x == 499
        assert event.y == 199


class TestMouseButton:
    def test_button_values(self):
        assert MouseButton.LEFT.value == 0
        assert MouseButton.MIDDLE.value == 1
        assert MouseButton.RIGHT.value == 2
        assert MouseButton.SCROLL_UP.value == 64
        assert MouseButton.SCROLL_DOWN.value == 65


class TestMouseAction:
    def test_action_types(self):
        assert MouseAction.PRESS is not None
        assert MouseAction.RELEASE is not None
        assert MouseAction.MOVE is not None
        assert MouseAction.SCROLL is not None
