"""Tests for store_view lens rendering and fidelity drill."""

from dataclasses import replace
from datetime import datetime, timezone, timedelta

import pytest

from cells import Zoom
from cells.components.list_view import ListState
from loops.lenses.store import store_view, _relative_time
from loops.tui.store_app import FidelityState, StoreExplorerState, _payload_one_liner


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
                },
                "hn.top": {
                    "count": 7,
                    "earliest": now - timedelta(days=10),
                    "latest": now - timedelta(minutes=45),
                    "latest_payload": {"story_count": 30, "top_score": 500},
                },
            },
        },
        "freshness": freshness or hour_ago,
    }


def _block_to_text(block) -> str:
    """Extract text content from a block for testing."""
    result = []
    for y in range(block.height):
        row = block.row(y)
        line = "".join(cell.char for cell in row)
        result.append(line)
    return "\n".join(result)


class TestMinimal:
    def test_shows_counts(self):
        data = _make_summary()
        block = store_view(data, Zoom.MINIMAL, 80)
        text = _block_to_text(block)
        assert "3 kinds" in text
        assert "6.5k facts" in text or "6462" in text or "6.4k" in text
        assert "15 ticks" in text

    def test_shows_freshness(self):
        data = _make_summary()
        block = store_view(data, Zoom.MINIMAL, 80)
        text = _block_to_text(block)
        assert "fresh" in text
        assert "ago" in text

    def test_non_empty(self):
        data = _make_summary()
        block = store_view(data, Zoom.MINIMAL, 80)
        assert block.height >= 1


class TestSummary:
    def test_shows_facts_header(self):
        data = _make_summary()
        block = store_view(data, Zoom.SUMMARY, 80)
        text = _block_to_text(block)
        assert "Facts" in text

    def test_shows_ticks_header(self):
        data = _make_summary()
        block = store_view(data, Zoom.SUMMARY, 80)
        text = _block_to_text(block)
        assert "Ticks" in text

    def test_shows_kind_names(self):
        data = _make_summary()
        block = store_view(data, Zoom.SUMMARY, 80)
        text = _block_to_text(block)
        assert "hn.story" in text
        assert "rss.item" in text

    def test_non_empty(self):
        data = _make_summary()
        block = store_view(data, Zoom.SUMMARY, 80)
        assert block.height >= 3


class TestDetailed:
    def test_shows_tick_sections(self):
        data = _make_summary()
        block = store_view(data, Zoom.DETAILED, 80)
        text = _block_to_text(block)
        assert "podcast.huberman" in text
        assert "hn.top" in text

    def test_shows_tick_counts(self):
        data = _make_summary()
        block = store_view(data, Zoom.DETAILED, 80)
        text = _block_to_text(block)
        assert "8 ticks" in text

    def test_non_empty(self):
        data = _make_summary()
        block = store_view(data, Zoom.DETAILED, 80)
        assert block.height >= 5


class TestFull:
    def test_shows_tick_payloads(self):
        data = _make_summary()
        block = store_view(data, Zoom.FULL, 80)
        text = _block_to_text(block)
        assert "episode_count" in text or "story_count" in text

    def test_non_empty(self):
        data = _make_summary()
        block = store_view(data, Zoom.FULL, 80)
        assert block.height >= 5


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


class TestFidelityState:
    """Test fidelity drill state transitions on StoreExplorerState."""

    def test_initial_state_has_no_fidelity(self):
        state = StoreExplorerState.from_summary(_make_fidelity_summary())
        assert state.fidelity is None
        assert state.focus == "list"

    def test_selected_is_tick(self):
        state = StoreExplorerState.from_summary(_make_fidelity_summary())
        # First items are facts, last is tick
        assert not state.selected_is_tick()  # cursor starts at 0 = first fact kind
        # Move cursor past fact kinds to tick
        tick_idx = len(state.kinds)
        state = replace(state, cursor=state.cursor.move_to(tick_idx))
        assert state.selected_is_tick()
        assert state.selected_tick_name() == "health.check"

    def test_drill_into_fidelity(self):
        state = StoreExplorerState.from_summary(_make_fidelity_summary())
        tick_idx = len(state.kinds)
        state = replace(state, cursor=state.cursor.move_to(tick_idx))

        facts = _make_fake_facts(8)
        tick_info = state.summary["ticks"]["names"]["health.check"]
        fid = FidelityState(
            facts=facts,
            tick_name="health.check",
            since=tick_info["latest_since"],
            until=tick_info["latest_ts"],
            cursor=ListState(item_count=len(facts)),
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
            cursor=ListState(item_count=len(facts)),
        )

        # Toggle to filtered (cpu.metric — kind at cursor 0)
        filtered = [f for f in facts if f["kind"] == "cpu.metric"]
        fid = replace(
            fid,
            facts=filtered,
            filtered=True,
            filter_kind="cpu.metric",
            cursor=ListState(item_count=len(filtered)),
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
            cursor=ListState(item_count=len(filtered)),
            filtered=True,
            filter_kind="cpu.metric",
        )

        # Toggle back to all
        fid = replace(
            fid,
            facts=all_facts,
            filtered=False,
            filter_kind=None,
            cursor=ListState(item_count=len(all_facts)),
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
            cursor=ListState(item_count=len(facts)),
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
            cursor=ListState(item_count=5),
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
        at_top = ListState(item_count=5, selected=0).move_up()
        assert at_top.selected == 0
        at_bottom = ListState(item_count=5, selected=4).move_down()
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
