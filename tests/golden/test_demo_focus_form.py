"""Golden integration test for the focus_form.py app demo.

Exercises: Focus ring navigation (Tab / Shift-Tab), capture/release mode,
TextInputState updates, TestSurface replay, multi-frame golden snapshots.
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest

from painted.tui import TestSurface

_PROJECT = Path(__file__).resolve().parent.parent.parent
_spec = importlib.util.spec_from_file_location(
    "_app_focus_form",
    _PROJECT / "demos" / "apps" / "focus_form.py",
)
_mod = importlib.util.module_from_spec(_spec)
sys.modules[_spec.name] = _mod
_spec.loader.exec_module(_mod)

FocusFormApp = _mod.FocusFormApp


def _frames_text(frames) -> str:
    return "\n--- frame ---\n".join(frame.text for frame in frames)


@pytest.mark.parametrize(
    ("scenario", "keys"),
    [
        ("initial", []),
        ("typing", list("db") + ["tab"] + list("5432")),
        ("navigation", ["tab", "tab", "tab", "shift_tab", "shift_tab", "shift_tab"]),
        ("submit", list("db") + ["tab"] + list("5432") + ["tab"] + list("sam") + ["tab", "enter"]),
    ],
)
def test_focus_form_app(golden, scenario: str, keys: list[str]) -> None:
    app = FocusFormApp()
    harness = TestSurface(app, width=60, height=18, input_queue=keys)
    frames = harness.run_to_completion()
    golden.assert_match(_frames_text(frames), scenario)
