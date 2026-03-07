"""Golden integration test for the focus.py demo.

Exercises: Focus ring navigation, capture/release mode, Cursor wrapping,
Search + filter_fuzzy, TestSurface replay, emission capture, zoom-level
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
    "_demo_focus",
    _PROJECT / "demos" / "patterns" / "focus.py",
)
_mod = importlib.util.module_from_spec(_spec)
sys.modules[_spec.name] = _mod
_spec.loader.exec_module(_mod)

_fetch = _mod._fetch
_render = _mod._render


def _ctx(zoom: Zoom) -> CliContext:
    return CliContext(
        zoom=zoom, mode=OutputMode.STATIC, use_ansi=False, is_tty=False, width=80, height=24
    )


@pytest.mark.parametrize("zoom", list(Zoom), ids=lambda z: z.name)
def test_focus_demo(golden, zoom):
    results = _fetch()
    block = _render(_ctx(zoom), results)
    golden.assert_match(block_to_text(block), "output")
