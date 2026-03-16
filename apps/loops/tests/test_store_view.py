"""Tests for store_view lens rendering and fidelity drill."""

from dataclasses import replace
from datetime import datetime, timezone, timedelta

import pytest

from painted import Zoom
from painted.views import ListState
from loops.commands.store import _bucket_timestamps, _sparkline_str
from loops.lenses.store import store_view, _relative_time
from loops.tui.store_app import FidelityState, StoreExplorerState, _payload_one_liner

from .helpers import block_to_text


def _make_summary(*, freshness=None):
    """Build a minimal summary dict matching StoreReader.summary() shape."""
    now = datetime.now(timezone.utc)
    hour_ago = now - timedelta(hours=1)

    return {
        "facts": {
            "total": 6462,
            "kinds": {
                "hn.story": {
                    "count": 3200,
                    "earliest": now - timedelta(days=30),
                    "latest": hour_ago,
                    "sample_payload": {"title": "Show HN", "url": "https://example.com"},
                },
                "rss.item": {
                    "count": 2800,
                    "earliest": now - timedelta(days=20),
                    "latest": now - timedelta(minutes=30),
                    "sample_payload": {"title": "Episode 42", "duration": "1:23:45"},
                },
                "error": {
                    "count": 462,
                    "earliest": now - timedelta(days=15),
                    "latest": now - timedelta(hours=2),
                },
            },
        },
        "ticks": {
            "total": 15,
            "names": {
                "podcast.huberman": {
                    "count": 8,
                    "earliest": now - timedelta(days=25),
                    "latest": hour_ago,
                    "latest_payload": {"episode_count": 42, "total_duration": 12345},
                    "sparkline": "▃▅▇▅▃▅▇▅",
                    "payload_keys": ["episode_count", "total_duration"],
                },
                "hn.top": {
                    "count": 7,
                    "earliest": now - timedelta(days=10),
                    "latest": now - timedelta(minutes=45),
                    "latest_payload": {"story_count": 30, "top_score": 500},
                    "sparkline": "▁▃▅▇▅▃▁▃",
                    "payload_keys": ["story_count", "top_score"],
                },
            },
        },
        "freshness": freshness or hour_ago,
    }


class TestStoreViewRendering:
    @staticmethod
    def _render(zoom):
        block = store_view(_make_summary(), zoom, 80)
        return block, block_to_text(block)

    @pytest.mark.parametrize(
        ("zoom", "present", "min_height"),
        [
            (Zoom.SUMMARY, ["hn.story", "rss.item", "3.2k", "2.8k", "ago"], 3),
            (Zoom.DETAILED, ["hn.story", "rss.item", "3.2k"], 5),
            (Zoom.FULL, ["3 kinds", "facts"], 5),
        ],
    )
    def test_zoom_levels_render_expected_content(self, zoom, present, min_height):
        block, text = self._render(zoom)
        for needle in present:
            assert needle in text
        assert "Show HN" in text or "Episode 42" in text
        assert block.height >= min_height

    def test_minimal_summary_is_dense_and_ordered(self):
        block, text = self._render(Zoom.MINIMAL)
        assert "3 kinds" in text
        assert "6.5k facts" in text or "6462" in text or "6.4k" in text
        assert "fresh" in text
        assert "ago" in text
        assert text.index("kinds") < text.index("facts")
        assert block.height >= 1

    def test_full_has_border(self):
        _, text = self._render(Zoom.FULL)
        assert "╭" in text or "│" in text


class TestRelativeTime:
    def test_seconds(self):
        now = datetime.now(timezone.utc)
        assert "s ago" in _relative_time(now - timedelta(seconds=30))

    def test_minutes(self):
        now = datetime.now(timezone.utc)
        assert "m ago" in _relative_time(now - timedelta(minutes=5))

    def test_hours(self):
        now = datetime.now(timezone.utc)
        assert "h ago" in _relative_time(now - timedelta(hours=3))

    def test_days(self):
        now = datetime.now(timezone.utc)
        assert "d ago" in _relative_time(now - timedelta(days=2))

    def test_non_datetime_returns_question(self):
        assert _relative_time("not a datetime") == "?"


# ── Sparkline tests ─────────────────────────────────────────


