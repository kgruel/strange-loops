"""Tests for ticks lens — zoom-level rendering of tick history."""

from datetime import datetime, timezone

from painted import Zoom

from .helpers import block_text as _text


def test_ticks_empty():
    from loops.lenses.ticks import ticks_view
    assert "No ticks" in _text(ticks_view({"ticks": []}, Zoom.SUMMARY, 80))

def test_ticks_minimal():
    from loops.lenses.ticks import ticks_view
    data = {"ticks": [{"name": "s", "ts": "2024-03-15T10:00:00", "kind_counts": {"m": 5}}]}
    assert "1 ticks" in _text(ticks_view(data, Zoom.MINIMAL, 80))

def test_ticks_summary_with_trigger():
    from loops.lenses.ticks import ticks_view
    data = {"ticks": [{
        "name": "session", "ts": "2024-03-15T10:00:00",
        "boundary": {"name": "session", "status": "closed"},
        "kind_counts": {"m": 5}, "since": "2024-03-15T09:00:00",
    }]}
    t = _text(ticks_view(data, Zoom.SUMMARY, 80))
    assert "session closed" in t

def test_ticks_summary_no_trigger():
    from loops.lenses.ticks import ticks_view
    data = {"ticks": [{"name": "s", "ts": "2024-03-15T10:00:00", "kind_counts": {"m": 5}}]}
    t = _text(ticks_view(data, Zoom.SUMMARY, 80))
    assert "#0" in t

def test_ticks_detailed():
    from loops.lenses.ticks import ticks_view
    data = {"ticks": [{"name": "s", "ts": "2024-03-15T10:00:00", "kind_counts": {"m": 5, "s": 2}}]}
    t = _text(ticks_view(data, Zoom.DETAILED, 80))
    assert "fold:" in t

def test_ticks_full():
    from loops.lenses.ticks import ticks_view
    data = {"ticks": [{
        "name": "s", "ts": "2024-03-15T10:00:00",
        "since": "2024-03-15T09:00:00",
        "boundary": {"name": "s"}, "kind_counts": {"m": 1}, "origin": "proj",
    }]}
    t = _text(ticks_view(data, Zoom.FULL, 80))
    assert "origin:" in t
    assert "window:" in t

def test_ticks_date_grouping():
    from loops.lenses.ticks import ticks_view
    data = {"ticks": [
        {"name": "s", "ts": "2024-03-15T10:00:00", "kind_counts": {}},
        {"name": "s", "ts": "2024-03-16T10:00:00", "kind_counts": {}},
    ]}
    t = _text(ticks_view(data, Zoom.SUMMARY, 80))
    assert "2024-03-15" in t
    assert "2024-03-16" in t

def test_format_duration_seconds():
    from loops.lenses.ticks import _format_duration
    assert _format_duration(datetime(2024, 1, 1, 10, 0), datetime(2024, 1, 1, 10, 0, 30)) == "30s"

def test_format_duration_minutes():
    from loops.lenses.ticks import _format_duration
    assert _format_duration(datetime(2024, 1, 1, 10, 0), datetime(2024, 1, 1, 10, 5)) == "5m"

def test_format_duration_hours():
    from loops.lenses.ticks import _format_duration
    assert _format_duration(datetime(2024, 1, 1, 10, 0), datetime(2024, 1, 1, 13, 30)) == "3h30m"

def test_format_duration_hours_exact():
    from loops.lenses.ticks import _format_duration
    assert _format_duration(datetime(2024, 1, 1, 10, 0), datetime(2024, 1, 1, 12, 0)) == "2h"

def test_format_duration_days():
    from loops.lenses.ticks import _format_duration
    assert _format_duration(datetime(2024, 1, 1, 10, 0), datetime(2024, 1, 4, 14, 0)) == "3d4h"

def test_format_duration_days_exact():
    from loops.lenses.ticks import _format_duration
    assert _format_duration(datetime(2024, 1, 1, 10, 0), datetime(2024, 1, 3, 10, 0)) == "2d"

def test_parse_ts_datetime():
    from loops.lenses.ticks import _parse_ts
    dt = datetime(2024, 1, 1, tzinfo=timezone.utc)
    assert _parse_ts(dt) is dt

def test_parse_ts_string():
    from loops.lenses.ticks import _parse_ts
    assert _parse_ts("2024-03-15T10:00:00").year == 2024
