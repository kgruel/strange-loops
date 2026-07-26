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
from atoms import FoldItem, FoldSection, FoldState
from painted import Zoom

from loops.lenses.fold import fold_view
from loops.surface import hide_inactive, project

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


def _lifecycle_hidden_surface():
    """A lifecycle-declaring kind with one active + one inactive entity, run
    through project → hide_inactive so the Window carries hidden=1 — the exact
    input the built-in lens footer discloses (S5). Deterministic: fixed ISO ts."""
    state = FoldState(
        sections=(
            FoldSection(
                kind="task",
                fold_type="by",
                key_field="name",
                lifecycle=("status", ("open", "in-progress")),
                items=(
                    FoldItem(
                        payload={"name": "alpha", "status": "open",
                                 "message": "active work"},
                        ts="2025-01-15T10:00:00+00:00", n=1,
                    ),
                    FoldItem(
                        payload={"name": "beta", "status": "done",
                                 "message": "shipped"},
                        ts="2025-01-15T11:00:00+00:00", n=1,
                    ),
                ),
            ),
        ),
        vertex="session",
    )
    return hide_inactive(project(state))


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


@pytest.mark.parametrize("zoom", list(Zoom), ids=lambda z: z.name)
def test_lifecycle_hidden_footer(golden, zoom):
    """S5: the '(N inactive hidden — --all to show)' footer over a post-hide
    Surface (active `alpha` shown, inactive `beta` projected out). The wave's
    ONE licensed fold-golden move — every captured line hand-verified."""
    block = fold_view(_lifecycle_hidden_surface(), zoom, width=80)
    golden.assert_match(block_to_text(block), "output")
