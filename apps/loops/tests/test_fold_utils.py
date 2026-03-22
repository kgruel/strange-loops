"""Tests for fold.py utility functions — pure logic, no rendering."""

import time
from collections import Counter
from datetime import datetime, timezone

import pytest
from atoms import FoldItem, FoldSection, FoldState


def item(payload=None, ts=None, observer="", origin="", n=1, refs=()):
    return FoldItem(payload=payload or {}, ts=ts, observer=observer, origin=origin, n=n, refs=refs)


def section(kind="test", items=(), fold_type="by", key_field="name", scalars=None):
    return FoldSection(kind=kind, items=items, fold_type=fold_type, key_field=key_field, scalars=scalars or {})


def state(sections=(), vertex="v", unfolded=None):
    return FoldState(sections=sections, vertex=vertex, unfolded=unfolded or {})


# ---------------------------------------------------------------------------
# _truncate
# ---------------------------------------------------------------------------

class TestTruncate:
    def test_short_text(self):
        from loops.lenses.fold import _truncate
        assert _truncate("hello", 20) == "hello"

    def test_long_text(self):
        from loops.lenses.fold import _truncate
        result = _truncate("a" * 50, 20)
        assert len(result) == 20
        assert result.endswith("\u2026")

    def test_min_len_floor(self):
        from loops.lenses.fold import _truncate
        result = _truncate("a" * 50, 3)
        assert len(result) == 10  # min floor is 10


# ---------------------------------------------------------------------------
# _recency_tag
# ---------------------------------------------------------------------------

class TestRecencyTag:
    def test_none(self):
        from loops.lenses.fold import _recency_tag
        assert _recency_tag(None) == ""

    def test_invalid_string(self):
        from loops.lenses.fold import _recency_tag
        assert _recency_tag("not-a-date") == ""

    def test_non_numeric_type(self):
        from loops.lenses.fold import _recency_tag
        assert _recency_tag([1, 2, 3]) == ""

    def test_future_timestamp(self):
        from loops.lenses.fold import _recency_tag
        assert _recency_tag(time.time() + 3600) == "now"

    def test_minutes_ago(self):
        from loops.lenses.fold import _recency_tag
        result = _recency_tag(time.time() - 300)  # 5 min ago
        assert result.endswith("m")

    def test_hours_ago(self):
        from loops.lenses.fold import _recency_tag
        result = _recency_tag(time.time() - 7200)  # 2 hours ago
        assert result.endswith("h")

    def test_days_ago(self):
        from loops.lenses.fold import _recency_tag
        result = _recency_tag(time.time() - 259200)  # 3 days ago
        assert result.endswith("d")

    def test_weeks_ago(self):
        from loops.lenses.fold import _recency_tag
        result = _recency_tag(time.time() - 1209600)  # 2 weeks
        assert result.endswith("w")

    def test_months_ago(self):
        from loops.lenses.fold import _recency_tag
        result = _recency_tag(time.time() - 5184000)  # ~60 days
        assert len(result) > 0  # month abbreviation like "Jan 15"

    def test_iso_string(self):
        from loops.lenses.fold import _recency_tag
        ts = datetime.now(tz=timezone.utc).isoformat()
        result = _recency_tag(ts)
        assert result.endswith("m") or result == "0m"


# ---------------------------------------------------------------------------
# _format_date / _format_ts_full
# ---------------------------------------------------------------------------

class TestFormatDate:
    def test_iso_string(self):
        from loops.lenses.fold import _format_date
        result = _format_date("2024-03-15T10:00:00")
        assert "Mar" in result

    def test_invalid_string(self):
        from loops.lenses.fold import _format_date
        result = _format_date("nope")
        assert result == "nope"

    def test_datetime_obj(self):
        from loops.lenses.fold import _format_date
        dt = datetime(2024, 1, 5, tzinfo=timezone.utc)
        result = _format_date(dt)
        assert "Jan" in result

    def test_epoch_float(self):
        from loops.lenses.fold import _format_date
        result = _format_date(1710504000.0)  # 2024-03-15
        assert len(result) > 0

    def test_unknown_type(self):
        from loops.lenses.fold import _format_date
        assert _format_date([1, 2]) == "?"


class TestFormatTsFull:
    def test_string_passthrough(self):
        from loops.lenses.fold import _format_ts_full
        assert _format_ts_full("2024-03-15T10:00:00") == "2024-03-15T10:00:00"

    def test_datetime_obj(self):
        from loops.lenses.fold import _format_ts_full
        dt = datetime(2024, 1, 5, 12, 0, 0, tzinfo=timezone.utc)
        result = _format_ts_full(dt)
        assert "2024" in result

    def test_epoch_float(self):
        from loops.lenses.fold import _format_ts_full
        result = _format_ts_full(1710504000.0)
        assert "2024" in result

    def test_unknown_type(self):
        from loops.lenses.fold import _format_ts_full
        assert _format_ts_full(None) == "?"


# ---------------------------------------------------------------------------
# _item_full_key / _inbound_count / _compute_*
# ---------------------------------------------------------------------------

class TestItemFullKey:
    def test_no_key_field(self):
        from loops.lenses.fold import _item_full_key
        assert _item_full_key(item({"name": "x"}), None) == ""

    def test_no_key_value(self):
        from loops.lenses.fold import _item_full_key
        assert _item_full_key(item({}), "name") == ""

    def test_with_kind(self):
        from loops.lenses.fold import _item_full_key
        assert _item_full_key(item({"name": "x"}), "name", "decision") == "decision/x"

    def test_without_kind(self):
        from loops.lenses.fold import _item_full_key
        assert _item_full_key(item({"name": "x"}), "name") == "x"


