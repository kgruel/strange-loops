"""Golden integration test for the mouse.py app demo.

Exercises: keyboard input, mouse clicks, mouse drag, scroll (color change).
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

from painted.mouse import MouseAction, MouseButton, MouseEvent
from painted.tui.testing import TestSurface

_PROJECT = Path(__file__).resolve().parent.parent.parent
_spec = importlib.util.spec_from_file_location(
    "_demo_mouse",
    _PROJECT / "demos" / "apps" / "mouse.py",
)
assert _spec is not None
assert _spec.loader is not None
_mod = importlib.util.module_from_spec(_spec)
sys.modules[_spec.name] = _mod
_spec.loader.exec_module(_mod)

MouseApp = _mod.MouseApp


def _frames_text(*, input_queue: list[str | MouseEvent]) -> str:
    app = MouseApp()
    harness = TestSurface(app, width=50, height=10, input_queue=input_queue)
    frames = harness.run_to_completion()
    return "\n--- frame ---\n".join(frame.text for frame in frames)


def test_mouse_demo(golden) -> None:
    move = MouseEvent(action=MouseAction.MOVE, button=MouseButton.NONE, x=5, y=4)
    scroll = MouseEvent(
        action=MouseAction.SCROLL,
        button=MouseButton.SCROLL_DOWN,
        x=5,
        y=4,
    )
    click_press = MouseEvent(action=MouseAction.PRESS, button=MouseButton.LEFT, x=5, y=4)
    click_release = MouseEvent(action=MouseAction.RELEASE, button=MouseButton.LEFT, x=5, y=4)
    move_away = MouseEvent(action=MouseAction.MOVE, button=MouseButton.NONE, x=0, y=1)

    drag_press = MouseEvent(action=MouseAction.PRESS, button=MouseButton.LEFT, x=2, y=6)
    drag_moves = [
        MouseEvent(action=MouseAction.MOVE, button=MouseButton.LEFT, x=4, y=6),
        MouseEvent(action=MouseAction.MOVE, button=MouseButton.LEFT, x=6, y=6),
        MouseEvent(action=MouseAction.MOVE, button=MouseButton.LEFT, x=8, y=6),
    ]
    drag_release = MouseEvent(action=MouseAction.RELEASE, button=MouseButton.LEFT, x=8, y=6)

    erase = MouseEvent(action=MouseAction.PRESS, button=MouseButton.RIGHT, x=5, y=4)

    text = _frames_text(
        input_queue=[
            move,
            scroll,
            click_press,
            click_release,
            move_away,
            drag_press,
            *drag_moves,
            drag_release,
            erase,
            "c",
            "2",
            "q",
        ]
    )
    golden.assert_match(text, "frames")
