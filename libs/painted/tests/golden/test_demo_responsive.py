"""Golden integration test for the responsive.py demo.

Exercises: join_responsive width adaptation, breakpoint-driven layout,
zoom-level detail control, pipeline/deploys/alerts panel rendering,
card/bordered composition.
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
    "_demo_responsive",
    _PROJECT / "demos" / "patterns" / "responsive.py",
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
def test_responsive_demo(golden, zoom):
    data = _fetch()
    block = _render(_ctx(zoom), data)
    golden.assert_match(block_to_text(block), "output")
