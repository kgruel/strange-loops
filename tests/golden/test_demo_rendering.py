"""Golden integration test for the rendering.py demo.

Unlike run_cli demos, rendering.py has four standalone demo functions
that write directly to stdout via print_block/show. We capture stdout
and golden-test each mode.

Exercises: tree_lens, chart_lens, show() auto-dispatch, custom lens
functions, palette switching, Block composition.
"""

from __future__ import annotations

import importlib.util
import sys
from contextlib import redirect_stdout
from io import StringIO
from pathlib import Path

import pytest

_PROJECT = Path(__file__).resolve().parent.parent.parent
_spec = importlib.util.spec_from_file_location(
    "_demo_rendering",
    _PROJECT / "demos" / "patterns" / "rendering.py",
)
_mod = importlib.util.module_from_spec(_spec)
sys.modules[_spec.name] = _mod
_spec.loader.exec_module(_mod)

_DEMOS = {
    "explicit": _mod.demo_explicit,
    "custom": _mod.demo_custom,
    "palette": _mod.demo_palette,
    "help": _mod.demo_help,
}


def _capture(fn) -> str:
    buf = StringIO()
    with redirect_stdout(buf):
        fn()
    return buf.getvalue()


@pytest.mark.parametrize("mode", list(_DEMOS.keys()))
def test_rendering_demo(golden, mode):
    text = _capture(_DEMOS[mode])
    golden.assert_match(text, "output")
