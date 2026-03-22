"""Tests for sync lens rendering — all zoom levels."""

import time

from painted import Zoom

from loops.lenses.sync import _format_ago, _format_interval, _format_skip, sync_view

from .helpers import block_text as _text


def test_format_ago():
    assert _format_ago(time.time() - 30).endswith("s ago")
    assert _format_ago(time.time() - 300).endswith("m ago")
    assert _format_ago(time.time() - 7200).endswith("h ago")
    assert _format_ago(time.time() - 172800).endswith("d ago")

def test_format_interval():
    assert _format_interval(30) == "30s"
    assert _format_interval(300) == "5m"
    assert _format_interval(7200) == "2h"
    assert _format_interval(172800) == "2d"

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
