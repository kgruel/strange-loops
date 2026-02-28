"""Golden integration test for the disk.py app demo.

Exercises: Surface app rendering, selection state, keyboard navigation,
progress_bar usage, Block composition pipeline.
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

from painted.tui import TestSurface

_PROJECT = Path(__file__).resolve().parent.parent.parent
_spec = importlib.util.spec_from_file_location(
    "_demo_disk_app",
    _PROJECT / "demos" / "apps" / "disk.py",
)
_mod = importlib.util.module_from_spec(_spec)
sys.modules[_spec.name] = _mod
_spec.loader.exec_module(_mod)

DiskApp = _mod.DiskApp


def _frames_text(frames) -> str:
    return "\n--- frame ---\n".join(frame.text for frame in frames)


def test_disk_app_demo(golden):
    app = DiskApp()
    harness = TestSurface(
        app,
        width=80,
        height=24,
        input_queue=["down", "down", "up", "q"],
    )
    frames = harness.run_to_completion()

    # Keep the interaction frames; omit the quit render to reduce noise.
    golden.assert_match(_frames_text(frames[:4]), "output")