class TestSparkline:
    def test_bucket_empty(self):
        assert _bucket_timestamps([], 8) == []

    def test_bucket_single_timestamp(self):
        buckets = _bucket_timestamps([100.0], 8)
        assert len(buckets) == 8
        assert sum(buckets) == 1.0

    def test_bucket_identical_timestamps(self):
        buckets = _bucket_timestamps([100.0, 100.0, 100.0], 8)
        assert len(buckets) == 8
        assert sum(buckets) == 3.0
        # All in the middle bucket
        assert buckets[4] == 3.0

    def test_bucket_spread(self):
        # Timestamps at extremes should land in first and last buckets
        buckets = _bucket_timestamps([0.0, 100.0], 4)
        assert len(buckets) == 4
        assert buckets[0] >= 1.0
        assert buckets[-1] >= 1.0

    def test_bucket_zero_width(self):
        assert _bucket_timestamps([1.0, 2.0], 0) == []

    def test_sparkline_empty(self):
        assert _sparkline_str([]) == ""

    def test_sparkline_all_zero(self):
        result = _sparkline_str([0.0, 0.0, 0.0])
        assert len(result) == 3
        assert all(c == " " for c in result)

    def test_sparkline_uniform(self):
        result = _sparkline_str([5.0, 5.0, 5.0])
        assert len(result) == 3
        # All same value -> all max char
        assert result[0] == result[1] == result[2]
        assert result[0] == "█"

    def test_sparkline_ascending(self):
        result = _sparkline_str([0.0, 1.0, 2.0, 3.0])
        assert len(result) == 4
        # Should be ascending characters
        assert result[-1] == "█"

    def test_sparkline_length_matches_input(self):
        for n in [1, 5, 10, 20]:
            result = _sparkline_str([float(i) for i in range(n)])
            assert len(result) == n


# ── Fidelity drill tests ─────────────────────────────────────────


def _make_fidelity_summary():
    """Build a summary with tick since/ts data for fidelity drill testing."""
    now = datetime.now(timezone.utc)
    hour_ago = now - timedelta(hours=1)

    return {
        "facts": {
            "total": 100,
            "kinds": {
                "cpu.metric": {"count": 50, "earliest": now - timedelta(days=5), "latest": hour_ago},
                "mem.metric": {"count": 50, "earliest": now - timedelta(days=5), "latest": hour_ago},
            },
        },
        "ticks": {
            "total": 5,
            "names": {
                "health.check": {
                    "count": 5,
                    "earliest": now - timedelta(days=3),
                    "latest": hour_ago,
                    "latest_payload": {"status": "ok"},
                    "latest_since": (now - timedelta(hours=2)).timestamp(),
                    "latest_ts": hour_ago.timestamp(),
                    "sparkline": "▃▅▇▅▃",
                    "payload_keys": ["status"],
                },
            },
        },
        "freshness": hour_ago,
    }


def _make_fake_facts(n: int = 5, kinds: list[str] | None = None) -> list[dict]:
    """Generate fake fact dicts for fidelity drill testing."""
    kinds = kinds or ["cpu.metric", "mem.metric"]
    now = datetime.now(timezone.utc)
    facts = []
    for i in range(n):
        facts.append({
            "kind": kinds[i % len(kinds)],
            "ts": now - timedelta(minutes=n - i),
            "observer": "vertex.infra",
            "payload": {"value": i * 10},
        })
    return facts


class TestStoreExplorerState:
    """Test ticks-first StoreExplorerState."""

    def test_from_summary_tick_names_only(self):
        state = StoreExplorerState.from_summary(_make_fidelity_summary())
        assert state.tick_names == ["health.check"]
        assert state.cursor.item_count == 1

    def test_items_are_tick_names(self):
        state = StoreExplorerState.from_summary(_make_summary())
        assert state.items == ["podcast.huberman", "hn.top"]

    def test_selected_name(self):
        state = StoreExplorerState.from_summary(_make_fidelity_summary())
        assert state.selected_name() == "health.check"

    def test_selected_data(self):
        state = StoreExplorerState.from_summary(_make_fidelity_summary())
        data = state.selected_data()
        assert data is not None
        assert data["count"] == 5

    def test_no_kinds_field(self):
        state = StoreExplorerState.from_summary(_make_fidelity_summary())
        assert not hasattr(state, "kinds")


