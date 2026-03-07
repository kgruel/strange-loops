"""Golden integration test for the profiler.py demo.

Uses SAMPLE_PROFILE directly — _fetch() runs cProfile and TestSurface,
producing non-deterministic timing data.

Exercises: frame cost bars (chart_lens), emission timeline (tree_lens),
flame graph (flame_lens), palette integration, zoom-level render.
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest

from painted import Zoom
from tests.helpers import block_to_text, static_ctx

_PROJECT = Path(__file__).resolve().parent.parent.parent
_spec = importlib.util.spec_from_file_location(
    "_demo_profiler",
    _PROJECT / "demos" / "patterns" / "profiler.py",
)
_mod = importlib.util.module_from_spec(_spec)
sys.modules[_spec.name] = _mod
_spec.loader.exec_module(_mod)

_render = _mod._render
SAMPLE_PROFILE = _mod.SAMPLE_PROFILE


@pytest.mark.parametrize("zoom", list(Zoom), ids=lambda z: z.name)
def test_profiler_demo(golden, zoom):
    block = _render(static_ctx(zoom), SAMPLE_PROFILE)
    golden.assert_match(block_to_text(block), "output")
