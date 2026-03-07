"""Golden integration test for the layers.py demo.

Exercises: Layer stack routing (top handles keys), Stay/Push/Pop/Quit actions,
bottom-to-top rendering, base-never-pops invariant, zoom-level render dispatch.
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
    "_demo_layers",
    _PROJECT / "demos" / "patterns" / "layers.py",
)
_mod = importlib.util.module_from_spec(_spec)
sys.modules[_spec.name] = _mod
_spec.loader.exec_module(_mod)

_fetch = _mod._fetch
_render = _mod._render


@pytest.mark.parametrize("zoom", list(Zoom), ids=lambda z: z.name)
def test_layers_demo(golden, zoom):
    traces = _fetch()
    block = _render(static_ctx(zoom), traces)
    golden.assert_match(block_to_text(block), "output")
