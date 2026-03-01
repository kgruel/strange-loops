"""Golden tests for the run command (facts and ticks views)."""
from __future__ import annotations

import pytest
from painted import Zoom

from loops.lenses.run import run_facts_view, run_ticks_view

from .fixtures import SAMPLE_FACTS, SAMPLE_TICKS
from .helpers import block_to_text


@pytest.mark.parametrize("zoom", list(Zoom), ids=lambda z: z.name)
def test_run_facts_demo(golden, zoom):
    block = run_facts_view(SAMPLE_FACTS, zoom, width=80)
    golden.assert_match(block_to_text(block), "output")


@pytest.mark.parametrize("zoom", list(Zoom), ids=lambda z: z.name)
def test_run_ticks_demo(golden, zoom):
    block = run_ticks_view(SAMPLE_TICKS, zoom, width=80)
    golden.assert_match(block_to_text(block), "output")
