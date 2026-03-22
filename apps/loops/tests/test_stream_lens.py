"""Tests for stream lens — zoom-level event history rendering."""

import time

from painted import Zoom

from .helpers import block_text as _text


def _fact(kind="metric", payload=None, ts=None, **kw):
    f = {"kind": kind, "payload": payload or {}, "ts": ts or time.time()}
    f.update(kw)
    return f


def test_stream_empty():
    from loops.lenses.stream import stream_view
    assert "No facts" in _text(stream_view({"facts": []}, Zoom.SUMMARY, 80))

def test_stream_tick_error():
    from loops.lenses.stream import stream_view
    assert "error msg" in _text(stream_view({"_tick_error": "error msg"}, Zoom.SUMMARY, 80))

def test_stream_minimal():
    from loops.lenses.stream import stream_view
    data = {"facts": [_fact("metric"), _fact("status")]}
    t = _text(stream_view(data, Zoom.MINIMAL, 80))
    assert "1 metric" in t
    assert "1 status" in t

def test_stream_minimal_with_tick():
    from loops.lenses.stream import stream_view
    data = {"facts": [_fact()], "_tick": {"index": 0, "total": 5}}
    assert "tick #0" in _text(stream_view(data, Zoom.MINIMAL, 80))

def test_stream_summary():
    from loops.lenses.stream import stream_view
    data = {"facts": [_fact("decision", {"topic": "auth", "message": "Use JWT"})]}
    t = _text(stream_view(data, Zoom.SUMMARY, 80))
    assert "[decision]" in t
    assert "auth" in t

def test_stream_summary_with_key_field():
    from loops.lenses.stream import stream_view
    data = {"facts": [_fact("metric", {"name": "cpu"})], "fold_meta": {"metric": {"key_field": "name"}}}
    assert "cpu" in _text(stream_view(data, Zoom.SUMMARY, 80))

def test_stream_detailed_with_id():
    from loops.lenses.stream import stream_view
    data = {"facts": [_fact("m", {"name": "x"}, id="01ABCDEFGHIJKLMNO123456789")]}
    t = _text(stream_view(data, Zoom.DETAILED, 80))
    assert "id:" in t

def test_stream_detailed_secondary_fields():
    from loops.lenses.stream import stream_view
    data = {"facts": [_fact("m", {"name": "x", "status": "open", "extra": "val"})]}
    t = _text(stream_view(data, Zoom.DETAILED, 80))
    assert "extra:" in t

def test_stream_full():
    from loops.lenses.stream import stream_view
    data = {"facts": [_fact("m", {"name": "x"}, id="01ABC", observer="alice", origin="proj")]}
    t = _text(stream_view(data, Zoom.FULL, 80))
    assert "observer: alice" in t
    assert "origin: proj" in t

def test_stream_id_lookup():
    from loops.lenses.stream import stream_view
    data = {"facts": [_fact("m", {"name": "x"}, id="01ABC", observer="a")], "_id_lookup": True}
    t = _text(stream_view(data, Zoom.SUMMARY, 80))
    assert "01ABC" in t

def test_stream_tick_header():
    from loops.lenses.stream import stream_view
    data = {"facts": [_fact()], "_tick": {
        "index": 2, "total": 10, "since": "2024-01-01T00:00:00", "ts": "2024-01-02T00:00:00",
        "boundary": {"name": "session", "status": "closed"},
    }}
    t = _text(stream_view(data, Zoom.SUMMARY, 80))
    assert "Tick #2" in t
    assert "session closed" in t
    assert "window:" in t

def test_stream_tick_range():
    from loops.lenses.stream import stream_view
    data = {"facts": [_fact()], "_tick": {"index": 0, "range_end": 3, "total": 10}}
    t = _text(stream_view(data, Zoom.SUMMARY, 80))
    assert "Ticks #0:3" in t

def test_stream_date_grouping():
    from loops.lenses.stream import stream_view
    data = {"facts": [
        _fact(ts="2024-03-15T10:00:00"),
        _fact(ts="2024-03-16T10:00:00"),
    ]}
    t = _text(stream_view(data, Zoom.SUMMARY, 80))
    assert "2024-03-15" in t
    assert "2024-03-16" in t


# --- Helpers ---

def test_stream_summary_helper():
    from loops.lenses.stream import _stream_summary
    assert _stream_summary({"topic": "auth", "message": "JWT"}) == "auth: JWT"
    assert _stream_summary({"topic": "auth"}) == "auth"
    assert "42" in _stream_summary({"x": 42})

def test_summary_fields():
    from loops.lenses.stream import _summary_fields
    result = _summary_fields({"topic": "a", "message": "b"})
    assert "topic" in result
    assert "message" in result