class TestInboundCount:
    def test_no_key_field(self):
        from loops.lenses.fold import _inbound_count
        assert _inbound_count(item(), None, Counter()) == 0

    def test_no_key_value(self):
        from loops.lenses.fold import _inbound_count
        assert _inbound_count(item({}), "name", Counter()) == 0

    def test_with_refs(self):
        from loops.lenses.fold import _inbound_count
        inbound = Counter({"decision/auth": 3, "thread/auth": 1})
        assert _inbound_count(item({"name": "auth"}), "name", inbound) == 4


class TestComputeInboundRefs:
    def test_with_refs(self):
        from loops.lenses.fold import _compute_inbound_refs
        i1 = item(refs=("decision/x", "thread/y"))
        i2 = item(refs=("decision/x",))
        s = section(items=(i1, i2))
        result = _compute_inbound_refs(state(sections=(s,)))
        assert result["decision/x"] == 2
        assert result["thread/y"] == 1


class TestComputeInboundEdges:
    def test_with_edges(self):
        from loops.lenses.fold import _compute_inbound_edges
        i1 = item({"name": "a"}, refs=("decision/b",))
        s = section(items=(i1,), kind="thread", key_field="name")
        result = _compute_inbound_edges(state(sections=(s,)))
        assert "decision/b" in result
        assert "thread/a" in result["decision/b"]

    def test_no_refs(self):
        from loops.lenses.fold import _compute_inbound_edges
        i1 = item({"name": "a"})
        s = section(items=(i1,))
        result = _compute_inbound_edges(state(sections=(s,)))
        assert result == {}


# ---------------------------------------------------------------------------
# _first_field / _group_by_namespace
# ---------------------------------------------------------------------------

class TestFirstField:
    def test_empty_payload(self):
        from loops.lenses.fold import _first_field
        assert _first_field({}) == ("?", None)

    def test_all_empty(self):
        from loops.lenses.fold import _first_field
        assert _first_field({"a": "", "b": None}) == ("?", None)


class TestGroupByNamespace:
    def test_no_namespace(self):
        from loops.lenses.fold import _group_by_namespace
        items = (item({"name": "x"}), item({"name": "y"}))
        result = _group_by_namespace(items, "name")
        assert "" in result
        assert len(result[""]) == 2


# ---------------------------------------------------------------------------
# fold_view rendering paths
# ---------------------------------------------------------------------------

class TestFoldView:
    def _text(self, block):
        return "\n".join("".join(c.char for c in row).rstrip() for row in block._rows)

    def test_empty_data(self):
        from loops.lenses.fold import fold_view
        from painted import Zoom
        data = state(sections=())
        assert "No data" in self._text(fold_view(data, Zoom.SUMMARY, 80))

    def test_minimal_zoom(self):
        from loops.lenses.fold import fold_view
        from painted import Zoom
        s = section(kind="decision", items=(item({"name": "x"}),))
        data = state(sections=(s,))
        t = self._text(fold_view(data, Zoom.MINIMAL, 80))
        assert "1 decisions" in t

    def test_minimal_with_unfolded(self):
        from loops.lenses.fold import fold_view
        from painted import Zoom
        s = section(kind="thread", items=(item({"name": "a"}),))
        data = state(sections=(s,), unfolded={"orphan": 3})
        t = self._text(fold_view(data, Zoom.MINIMAL, 80))
        assert "unfolded" in t

    def test_summary_zoom(self):
        from loops.lenses.fold import fold_view
        from painted import Zoom
        s = section(kind="decision", items=(
            item({"name": "auth", "message": "Use JWT"}, ts=1710504000.0, n=2),
        ))
        data = state(sections=(s,))
        t = self._text(fold_view(data, Zoom.SUMMARY, 80))
        assert "Decision" in t or "decision" in t

    def test_refs_filter(self):
        from loops.lenses.fold import fold_view
        from painted import Zoom
        i1 = item({"name": "x"}, refs=("decision/y",))
        i2 = item({"name": "y"})  # no refs, no inbound
        s = section(kind="thread", items=(i1, i2), key_field="name")
        data = state(sections=(s,))
        t = self._text(fold_view(data, Zoom.SUMMARY, 80, visible={"refs"}))
        # Should show section but filter disconnected items
        assert "thread" in t.lower() or "Thread" in t

    def test_facts_filter(self):
        from loops.lenses.fold import fold_view
        from painted import Zoom
        i1 = item({"name": "x"}, n=3)
        s = section(kind="metric", items=(i1,), fold_type="by")
        data = state(sections=(s,))
        t = self._text(fold_view(data, Zoom.SUMMARY, 80, visible={"facts"}))
        assert len(t) > 0

    def test_footer_with_skipped(self):
        from loops.lenses.fold import fold_view
        from painted import Zoom
        # collect fold with facts filter → skipped (no history)
        s = section(kind="metric", items=(item({"name": "x"}),), fold_type="collect")
        data = state(sections=(s,))
        t = self._text(fold_view(data, Zoom.SUMMARY, 80, visible={"facts"}))
        # Should show filtered message
        assert len(t) > 0
