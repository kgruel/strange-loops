"""Golden integration test for the palette_icons.py demo.

Exercises: ambient configuration switching via use_palette/use_icons context
managers, automatic pickup by components (spinner/progress) and lenses
(tree_lens/chart_lens), and zoom-based render dispatch.
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest

from painted import CliContext, Zoom
from painted.fidelity import Format, OutputMode
from tests.helpers import block_to_text

_PROJECT = Path(__file__).resolve().parent.parent.parent
_spec = importlib.util.spec_from_file_location(
    "_demo_palette_icons",
    _PROJECT / "demos" / "patterns" / "palette_icons.py",
)
_mod = importlib.util.module_from_spec(_spec)
sys.modules[_spec.name] = _mod
_spec.loader.exec_module(_mod)

_fetch = _mod._fetch
_render = _mod._render


def _ctx(zoom: Zoom) -> CliContext:
    return CliContext(
        zoom=zoom, mode=OutputMode.STATIC, format=Format.PLAIN, is_tty=False, width=80, height=24
    )


@pytest.mark.parametrize("zoom", list(Zoom), ids=lambda z: z.name)
def test_palette_icons_demo(golden, zoom):
    data = _fetch()
    block = _render(_ctx(zoom), data)
    golden.assert_match(block_to_text(block), "output")
