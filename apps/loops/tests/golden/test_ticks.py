"""Golden coverage for ``ticks_view`` (``store ticks`` listing).

test_grammar_parity.py already byte-goldens ``ticks_view`` (as "ticks"/
"ticks-chain") over a REAL store fixture — this file complements it with a
plain-dict fixture (following the test_log.py/test_why.py pattern: fixture
dict in, ``golden.assert_match`` out, no store) so the listing lens has
coverage independent of the store-fixture builder, plus the ontology honesty
callout the store-fixture path doesn't happen to exercise.
"""
from __future__ import annotations

import pytest
from painted import Zoom

from loops.lenses.ticks import ticks_view

from .fixtures import SAMPLE_TICKS_LISTING, SAMPLE_TICKS_ONTOLOGY_NOTICE
from .helpers import block_to_text


@pytest.mark.parametrize("zoom", list(Zoom), ids=lambda z: z.name)
def test_ticks_demo_tty(golden, zoom):
    block = ticks_view(SAMPLE_TICKS_LISTING, zoom, width=80, piped=False)
    golden.assert_match(block_to_text(block), "output")


@pytest.mark.parametrize("zoom", list(Zoom), ids=lambda z: z.name)
def test_ticks_demo_piped(golden, zoom):
    block = ticks_view(SAMPLE_TICKS_LISTING, zoom, width=None, piped=True)
    golden.assert_match(block_to_text(block), "output")


def test_ticks_ontology_notice(golden):
    """SPEC §9.2/§9.5 honesty callout above the tick rows."""
    block = ticks_view(SAMPLE_TICKS_ONTOLOGY_NOTICE, Zoom.SUMMARY, width=80)
    golden.assert_match(block_to_text(block), "output")
