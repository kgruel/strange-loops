"""Unit tests for the shared static-grammar vocabulary (lenses/_grammar)."""

import time
from datetime import datetime, timedelta, timezone

from painted import Style

from loops.lenses._grammar import (
    DateGrouper,
    attest_line,
    clock,
    coerce_dt,
    date_key,
    duration,
    full_iso,
    recency,
    short_date,
    stamp,
    tick_drill_rows,
)


class TestCoerceDt:
    def test_datetime_aware_passthrough(self):
        dt = datetime(2024, 3, 15, 10, 0, tzinfo=timezone.utc)
        assert coerce_dt(dt) is dt

    def test_datetime_naive_gets_utc(self):
        assert coerce_dt(datetime(2024, 3, 15)).tzinfo is not None

    def test_iso_string(self):
        assert coerce_dt("2024-03-15T10:00:00").year == 2024

    def test_epoch(self):
        assert coerce_dt(0).year == 1970

    def test_garbage_is_none(self):
        assert coerce_dt("not-a-date") is None
        assert coerce_dt(None) is None
        assert coerce_dt([1, 2]) is None


class TestRecency:
    def test_ladder(self):
        now = time.time()
        assert recency(now - 30) == "now"
        assert recency(now - 300) == "5m"
        assert recency(now - 7200) == "2h"
        assert recency(now - 3 * 86400) == "3d"
        assert recency(now - 14 * 86400) == "2w"

    def test_calendar_cutover(self):
        old = datetime.now(timezone.utc) - timedelta(days=90)
        tag = recency(old)
        assert tag == f"{old.strftime('%b')} {old.day}"

    def test_future_is_now(self):
        assert recency(time.time() + 3600) == "now"

    def test_unparseable_is_empty(self):
        assert recency("nope") == ""
        assert recency(None) == ""


class TestForms:
    DT = datetime(2024, 3, 15, 9, 5, 7, tzinfo=timezone.utc)

    def test_clock(self):
        assert clock(self.DT) == "09:05"

    def test_date_key(self):
        assert date_key(self.DT) == "2024-03-15"

    def test_short_date_no_zero_pad(self):
        assert short_date(datetime(2024, 3, 5, tzinfo=timezone.utc)) == "Mar 5"

    def test_short_date_string_fallback(self):
        assert short_date("not-a-date-x") == "not-a-date"

    def test_stamp(self):
        assert stamp(self.DT) == "2024-03-15 09:05"

    def test_full_iso_string_passthrough(self):
        assert full_iso("2024-03-15T09:05:07") == "2024-03-15T09:05:07"

    def test_full_iso_epoch(self):
        assert full_iso(self.DT.timestamp()).startswith("2024-03-15T09:05:07")


class TestDuration:
    START = datetime(2024, 1, 1, 10, 0)

    def test_ladder(self):
        assert duration(self.START, self.START + timedelta(seconds=30)) == "30s"
        assert duration(self.START, self.START + timedelta(minutes=5)) == "5m"
        assert duration(self.START, self.START + timedelta(hours=3, minutes=30)) == "3h30m"
        assert duration(self.START, self.START + timedelta(hours=2)) == "2h"
        assert duration(self.START, self.START + timedelta(days=3, hours=4)) == "3d4h"
        assert duration(self.START, self.START + timedelta(days=2)) == "2d"


class TestDateGrouper:
    def test_headers_on_date_change_only(self):
        g = DateGrouper()
        d1 = datetime(2024, 3, 15, 9, 0, tzinfo=timezone.utc)
        d2 = datetime(2024, 3, 15, 17, 0, tzinfo=timezone.utc)
        d3 = datetime(2024, 3, 16, 1, 0, tzinfo=timezone.utc)

        first = g.header_rows(d1)
        assert [t for t, _ in first] == ["2024-03-15:"]
        assert g.header_rows(d2) == []
        rows = g.header_rows(d3)
        assert [t for t, _ in rows] == ["", "2024-03-16:"]


class TestTickEnvelope:
    def test_attest_absent(self):
        assert attest_line(None) == ""

    def test_attest_unchained(self):
        assert "none" in attest_line({"chained": False})

    def test_attest_chained_signed_cursor(self):
        line = attest_line(
            {"chained": True, "signed": True, "cursor_kind": "decision",
             "cursor_preview": "topic x"}
        )
        assert "chained · signed" in line
        assert 'decision: "topic x"' in line

    def test_drill_rows_single(self):
        rows = tick_drill_rows(
            {"index": 3, "total": 10, "since": "a", "ts": "b",
             "boundary": {"name": "session", "status": "end"}}
        )
        texts = [t for t, _ in rows]
        assert texts[0] == "Tick #3 of 10 — session end"
        assert texts[1] == "  window: a → b"

    def test_drill_rows_range_observers(self):
        rows = tick_drill_rows(
            {"index": 0, "total": 10, "range_end": 3,
             "range_boundaries": [{"name": "kyle"}, {"name": "kyle"}, {"name": "agent"}]}
        )
        assert rows[0][0] == "Ticks #0:3 of 10 — kyle, agent"

    def test_drill_rows_empty(self):
        assert tick_drill_rows({}) == []

    def test_rows_are_styled_tuples(self):
        rows = tick_drill_rows({"index": 0, "total": 1})
        assert all(isinstance(s, Style) for _, s in rows)


class TestRail:
    def test_glyphs(self):
        from loops.lenses._grammar import rail_glyph

        assert rail_glyph("high") == "◆"
        assert rail_glyph("mid") == "│"
        assert rail_glyph("tail") == "·"
        assert rail_glyph("stale") == "⊘"
        assert rail_glyph("unknown") == "│"
