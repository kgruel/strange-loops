"""Golden integration tests for the testing.py demo.

Exercises the full pipeline: TestSurface replay -> emission capture ->
render at each zoom level -> Block -> plain text output.
"""

from __future__ import annotations

import importlib.util
import io
from pathlib import Path

import pytest

from painted import Block, CliContext, Zoom
from painted.fidelity import Format, OutputMode
from painted.writer import print_block

# ---------------------------------------------------------------------------
# Import demo module without mutating sys.path
# ---------------------------------------------------------------------------

_DEMO_PATH = Path(__file__).resolve().parent.parent / "demos" / "patterns" / "testing.py"

_spec = importlib.util.spec_from_file_location("_demo_testing", _DEMO_PATH)
_mod = importlib.util.module_from_spec(_spec)
import sys as _sys
_sys.modules[_spec.name] = _mod
_spec.loader.exec_module(_mod)

_fetch = _mod._fetch
_render = _mod._render


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _block_to_text(block: Block) -> str:
    buf = io.StringIO()
    print_block(block, buf, use_ansi=False)
    return buf.getvalue()


def _make_ctx(zoom: Zoom) -> CliContext:
    return CliContext(
        zoom=zoom,
        mode=OutputMode.STATIC,
        format=Format.PLAIN,
        is_tty=False,
        width=80,
        height=24,
    )


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("zoom", list(Zoom), ids=lambda z: z.name)
def test_testing_demo(golden, zoom):
    results = _fetch()
    ctx = _make_ctx(zoom)
    block = _render(ctx, results)
    text = _block_to_text(block)
    golden.assert_match(text, "output")
