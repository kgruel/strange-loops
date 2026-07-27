"""Live-edge staleness footer — the fold lens half of the sensor
(design:rendering/live-edge-staleness-on-read-path)."""
from dataclasses import replace

from atoms import FoldItem, FoldSection, FoldState
from painted import Zoom, paint

from loops.lenses.fold import fold_view
from loops.surface import STALE_AFTER_SECS, project

_NOW = 1736942400.0  # pinned via the _grammar.time.time seam


def _pin(monkeypatch):
    monkeypatch.setattr("loops.lenses._grammar.time.time", lambda: _NOW)


def _state(edge_facts=0, edge_since=None):
    item = FoldItem(
        payload={"topic": "a", "message": "m"},
        ts=_NOW - 120, observer="o", id=None, n=1, refs=(),
    )
    state = FoldState(
        sections=(FoldSection(
            kind="decision", items=(item,), fold_type="by",
            key_field="topic", preview_fields=("message",),
        ),),
        vertex="project",
    )
    return replace(state, edge_facts=edge_facts, edge_since=edge_since)


def _text(block):
    import io
    from contextlib import redirect_stdout

    out = paint(block)
    if isinstance(out, str):
        return out
    buf = io.StringIO()
    with redirect_stdout(buf):
        paint(block)
    return buf.getvalue()


class TestEdgeFooter:
    def test_stale_edge_fires_in_footer_and_minimal(self, monkeypatch):
        _pin(monkeypatch)
        surface = project(_state(edge_facts=116, edge_since=_NOW - 10 * 86400))
        body = _text(fold_view(surface, Zoom.SUMMARY, None))
        assert "live edge: 116 facts unsealed, oldest 10d" in body
        assert "sl seal project" in body
        minimal = _text(fold_view(surface, Zoom.MINIMAL, None))
        assert "edge stale: 116 unsealed, 10d" in minimal

    def test_young_edge_stays_quiet(self, monkeypatch):
        _pin(monkeypatch)
        surface = project(_state(edge_facts=5, edge_since=_NOW - 60))
        assert "live edge" not in _text(fold_view(surface, Zoom.SUMMARY, None))

    def test_dormant_store_stays_quiet(self, monkeypatch):
        """Old tick, empty edge: dormancy is not wiring death."""
        _pin(monkeypatch)
        surface = project(_state(edge_facts=0, edge_since=None))
        assert "live edge" not in _text(fold_view(surface, Zoom.SUMMARY, None))

    def test_boundary_exactly_at_dial_is_quiet(self, monkeypatch):
        """is_stale is strict-> — exactly STALE_AFTER_SECS old is not stale.
        The lens inherits the shared dial's boundary, no second judgment."""
        _pin(monkeypatch)
        surface = project(_state(edge_facts=3, edge_since=_NOW - STALE_AFTER_SECS))
        assert "live edge" not in _text(fold_view(surface, Zoom.SUMMARY, None))
