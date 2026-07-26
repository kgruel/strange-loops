"""Tests for sync lens rendering — all zoom levels."""

import time

import pytest
from painted import Zoom

from loops.lenses.sync import _format_skip, sync_view

from .helpers import block_text as _text


_NOW = 1_700_000_000.0


@pytest.fixture
def _pin_clock(monkeypatch):
    """Pin the clock ``recency`` reads. Unpinned, the ages below land exactly ON
    recency's band boundaries, where the microseconds between the test's
    ``time.time()`` and recency's own read decide whether 7200s says "2h" or
    "1h" — flaky by construction, not a property worth asserting."""
    monkeypatch.setattr("loops.lenses._grammar.time.time", lambda: _NOW)


def test_format_skip_speaks_the_shared_time_vocabulary(_pin_clock):
    """Ages come from ``_grammar.recency``, cadences from ``duration_secs`` —
    the lens holds no time ladder of its own."""
    def skip(age, cadence=None):
        d = {"kind": "m", "last_run_ts": _NOW - age}
        if cadence is not None:
            d["cadence_interval"] = cadence
        return _format_skip(d)

    assert skip(30) == "m: fresh (last run now)"
    assert skip(300) == "m: fresh (last run 5m)"
    assert skip(7200) == "m: fresh (last run 2h)"
    assert skip(172800) == "m: fresh (last run 2d)"
    # The calendar cutover the deleted lens-local ladder lacked (it said "197d ago").
    assert skip(197 * 86400) == "m: fresh (last run May 1)"

    assert skip(300, cadence=30) == "m: fresh (last run 5m, cadence 30s)"
    assert skip(300, cadence=300) == "m: fresh (last run 5m, cadence 5m)"
    assert skip(300, cadence=7200) == "m: fresh (last run 5m, cadence 2h)"
    assert skip(300, cadence=172800) == "m: fresh (last run 5m, cadence 2d)"

def test_format_skip_full():
    r = _format_skip({"kind": "metric", "last_run_ts": time.time() - 60, "cadence_interval": 300})
    assert "metric" in r and "fresh" in r

def test_format_skip_no_interval():
    assert "metric" in _format_skip({"kind": "metric", "last_run_ts": time.time() - 60})

def test_format_skip_minimal():
    assert _format_skip({"kind": "metric"}) == "metric"

def test_sync_minimal_empty():
    assert "nothing to sync" in _text(sync_view({}, Zoom.MINIMAL, 80))

def test_sync_minimal_with_facts():
    t = _text(sync_view({"ran": ["metric"], "fact_counts": {"metric": 5}}, Zoom.MINIMAL, 80))
    assert "5 facts" in t and "1 ran" in t

def test_sync_with_errors():
    t = _text(sync_view({"ran": ["metric"], "fact_counts": {"metric": 1}, "errors": [{"payload": {"error": "timeout"}}]}, Zoom.MINIMAL, 80))
    assert "1 errors" in t

def test_sync_summary_instance():
    data = {"ran": ["metric", "status"], "fact_counts": {"metric": 3, "status": 1},
            "skipped": [{"kind": "health", "last_run_ts": time.time() - 60}]}
    assert "Ran:" in _text(sync_view(data, Zoom.SUMMARY, 80))

def test_sync_with_ticks():
    data = {"ran": ["metric"], "fact_counts": {"metric": 3},
            "ticks": [{"name": "session", "payload": {}, "ts": 1e9}]}
    assert "Ran:" in _text(sync_view(data, Zoom.SUMMARY, 80))

def test_sync_aggregation_children():
    data = {"children": [{"name": "proj", "ran": ["metric"], "skipped": [],
                           "fact_counts": {"metric": 5}}], "fact_counts": {"metric": 5}}
    t = _text(sync_view(data, Zoom.SUMMARY, 80))
    assert "proj:" in t or "5 facts" in t
