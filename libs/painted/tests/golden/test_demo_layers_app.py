"""Golden integration test for the apps/layers.py demo.

Exercises: Surface + TestSurface replay, layer push/pop/quit lifecycle,
and bottom-to-top rendering across multiple frames.
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest

from painted.tui.testing import TestSurface

_PROJECT = Path(__file__).resolve().parent.parent.parent
_spec = importlib.util.spec_from_file_location(
    "_demo_layers_app",
    _PROJECT / "demos" / "apps" / "layers.py",
)
_mod = importlib.util.module_from_spec(_spec)
sys.modules[_spec.name] = _mod
_spec.loader.exec_module(_mod)

LayersApp = _mod.LayersApp

_FRAME_SEP = "\n--- frame ---\n"


def _capture_frames(keys: list[str]) -> str:
    app = LayersApp()
    harness = TestSurface(app, width=80, height=24, input_queue=keys)
    frames = harness.run_to_completion()
    return _FRAME_SEP.join(frame.text for frame in frames)


@pytest.mark.parametrize(
    "keys",
    [
        pytest.param([], id="initial"),
        pytest.param(["s"], id="push_layers"),
        pytest.param(["s", "up", "enter", "h", "x"], id="pop_layers"),
        pytest.param(["q"], id="quit"),
    ],
)
def test_layers_app_demo(golden, keys: list[str]) -> None:
    golden.assert_match(_capture_frames(keys), "frames")
