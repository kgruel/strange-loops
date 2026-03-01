"""Golden tests for the compile command."""
from __future__ import annotations

import pytest
from painted import Zoom

from loops.lenses.compile import compile_view

from .fixtures import SAMPLE_COMPILE_LOOP, SAMPLE_COMPILE_VERTEX
from .helpers import block_to_text


@pytest.mark.parametrize("zoom", list(Zoom), ids=lambda z: z.name)
def test_compile_loop_demo(golden, zoom):
    block = compile_view(SAMPLE_COMPILE_LOOP, zoom, width=80)
    golden.assert_match(block_to_text(block), "output")


@pytest.mark.parametrize("zoom", list(Zoom), ids=lambda z: z.name)
def test_compile_vertex_demo(golden, zoom):
    block = compile_view(SAMPLE_COMPILE_VERTEX, zoom, width=80)
    golden.assert_match(block_to_text(block), "output")
