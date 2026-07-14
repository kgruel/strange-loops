"""Golden tests for run/test command lenses (facts and ticks views).

run_facts_view: used by `test` command (without --input) to show streamed facts.
_run_ticks_view: tick-rendering internal, composed into sync_view (the `run`
command's actual lens for .vertex one-shot sync results).
"""
from __future__ import annotations

import pytest
from painted import Zoom

from loops.lenses.run import _run_ticks_view, run_facts_view

from .fixtures import SAMPLE_FACTS, SAMPLE_TICKS
from .helpers import block_to_text


@pytest.mark.parametrize("zoom", list(Zoom), ids=lambda z: z.name)
def test_run_facts_demo(golden, zoom):
    block = run_facts_view(SAMPLE_FACTS, zoom, width=80)
    golden.assert_match(block_to_text(block), "output")


@pytest.mark.parametrize("zoom", list(Zoom), ids=lambda z: z.name)
def test_run_ticks_demo(golden, zoom):
    block = _run_ticks_view(SAMPLE_TICKS, zoom, width=80)
    golden.assert_match(block_to_text(block), "output")
