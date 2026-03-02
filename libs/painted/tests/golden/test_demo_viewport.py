"""Golden integration test for the viewport.py app demo.

Exercises: list_view scrolling, Viewport offset/window changes, boundary behavior.
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

from painted.tui import TestSurface

_PROJECT = Path(__file__).resolve().parent.parent.parent
_spec = importlib.util.spec_from_file_location(
    "_demo_viewport",
    _PROJECT / "demos" / "apps" / "viewport.py",
)
_mod = importlib.util.module_from_spec(_spec)
sys.modules[_spec.name] = _mod
_spec.loader.exec_module(_mod)

ViewportInspectorApp = _mod.ViewportInspectorApp


def _frames_to_text(frames) -> str:
    return "\n--- frame ---\n".join(frame.text for frame in frames)


def test_viewport_demo(golden):
    # Small-ish terminal so the viewport window is visibly smaller than content.
    app = ViewportInspectorApp()
    keys = ["up", *["down"] * 15, *["up"] * 5, *["down"] * 20, "q"]

    harness = TestSurface(app, width=80, height=14, input_queue=keys)
    frames = harness.run_to_completion()

    golden.assert_match(_frames_to_text(frames), "frames")
