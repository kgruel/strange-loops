"""Golden integration test for the minimal.py app demo.

Exercises: TestSurface replay, movement (all arrow keys), color cycling
(all 6 colors), quit. Each scenario replays a key sequence and captures
every frame — the golden is the full replay record.
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest

from painted.tui.testing import TestSurface

_PROJECT = Path(__file__).resolve().parent.parent.parent
_spec = importlib.util.spec_from_file_location(
    "_demo_minimal",
    _PROJECT / "demos" / "apps" / "minimal.py",
)
_mod = importlib.util.module_from_spec(_spec)
sys.modules[_spec.name] = _mod
_spec.loader.exec_module(_mod)

MinimalApp = _mod.MinimalApp

WIDTH = 80
HEIGHT = 24

_FRAME_SEP = "\n--- frame ---\n"

# Each scenario: (id, key_sequence)
_SCENARIOS: list[tuple[str, list[str]]] = [
    ("initial", []),
    (
        "movement",
        # Right x3, down x3, left x2, up x2 — exercises all four arrows
        ["right"] * 3 + ["down"] * 3 + ["left"] * 2 + ["up"] * 2,
    ),
    (
        "all_colors",
        # 5 presses: red(initial) → green → yellow → blue → magenta → cyan
        ["c"] * 5,
    ),
    (
        "quit",
        # Move, change color, quit — app should stop processing further keys
        ["right", "down", "c", "q", "left"],
    ),
]


@pytest.mark.parametrize("keys", [s[1] for s in _SCENARIOS], ids=[s[0] for s in _SCENARIOS])
def test_minimal_app(golden, keys):
    app = MinimalApp()
    harness = TestSurface(app, width=WIDTH, height=HEIGHT, input_queue=keys)
    frames = harness.run_to_completion()
    replay = _FRAME_SEP.join(f.text for f in frames)
    golden.assert_match(replay, "output")
