"""Tests for run lens — zoom-level rendering of facts and ticks."""

from datetime import datetime, timezone

from painted import Zoom

from loops.lenses.run import _format_ts, run_facts_view, run_ticks_view

from .helpers import block_text as _text


def test_facts_empty():
    assert "No facts" in _text(run_facts_view([], Zoom.SUMMARY, 80))

def test_facts_minimal():
    assert "[metric]" in _text(run_facts_view([{"kind": "metric", "payload": {"n": 1}}], Zoom.MINIMAL, 80))

def test_facts_summary_many_keys():
    data = [{"kind": "m", "payload": {"a": 1, "b": 2, "c": 3, "d": 4}}]
    assert "..." in _text(run_facts_view(data, Zoom.SUMMARY, 80))

def test_facts_summary_non_dict_payload():
    assert "[m]" in _text(run_facts_view([{"kind": "m", "payload": "raw"}], Zoom.SUMMARY, 80))

def test_facts_detailed():
    assert "[m]" in _text(run_facts_view([{"kind": "m", "payload": {"x": 1}}], Zoom.DETAILED, 80))

def test_facts_full():
    data = [{"kind": "m", "payload": {}, "ts": 1e9, "observer": "a", "origin": "b"}]
    t = _text(run_facts_view(data, Zoom.FULL, 80))
    assert "observer=a" in t and "origin=b" in t

def test_facts_footer():
    assert "1 facts" in _text(run_facts_view([{"kind": "x", "payload": {}}], Zoom.MINIMAL, 80))

def test_ticks_empty():
    assert "No ticks" in _text(run_ticks_view([], Zoom.SUMMARY, 80))

def test_ticks_minimal():
    assert "s" in _text(run_ticks_view([{"name": "s", "payload": {}, "ts": 1e9}], Zoom.MINIMAL, 80))

def test_ticks_summary():
    assert "1 keys" in _text(run_ticks_view([{"name": "s", "payload": {"n": 1}, "ts": 1e9}], Zoom.SUMMARY, 80))

def test_ticks_detailed():
    assert "n:" in _text(run_ticks_view([{"name": "s", "payload": {"n": 1}, "ts": 1e9}], Zoom.DETAILED, 80))

def test_ticks_full():
    t = _text(run_ticks_view([{"name": "s", "payload": {"n": 1}, "ts": 1e9, "origin": "proj"}], Zoom.FULL, 80))
    assert "origin=proj" in t

def test_format_ts_float():
    assert "2001" in _format_ts(1e9)

def test_format_ts_empty():
    assert _format_ts("") == "?"

def test_run_no_width():
    assert run_facts_view([{"kind": "m", "payload": {}}], Zoom.MINIMAL, None) is not None

def test_format_ts_datetime():
    dt = datetime(2024, 3, 15, 10, 0, 0, tzinfo=timezone.utc)
    assert "2024" in _format_ts(dt)
