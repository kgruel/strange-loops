"""Golden integration test for the timing.py demo.

Exercises: FrameTimer instrumentation, per-phase timing, lens composition
(chart_lens for frame bars, flame_lens for phase proportions), zoom-level
render dispatch.
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest

from painted import CliContext, Zoom
from painted.fidelity import OutputMode
from tests.helpers import block_to_text

_PROJECT = Path(__file__).resolve().parent.parent.parent
_spec = importlib.util.spec_from_file_location(
    "_demo_timing",
    _PROJECT / "demos" / "patterns" / "timing.py",
)
_mod = importlib.util.module_from_spec(_spec)
sys.modules[_spec.name] = _mod
_spec.loader.exec_module(_mod)

_render = _mod._render
SAMPLE_TIMING = _mod.SAMPLE_TIMING


def _ctx(zoom: Zoom) -> CliContext:
    return CliContext(
        zoom=zoom, mode=OutputMode.STATIC, use_ansi=False, is_tty=False, width=80, height=24
    )


@pytest.mark.parametrize("zoom", list(Zoom), ids=lambda z: z.name)
def test_timing_demo(golden, zoom):
    block = _render(_ctx(zoom), SAMPLE_TIMING)
    golden.assert_match(block_to_text(block), "output")
