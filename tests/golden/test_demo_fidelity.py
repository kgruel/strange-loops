"""Golden integration test for the fidelity.py demo.

Uses SAMPLE_DISK directly — _fetch() calls shutil.disk_usage and
datetime.now(), making it non-deterministic.

Exercises: disk usage rendering, usage bars, directory trees,
bordered layouts, zoom-level render.
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
    "_demo_fidelity",
    _PROJECT / "demos" / "patterns" / "fidelity.py",
)
_mod = importlib.util.module_from_spec(_spec)
sys.modules[_spec.name] = _mod
_spec.loader.exec_module(_mod)

_render = _mod._render
SAMPLE_DISK = _mod.SAMPLE_DISK


def _block_to_text(block: Block) -> str:
    buf = io.StringIO()
    print_block(block, buf, use_ansi=False)
    return buf.getvalue()


def _ctx(zoom: Zoom) -> CliContext:
    return CliContext(
        zoom=zoom, mode=OutputMode.STATIC, format=Format.PLAIN, is_tty=False, width=80, height=24
    )


@pytest.mark.parametrize("zoom", list(Zoom), ids=lambda z: z.name)
def test_fidelity_demo(golden, zoom):
    block = _render(_ctx(zoom), SAMPLE_DISK)
    golden.assert_match(_block_to_text(block), "output")
