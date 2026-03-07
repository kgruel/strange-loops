"""Golden integration test for the fidelity.py demo.

Uses SAMPLE_DISK directly — _fetch() calls shutil.disk_usage and
datetime.now(), making it non-deterministic.

Exercises: disk usage rendering, usage bars, directory trees,
bordered layouts, zoom-level render.
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
    "_demo_fidelity",
    _PROJECT / "demos" / "patterns" / "fidelity.py",
)
_mod = importlib.util.module_from_spec(_spec)
sys.modules[_spec.name] = _mod
_spec.loader.exec_module(_mod)

_render = _mod._render
SAMPLE_DISK = _mod.SAMPLE_DISK


@pytest.mark.parametrize("zoom", list(Zoom), ids=lambda z: z.name)
def test_fidelity_demo(golden, zoom):
    block = _render(static_ctx(zoom), SAMPLE_DISK)
    golden.assert_match(block_to_text(block), "output")
