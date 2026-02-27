"""Golden integration test for the live.py demo.

Exercises: deterministic health check data, status icons, spinner/progress
rendering, palette + icon dispatch, zoom-level render.
"""

from __future__ import annotations

import importlib.util
import io
import sys
from pathlib import Path

import pytest

from painted import Block, CliContext, Zoom
from painted.fidelity import Format, OutputMode
from painted.writer import print_block

_PROJECT = Path(__file__).resolve().parent.parent.parent
_spec = importlib.util.spec_from_file_location(
    "_demo_live", _PROJECT / "demos" / "patterns" / "live.py",
)
_mod = importlib.util.module_from_spec(_spec)
sys.modules[_spec.name] = _mod
_spec.loader.exec_module(_mod)

_fetch = _mod._fetch
_render = _mod._render


def _block_to_text(block: Block) -> str:
    buf = io.StringIO()
    print_block(block, buf, use_ansi=False)
    return buf.getvalue()


def _ctx(zoom: Zoom) -> CliContext:
    return CliContext(zoom=zoom, mode=OutputMode.STATIC, format=Format.PLAIN,
                      is_tty=False, width=80, height=24)


@pytest.mark.parametrize("zoom", list(Zoom), ids=lambda z: z.name)
def test_live_demo(golden, zoom):
    report = _fetch()
    block = _render(_ctx(zoom), report)
    golden.assert_match(_block_to_text(block), "output")
