"""Tier-allocated disclosure invariants (G4d).

decision:design/tier-allocated-disclosure: the TTY default-zoom (SUMMARY)
ORIENTATION view breathes by tier — high rows get bodies, mid get headlines,
tail get bare lines. Every other path stays uniform and tier-blind. These
tests pin the exemptions so the orientation breathing never leaks onto a
retrieval path.
"""

from atoms import FoldItem, FoldSection, FoldState
from painted import Zoom

from loops.lenses.fold import fold_view
from loops.surface import project

from .helpers import block_text as _text


def _spread_state():
    """A by-fold section whose salience spreads across all three tiers.

    n = [1]*8 + [2, 9]: the n=9 item is high, the n=2 mid, the rest tail —
    a genuine tier gradient (so tier_allocate engages). Bodies differ from
    keys so a suppressed body is detectable.
    """
    items = tuple(
        FoldItem(payload={"topic": f"k{i}", "message": f"body-{i}"},
                 ts=None, observer="o", id=None, n=n)
        for i, n in enumerate([1, 1, 1, 1, 1, 1, 1, 1, 2, 9])
    )
    return FoldState(
        vertex="v",
        sections=(FoldSection(kind="decision", items=items,
                              fold_type="by", key_field="topic"),),
    )


def test_summary_tty_allocates_by_tier():
    """The orientation view: high body shown, tail body suppressed."""
    surface = project(_spread_state())
    t = _text(fold_view(surface, Zoom.SUMMARY, 100, piped=False))
    assert "body-9" in t          # high tier keeps its body
    assert "body-0" not in t      # tail tier goes bare (no body)


def test_exact_key_address_always_full_body():
    """granularity=='whole' (exact key address) forces the body REGARDLESS of
    tier — the retrieval-path flip-invariant. k0 is tail, but addressed exactly
    it still shows its body at SUMMARY TTY."""
    surface = project(_spread_state(), queried_key="k0")
    t = _text(fold_view(surface, Zoom.SUMMARY, 100, piped=False))
    assert "body-0" in t


def test_full_forces_uniform_bodies():
    """--full (whole granularity on every row) is tier-blind — all bodies."""
    surface = project(_spread_state(), full=True)
    t = _text(fold_view(surface, Zoom.SUMMARY, 100, piped=False))
    assert "body-0" in t and "body-9" in t


def test_detailed_and_full_zoom_are_tier_blind():
    """-v / -vv (DETAILED / FULL zoom) disclose uniformly — no allocation."""
    surface = project(_spread_state())
    for zoom in (Zoom.DETAILED, Zoom.FULL):
        t = _text(fold_view(surface, zoom, 100, piped=False))
        assert "body-0" in t and "body-9" in t


def test_piped_register_never_allocates():
    """The piped ledger carries every body on both hot and cold rows — the
    agent channel stays information-faithful, tier is a WORD column, not a
    disclosure gate."""
    surface = project(_spread_state())
    t = _text(fold_view(surface, Zoom.SUMMARY, None, piped=True))
    assert "body-0" in t and "body-9" in t


def test_flat_population_shows_all_bodies():
    """No tier gradient (all one tier) → nothing to allocate along → uniform
    bodies, exactly as before G4d. A single-item section is the degenerate
    case that would otherwise hide its only body."""
    state = FoldState(
        vertex="v",
        sections=(FoldSection(
            kind="decision",
            items=(FoldItem(payload={"topic": "solo", "message": "only-body"},
                            ts=None, observer="o", id=None, n=1),),
            fold_type="by", key_field="topic"),),
    )
    t = _text(fold_view(project(state), Zoom.SUMMARY, 100, piped=False))
    assert "only-body" in t
