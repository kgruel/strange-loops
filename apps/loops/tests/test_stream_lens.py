"""Tests for stream lens — zoom-level event history rendering."""

import time

from painted import Zoom

from loops.lenses.stream import _stream_summary, _summary_fields, stream_view

from .helpers import block_text as _text


def _fact(kind="metric", payload=None, ts=None, **kw):
    return {"kind": kind, "payload": payload or {}, "ts": ts or time.time(), **kw}


def test_stream_empty():
    assert "No facts" in _text(stream_view({"facts": []}, Zoom.SUMMARY, 80))

def test_stream_tick_error():
    assert "error msg" in _text(stream_view({"_tick_error": "error msg"}, Zoom.SUMMARY, 80))

def test_stream_minimal():
    t = _text(stream_view({"facts": [_fact("metric"), _fact("status")]}, Zoom.MINIMAL, 80))
    assert "1 metric" in t and "1 status" in t

def test_stream_minimal_with_tick():
    data = {"facts": [_fact()], "_tick": {"index": 0, "total": 5}}
    assert "tick #0" in _text(stream_view(data, Zoom.MINIMAL, 80))

def test_stream_summary():
    t = _text(stream_view({"facts": [_fact("decision", {"topic": "auth", "message": "Use JWT"})]}, Zoom.SUMMARY, 80))
    assert "[decision]" in t and "auth" in t

def test_stream_summary_with_key_field():
    data = {"facts": [_fact("metric", {"name": "cpu"})], "fold_meta": {"metric": {"key_field": "name"}}}
    assert "cpu" in _text(stream_view(data, Zoom.SUMMARY, 80))

def test_stream_detailed_with_id():
    t = _text(stream_view({"facts": [_fact("m", {"name": "x"}, id="01ABCDEFGHIJKLMNO123456789")]}, Zoom.DETAILED, 80))
    assert "id:" in t

def test_stream_detailed_secondary_fields():
    t = _text(stream_view({"facts": [_fact("m", {"name": "x", "status": "open", "extra": "val"})]}, Zoom.DETAILED, 80))
    assert "extra:" in t

def test_stream_full():
    t = _text(stream_view({"facts": [_fact("m", {"name": "x"}, id="01ABC", observer="alice", origin="proj")]}, Zoom.FULL, 80))
    assert "observer: alice" in t and "origin: proj" in t

def test_stream_id_lookup():
    t = _text(stream_view({"facts": [_fact("m", {"name": "x"}, id="01ABC", observer="a")], "_id_lookup": True}, Zoom.SUMMARY, 80))
    assert "01ABC" in t

def test_stream_tick_header():
    data = {"facts": [_fact()], "_tick": {
        "index": 2, "total": 10, "since": "2024-01-01T00:00:00", "ts": "2024-01-02T00:00:00",
        "boundary": {"name": "session", "status": "closed"},
    }}
    t = _text(stream_view(data, Zoom.SUMMARY, 80))
    assert "Tick #2" in t and "session closed" in t and "window:" in t

def test_stream_tick_range():
    data = {"facts": [_fact()], "_tick": {"index": 0, "range_end": 3, "total": 10}}
    assert "Ticks #0:3" in _text(stream_view(data, Zoom.SUMMARY, 80))

def test_stream_date_grouping():
    data = {"facts": [_fact(ts="2024-03-15T10:00:00"), _fact(ts="2024-03-16T10:00:00")]}
    t = _text(stream_view(data, Zoom.SUMMARY, 80))
    assert "2024-03-15" in t and "2024-03-16" in t

def test_stream_no_width():
    assert stream_view({"facts": [_fact("m", {"name": "x"})]}, Zoom.SUMMARY, None) is not None

def test_stream_tick_no_facts():
    assert stream_view({"facts": [], "_tick": {"index": 0, "total": 5}}, Zoom.SUMMARY, 80) is not None

def test_stream_summary_key_not_in_labels():
    assert "X" in _stream_summary({"custom_id": "X", "name": "foo"}, key_field="custom_id")

def test_stream_summary_fallback_to_known_field():
    assert _stream_summary({"z_extra": "", "name": "fallback"}) == "fallback"

def test_summary_fields_key_not_in_labels():
    assert "custom" in _summary_fields({"custom": "v", "name": "n"}, key_field="custom")

def test_summary_fields_key_in_labels_with_reorder():
    assert "name" in _summary_fields({"name": "n", "topic": "t"}, key_field="name")

def test_stream_summary_helper():
    assert _stream_summary({"topic": "auth", "message": "JWT"}) == "auth: JWT"
    assert _stream_summary({"topic": "auth"}) == "auth"
    assert "42" in _stream_summary({"x": 42})

def test_summary_fields():
    result = _summary_fields({"topic": "a", "message": "b"})
    assert "topic" in result and "message" in result

def test_stream_no_width_error():
    """stream_view with width=None hits _block (L14)."""
    block = stream_view({"_tick_error": "bad"}, Zoom.SUMMARY, None)
    assert block is not None


def test_stream_summary_last_resort_str_payload():
    """_stream_summary returns str(payload) when payload has no standard label fields (L192)."""
    payload = {"value": "42", "unit": "ms"}  # no topic/name/summary/message
    result = _stream_summary(payload)
    # Last resort: str(payload) is returned
    assert "42" in result or "ms" in result or result == str(payload)
