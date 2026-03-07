"""Golden integration test for the help.py demo.

Exercises: HelpData/HelpFlag/HelpGroup rendering, _render_help at
SUMMARY vs DETAILED zoom, side-by-side layout at FULL, zoom-level
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
    "_demo_help",
    _PROJECT / "demos" / "patterns" / "help.py",
)
_mod = importlib.util.module_from_spec(_spec)
sys.modules[_spec.name] = _mod
_spec.loader.exec_module(_mod)

_render = _mod._render
SAMPLE_HELP = _mod.SAMPLE_HELP


def _ctx(zoom: Zoom) -> CliContext:
    return CliContext(
        zoom=zoom, mode=OutputMode.STATIC, use_ansi=False, is_tty=False, width=80, height=24
    )


@pytest.mark.parametrize("zoom", list(Zoom), ids=lambda z: z.name)
def test_help_demo(golden, zoom):
    block = _render(_ctx(zoom), SAMPLE_HELP)
    golden.assert_match(block_to_text(block), "output")
