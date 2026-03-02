"""Golden integration test for the apps/widgets.py demo.

Exercises: focus ring, spinner tick, progress adjustments, list scrolling,
and text input edits via TestSurface replay capture.
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest

from painted.tui.testing import TestSurface

_PROJECT = Path(__file__).resolve().parent.parent.parent
_spec = importlib.util.spec_from_file_location(
    "_demo_app_widgets",
    _PROJECT / "demos" / "apps" / "widgets.py",
)
_mod = importlib.util.module_from_spec(_spec)
sys.modules[_spec.name] = _mod
_spec.loader.exec_module(_mod)

_FRAME_SEP = "\n--- frame ---\n"


def _replay(keys: list[str]) -> str:
    app = _mod.WidgetsApp()
    frames = TestSurface(app, width=80, height=24, input_queue=keys).run_to_completion()
    return _FRAME_SEP.join(frame.text for frame in frames)


@pytest.mark.parametrize(
    ("scenario", "keys"),
    [
        pytest.param(
            "walkthrough",
            [
                "right",
                "right",
                "left",
                "tab",
                "down",
                "down",
                "down",
                "tab",
                "left",
                "left",
                "a",
                "q",
            ],
            id="walkthrough",
        ),
        pytest.param("spinner_tick", ["a", "a", "a", "a", "a", "q"], id="spinner_tick"),
    ],
)
def test_widgets_app_demo(golden, scenario: str, keys: list[str]) -> None:
    golden.assert_match(_replay(keys), "replay")
