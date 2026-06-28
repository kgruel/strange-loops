"""Golden coverage for fold-lens paths the basic goldens never exercised.

These lock TODAY's render of the namespace-grouped / refs-edge / walked /
source-facts / unfolded branches BEFORE the S2 Surface-interposition rewrite,
so the rewrite's byte-identity is actually gated (the empty-diff gate is blind
to any branch with no golden — see the S1 adversarial verify's golden-blindness
finding). The harness bootstraps a missing golden on first run, so running these
once on the pre-rewrite lens captures the baseline; re-running post-rewrite is
the gate.
"""
from __future__ import annotations

import pytest
from painted import Zoom

from loops.lenses.fold import fold_view

from .fixtures import (
    SAMPLE_FOLD_FACTS,
    SAMPLE_FOLD_GROUPED,
    SAMPLE_FOLD_REFS,
    SAMPLE_FOLD_UNFOLDED,
    SAMPLE_FOLD_WALKED,
)
from .helpers import block_to_text

REFS = frozenset({"refs"})
FACTS = frozenset({"facts"})


@pytest.mark.parametrize("zoom", list(Zoom), ids=lambda z: z.name)
def test_grouped(golden, zoom):
    """Multi-namespace grouping + >5 windowing + tied-group fold-order tiebreak."""
    block = fold_view(SAMPLE_FOLD_GROUPED, zoom, width=80)
    golden.assert_match(block_to_text(block), "output")


def test_grouped_piped(golden):
    """width=None piped render — the '## KIND' header path."""
    block = fold_view(SAMPLE_FOLD_GROUPED, Zoom.SUMMARY, width=None)
    golden.assert_match(block_to_text(block), "output")


@pytest.mark.parametrize("zoom", list(Zoom), ids=lambda z: z.name)
def test_refs(golden, zoom):
    """Inbound/outbound edge expansion; design/c has two same-section sources."""
    block = fold_view(SAMPLE_FOLD_REFS, zoom, width=80, visible=REFS)
    golden.assert_match(block_to_text(block), "output")


@pytest.mark.parametrize("zoom", list(Zoom), ids=lambda z: z.name)
def test_walked(golden, zoom):
    """--refs N walked rows: via-anchor grouping + depth>1 marker."""
    block = fold_view(SAMPLE_FOLD_WALKED, zoom, width=80, visible=REFS)
    golden.assert_match(block_to_text(block), "output")


@pytest.mark.parametrize("zoom", list(Zoom), ids=lambda z: z.name)
def test_facts(golden, zoom):
    """Source-facts drill (reverse-chrono, limit-3) + 'No history:' skip footer."""
    block = fold_view(SAMPLE_FOLD_FACTS, zoom, width=80, visible=FACTS)
    golden.assert_match(block_to_text(block), "output")


@pytest.mark.parametrize("zoom", list(Zoom), ids=lambda z: z.name)
def test_unfolded(golden, zoom):
    """MINIMAL loose-render + 'Unfolded:' footer for undeclared kinds."""
    block = fold_view(SAMPLE_FOLD_UNFOLDED, zoom, width=80)
    golden.assert_match(block_to_text(block), "output")
