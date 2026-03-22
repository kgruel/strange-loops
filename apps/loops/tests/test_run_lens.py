"""Tests for run lens — zoom-level rendering of facts and ticks."""

from painted import Zoom

from .helpers import block_text as _text


def test_facts_empty():
    from loops.lenses.run import run_facts_view
    assert "No facts" in _text(run_facts_view([], Zoom.SUMMARY, 80))

def test_facts_minimal():
    from loops.lenses.run import run_facts_view
    assert "[metric]" in _text(run_facts_view([{"kind": "metric", "payload": {"n": 1}}], Zoom.MINIMAL, 80))

def test_facts_summary_many_keys():
    from loops.lenses.run import run_facts_view
    data = [{"kind": "m", "payload": {"a": 1, "b": 2, "c": 3, "d": 4}}]
    assert "..." in _text(run_facts_view(data, Zoom.SUMMARY, 80))

def test_facts_summary_non_dict_payload():
    from loops.lenses.run import run_facts_view
    data = [{"kind": "m", "payload": "raw"}]
    assert "[m]" in _text(run_facts_view(data, Zoom.SUMMARY, 80))

def test_facts_detailed():
    from loops.lenses.run import run_facts_view
    data = [{"kind": "m", "payload": {"x": 1}}]
    assert "[m]" in _text(run_facts_view(data, Zoom.DETAILED, 80))

def test_facts_full():
    from loops.lenses.run import run_facts_view
    data = [{"kind": "m", "payload": {}, "ts": 1e9, "observer": "a", "origin": "b"}]
    t = _text(run_facts_view(data, Zoom.FULL, 80))
    assert "observer=a" in t
    assert "origin=b" in t

def test_facts_footer():
    from loops.lenses.run import run_facts_view
    assert "1 facts" in _text(run_facts_view([{"kind": "x", "payload": {}}], Zoom.MINIMAL, 80))

def test_ticks_empty():
    from loops.lenses.run import run_ticks_view
    assert "No ticks" in _text(run_ticks_view([], Zoom.SUMMARY, 80))

def test_ticks_minimal():
    from loops.lenses.run import run_ticks_view
    data = [{"name": "s", "payload": {}, "ts": 1e9}]
    assert "s" in _text(run_ticks_view(data, Zoom.MINIMAL, 80))

def test_ticks_summary():
    from loops.lenses.run import run_ticks_view
    data = [{"name": "s", "payload": {"n": 1}, "ts": 1e9}]
    assert "1 keys" in _text(run_ticks_view(data, Zoom.SUMMARY, 80))

def test_ticks_detailed():
    from loops.lenses.run import run_ticks_view
    data = [{"name": "s", "payload": {"n": 1}, "ts": 1e9}]
    t = _text(run_ticks_view(data, Zoom.DETAILED, 80))
    assert "n:" in t

def test_ticks_full():
    from loops.lenses.run import run_ticks_view
    data = [{"name": "s", "payload": {"n": 1}, "ts": 1e9, "origin": "proj"}]
    t = _text(run_ticks_view(data, Zoom.FULL, 80))
    assert "origin=proj" in t

def test_format_ts_float():
    from loops.lenses.run import _format_ts
    assert "2001" in _format_ts(1e9)

def test_format_ts_empty():
    from loops.lenses.run import _format_ts
    assert _format_ts("") == "?"
