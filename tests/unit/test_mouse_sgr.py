"""Tests for SGR mouse parsing and KeyboardInput integration."""

from __future__ import annotations

from unittest.mock import patch

import pytest

from painted._mouse import MouseAction, MouseButton, MouseEvent, parse_sgr_mouse
from painted.tui import KeyboardInput


def _bytes_stream(data: bytes) -> list[bytes]:
    return [bytes([b]) for b in data]


def _get_input_from_bytes(data: bytes):
    kb = KeyboardInput()
    kb._available = True
    stream = _bytes_stream(data)
    it = iter(stream)

    def _read_byte(_timeout: float = 0):
        try:
            return next(it)
        except StopIteration:
            return None

    with patch.object(kb, "_read_byte", side_effect=_read_byte):
        return kb.get_input()


def test_parse_sgr_mouse_left_press():
    ev = parse_sgr_mouse("0;10;5", "M")
    assert ev == MouseEvent(
        action=MouseAction.PRESS,
        button=MouseButton.LEFT,
        x=9,
        y=4,
        shift=False,
        meta=False,
        ctrl=False,
    )


def test_parse_sgr_mouse_left_release():
    ev = parse_sgr_mouse("0;10;5", "m")
    assert ev is not None
    assert ev.action == MouseAction.RELEASE
    assert ev.button == MouseButton.LEFT


@pytest.mark.parametrize(
    ("params", "button"),
    [
        ("1;10;5", MouseButton.MIDDLE),
        ("2;10;5", MouseButton.RIGHT),
    ],
)
def test_parse_sgr_mouse_buttons(params: str, button: MouseButton):
    ev = parse_sgr_mouse(params, "M")
    assert ev is not None
    assert ev.action == MouseAction.PRESS
    assert ev.button == button


@pytest.mark.parametrize(
    ("params", "expected_delta"),
    [
        ("64;10;5", -1),
        ("65;10;5", 1),
    ],
)
def test_parse_sgr_mouse_scroll(params: str, expected_delta: int):
    ev = parse_sgr_mouse(params, "M")
    assert ev is not None
    assert ev.action == MouseAction.SCROLL
    assert ev.scroll_delta == expected_delta


def test_parse_sgr_mouse_modifiers():
    ev = parse_sgr_mouse("28;10;5", "M")  # 4+8+16 => shift/meta/ctrl
    assert ev is not None
    assert ev.shift is True
    assert ev.meta is True
    assert ev.ctrl is True


def test_parse_sgr_mouse_motion_hover():
    ev = parse_sgr_mouse("35;10;5", "M")  # 32 motion + 3 none
    assert ev is not None
    assert ev.action == MouseAction.MOVE
    assert ev.button == MouseButton.NONE


def test_parse_sgr_mouse_motion_drag_left():
    ev = parse_sgr_mouse("32;10;5", "M")  # 32 motion + button 0
    assert ev is not None
    assert ev.action == MouseAction.MOVE
    assert ev.button == MouseButton.LEFT


@pytest.mark.parametrize(
    ("params", "final"),
    [
        ("0;10", "M"),
        ("x;10;5", "M"),
    ],
)
def test_parse_sgr_mouse_malformed_returns_none(params: str, final: str):
    assert parse_sgr_mouse(params, final) is None


def test_keyboardinput_sgr_mouse_integration_press_and_release():
    press = _get_input_from_bytes(b"\x1b[<0;10;5M")
    assert isinstance(press, MouseEvent)
    assert press.action == MouseAction.PRESS
    assert press.button == MouseButton.LEFT
    assert (press.x, press.y) == (9, 4)

    release = _get_input_from_bytes(b"\x1b[<0;10;5m")
    assert isinstance(release, MouseEvent)
    assert release.action == MouseAction.RELEASE


def test_keyboardinput_mouse_events_filtered_by_get_key():
    kb = KeyboardInput()
    kb._available = True
    ev = MouseEvent(action=MouseAction.PRESS, button=MouseButton.LEFT, x=0, y=0)
    with patch.object(kb, "get_input", return_value=ev):
        assert kb.get_key() is None


def test_keyboardinput_malformed_sgr_sequence_degrades_to_escape():
    # Missing coordinates => parse_sgr_mouse returns None => KeyboardInput returns "escape".
    assert _get_input_from_bytes(b"\x1b[<0;10M") == "escape"
