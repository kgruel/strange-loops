"""Tests for sync lens rendering — all zoom levels."""

import time

from painted import Zoom

from .helpers import block_text as _text


def test_format_ago():
    from loops.lenses.sync import _format_ago
    assert _format_ago(time.time() - 30).endswith("s ago")
    assert _format_ago(time.time() - 300).endswith("m ago")
    assert _format_ago(time.time() - 7200).endswith("h ago")
    assert _format_ago(time.time() - 172800).endswith("d ago")


def test_format_interval():
    from loops.lenses.sync import _format_interval
    assert _format_interval(30) == "30s"
    assert _format_interval(300) == "5m"
    assert _format_interval(7200) == "2h"
    assert _format_interval(172800) == "2d"


def test_format_skip_full():
    from loops.lenses.sync import _format_skip
    result = _format_skip({"kind": "metric", "last_run_ts": time.time() - 60, "cadence_interval": 300})
    assert "metric" in result
    assert "fresh" in result

def test_format_skip_no_interval():
    from loops.lenses.sync import _format_skip
    result = _format_skip({"kind": "metric", "last_run_ts": time.time() - 60})
    assert "metric" in result

def test_format_skip_minimal():
    from loops.lenses.sync import _format_skip
    assert _format_skip({"kind": "metric"}) == "metric"


def test_sync_minimal_empty():
    from loops.lenses.sync import sync_view
    t = _text(sync_view({}, Zoom.MINIMAL, 80))
    assert "nothing to sync" in t

def test_sync_minimal_with_facts():
    from loops.lenses.sync import sync_view
    data = {"ran": ["metric"], "fact_counts": {"metric": 5}}
    t = _text(sync_view(data, Zoom.MINIMAL, 80))
    assert "5 facts" in t
    assert "1 ran" in t

def test_sync_summary_instance():
    from loops.lenses.sync import sync_view
    data = {"ran": ["metric", "status"], "fact_counts": {"metric": 3, "status": 1}, "skipped": [{"kind": "health", "last_run_ts": time.time() - 60}]}
    t = _text(sync_view(data, Zoom.SUMMARY, 80))
    assert "Ran:" in t
    assert "metric (3)" in t

def test_sync_with_errors():
    """Errors list in sync data (L78)."""
    from loops.lenses.sync import sync_view
    data = {"ran": ["metric"], "fact_counts": {"metric": 1}, "errors": [{"payload": {"error": "timeout"}}]}
    t = _text(sync_view(data, Zoom.MINIMAL, 80))
    assert "1 errors" in t

def test_sync_with_ticks():
    """sync_view with ticks (L135-136 — tick rendering path)."""
    from loops.lenses.sync import sync_view
    data = {
        "ran": ["metric"], "fact_counts": {"metric": 3},
        "ticks": [{"name": "session", "payload": {}, "ts": 1e9}],
    }
    t = _text(sync_view(data, Zoom.SUMMARY, 80))
    assert "Ran:" in t

def test_sync_aggregation_children():
    """Aggregation path with children."""
    from loops.lenses.sync import sync_view
    data = {
        "children": [
            {"name": "proj", "ran": ["metric"], "skipped": [], "fact_counts": {"metric": 5}},
        ],
        "fact_counts": {"metric": 5},
    }
    t = _text(sync_view(data, Zoom.SUMMARY, 80))
    assert "proj:" in t or "5 facts" in t
