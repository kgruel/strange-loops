"""Golden integration test for the apps/animation.py demo.

Exercises: update() cadence, mark_dirty() for timer-driven rendering,
SpinnerState ticking, ProgressState advancement, pause/resume/reset controls.
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

from painted.tui import TestSurface

_PROJECT = Path(__file__).resolve().parent.parent.parent
_spec = importlib.util.spec_from_file_location(
    "_app_animation",
    _PROJECT / "demos" / "apps" / "animation.py",
)
_mod = importlib.util.module_from_spec(_spec)
sys.modules[_spec.name] = _mod
_spec.loader.exec_module(_mod)

AnimationApp = _mod.AnimationApp


def _frames_text(frames) -> str:
    return "\n--- frame ---\n".join(f.text for f in frames) + "\n"


def _run(keys: list[str]) -> str:
    app = AnimationApp()
    harness = TestSurface(app, width=60, height=12, input_queue=keys)
    return _frames_text(harness.run_to_completion())


def test_animation_initial(golden) -> None:
    golden.assert_match(_run([]), "output")


def test_animation_running(golden) -> None:
    golden.assert_match(_run(["x"] * 6), "output")


def test_animation_pause_resume(golden) -> None:
    keys = ["x"] * 3 + ["space"] + ["x"] * 3 + ["space"] + ["x"] * 2
    golden.assert_match(_run(keys), "output")


def test_animation_reset(golden) -> None:
    keys = ["x"] * 4 + ["r"] + ["x"] * 2
    golden.assert_match(_run(keys), "output")