class TestFidelityState:
    """Test fidelity drill state transitions on StoreExplorerState."""

    def test_initial_state_has_no_fidelity(self):
        state = StoreExplorerState.from_summary(_make_fidelity_summary())
        assert state.fidelity is None
        assert state.focus == "list"

    def test_selection_is_always_tick(self):
        state = StoreExplorerState.from_summary(_make_fidelity_summary())
        # First item is a tick (no facts in the list anymore)
        assert state.selected_name() == "health.check"

    def test_drill_into_fidelity(self):
        state = StoreExplorerState.from_summary(_make_fidelity_summary())

        facts = _make_fake_facts(8)
        tick_info = state.summary["ticks"]["names"]["health.check"]
        fid = FidelityState(
            facts=facts,
            tick_name="health.check",
            since=tick_info["latest_since"],
            until=tick_info["latest_ts"],
            cursor=ListState().with_count(len(facts)),
        )
        state = replace(state, focus="fidelity", fidelity=fid)

        assert state.fidelity is not None
        assert len(state.fidelity.facts) == 8
        assert state.fidelity.tick_name == "health.check"
        assert state.fidelity.cursor.item_count == 8

    def test_toggle_filter_on(self):
        facts = _make_fake_facts(6)
        fid = FidelityState(
            facts=facts,
            tick_name="health.check",
            since=1000.0,
            until=2000.0,
            cursor=ListState().with_count(len(facts)),
        )

        # Toggle to filtered (cpu.metric — kind at cursor 0)
        filtered = [f for f in facts if f["kind"] == "cpu.metric"]
        fid = replace(
            fid,
            facts=filtered,
            filtered=True,
            filter_kind="cpu.metric",
            cursor=ListState().with_count(len(filtered)),
        )

        assert fid.filtered is True
        assert fid.filter_kind == "cpu.metric"
        assert all(f["kind"] == "cpu.metric" for f in fid.facts)

    def test_toggle_filter_off(self):
        all_facts = _make_fake_facts(6)
        filtered = [f for f in all_facts if f["kind"] == "cpu.metric"]

        fid = FidelityState(
            facts=filtered,
            tick_name="health.check",
            since=1000.0,
            until=2000.0,
            cursor=ListState().with_count(len(filtered)),
            filtered=True,
            filter_kind="cpu.metric",
        )

        # Toggle back to all
        fid = replace(
            fid,
            facts=all_facts,
            filtered=False,
            filter_kind=None,
            cursor=ListState().with_count(len(all_facts)),
        )

        assert fid.filtered is False
        assert fid.filter_kind is None
        assert len(fid.facts) == 6

    def test_drill_out_clears_fidelity(self):
        state = StoreExplorerState.from_summary(_make_fidelity_summary())
        facts = _make_fake_facts(3)
        fid = FidelityState(
            facts=facts,
            tick_name="health.check",
            since=1000.0,
            until=2000.0,
            cursor=ListState().with_count(len(facts)),
        )
        state = replace(state, focus="fidelity", fidelity=fid)

        # Pop back
        state = replace(state, focus="list", fidelity=None)

        assert state.focus == "list"
        assert state.fidelity is None

    def test_fidelity_cursor_navigation(self):
        facts = _make_fake_facts(5)
        fid = FidelityState(
            facts=facts,
            tick_name="health.check",
            since=1000.0,
            until=2000.0,
            cursor=ListState().with_count(5),
        )

        # Move down
        cursor = fid.cursor.move_down()
        assert cursor.selected == 1
        cursor = cursor.move_down()
        assert cursor.selected == 2

        # Move up
        cursor = cursor.move_up()
        assert cursor.selected == 1

        # Clamp at bounds
        at_top = ListState().with_count(5).move_to(0).move_up()
        assert at_top.selected == 0
        at_bottom = ListState().with_count(5).move_to(4).move_down()
        assert at_bottom.selected == 4


class TestPayloadOneLiner:
    def test_dict_payload(self):
        result = _payload_one_liner({"cpu": 85, "mem": 1024}, 60)
        assert "cpu=85" in result
        assert "mem=1024" in result

    def test_list_payload(self):
        result = _payload_one_liner([1, 2, 3], 60)
        assert "3 items" in result

    def test_string_truncation(self):
        payload = {"title": "A very long string that should be truncated for display"}
        result = _payload_one_liner(payload, 60)
        assert "\u2026" in result  # ellipsis in truncated value

    def test_max_width_truncation(self):
        payload = {"a": 1, "b": 2, "c": 3, "d": 4, "e": 5, "f": 6}
        result = _payload_one_liner(payload, 20)
        assert len(result) <= 20

    def test_none_payload(self):
        result = _payload_one_liner(None, 60)
        assert result == ""
