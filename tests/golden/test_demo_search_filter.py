"""Golden integration test for the apps/search_filter.py demo.

Exercises: Search state (type, backspace, clear), filter_fuzzy filtering,
selection navigation (up/down wrapping), enter to pick, tab to cycle
filter modes, TestSurface replay with multi-frame golden snapshots.
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest

from painted.tui import TestSurface

_PROJECT = Path(__file__).resolve().parent.parent.parent
_spec = importlib.util.spec_from_file_location(
    "_app_search_filter",
    _PROJECT / "demos" / "apps" / "search_filter.py",
)
_mod = importlib.util.module_from_spec(_spec)
sys.modules[_spec.name] = _mod
_spec.loader.exec_module(_mod)

SearchFilterApp = _mod.SearchFilterApp

_FRAME_SEP = "\n--- frame ---\n"


def _run(keys: list[str]) -> str:
    app = SearchFilterApp()
    harness = TestSurface(app, width=60, height=20, input_queue=keys)
    frames = harness.run_to_completion()
    return _FRAME_SEP.join(f.text for f in frames)


@pytest.mark.parametrize(
    ("scenario", "keys"),
    [
        ("initial", []),
        ("type_filter", list("dep")),
        ("navigate", list("de") + ["down", "down", "up"]),
        ("pick", list("run") + ["down", "enter"]),
        ("backspace", list("deploy") + ["backspace", "backspace"]),
        ("clear", list("xyz") + ["escape"]),
        ("cycle_filter", ["tab", "tab"]),
    ],
)
def test_search_filter_app(golden, scenario: str, keys: list[str]) -> None:
    golden.assert_match(_run(keys), "output")
