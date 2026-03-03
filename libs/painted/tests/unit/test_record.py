"""Tests for record rendering primitives (record_line, record_timeline, record_map)."""

from __future__ import annotations

from datetime import datetime, timezone, timedelta

from painted import Block, Style, Zoom
from painted.views import (
    AttentionFn,
    GutterFn,
    PayloadLens,
    apply_attention,
    apply_gutter,
    attention_blocked,
    attention_novelty,
    attention_relevance,
    attention_staleness,
    gutter_freshness,
    gutter_lifecycle,
    gutter_pass_fail,
    record_line,
    record_line_composed,
    record_map,
    record_timeline,
)
from tests.helpers import block_to_text

_BASE = datetime(2025, 1, 15, 10, 0, 0, tzinfo=timezone.utc)


def _ts(hours: float = 0, days: int = 0) -> datetime:
    return _BASE + timedelta(hours=hours, days=days)


# ---------------------------------------------------------------------------
# record_line
# ---------------------------------------------------------------------------


class TestRecordLineZoom:
    """record_line across zoom levels."""

    def test_minimal_no_timestamp(self):
        """MINIMAL omits timestamp and label."""
        block = record_line(_ts(), "decision", {"topic": "SQLite"}, Zoom.MINIMAL, 40)
        text = block_to_text(block)
        assert "10:00" not in text
        assert "[decision]" not in text
        assert "SQLite" in text

    def test_summary_has_timestamp_and_label(self):
        """SUMMARY includes HH:MM and [kind]."""
        block = record_line(_ts(), "decision", {"topic": "SQLite"}, Zoom.SUMMARY, 60)
        text = block_to_text(block)
        assert "10:00" in text
        assert "decision" in text
        assert "SQLite" in text

    def test_detailed_shows_continuation_lines(self):
        """DETAILED shows secondary fields as continuation lines."""
        payload = {
            "topic": "SQLite",
            "message": "Chose SQLite over filesystem for atomic writes and query support",
        }
        block = record_line(_ts(), "decision", payload, Zoom.DETAILED, 80)
        text = block_to_text(block)
        assert block.height > 1
        assert "message:" in text

    def test_full_has_iso_timestamp(self):
        """FULL shows ISO timestamp."""
        block = record_line(_ts(), "decision", {"topic": "X"}, Zoom.FULL, 80)
        text = block_to_text(block)
        assert "2025-01-15T10:00:00Z" in text

    def test_full_shows_all_fields(self):
        """FULL shows every payload field."""
        payload = {"topic": "SQLite", "message": "yes", "author": "me"}
        block = record_line(_ts(), "decision", payload, Zoom.FULL, 80)
        text = block_to_text(block)
        assert "topic:" in text
        assert "message:" in text
        assert "author:" in text

    def test_full_shows_all_fields(self):
        """FULL zoom shows all fields (all lines, constrained to width)."""
        payload = {"output": "some output", "status": "failed", "extra": "data"}
        block = record_line(_ts(), "task", payload, Zoom.FULL, 80)
        text = block_to_text(block)
        assert "output:" in text
        assert "status:" in text
        assert "extra:" in text


class TestRecordLinePayloadLens:
    """record_line with payload_lens."""

    def test_lens_overrides_content(self):
        """Custom lens replaces default content."""

        def my_lens(kind: str, payload: dict, zoom: Zoom) -> str:
            return "CUSTOM"

        block = record_line(_ts(), "task", {"name": "x"}, Zoom.SUMMARY, 60, payload_lens=my_lens)
        text = block_to_text(block)
        assert "CUSTOM" in text

    def test_lens_returning_block(self):
        """Lens can return a Block instead of str."""

        def block_lens(kind: str, payload: dict, zoom: Zoom) -> Block:
            return Block.text("BLOCK_CONTENT", Style())

        block = record_line(_ts(), "task", {"name": "x"}, Zoom.SUMMARY, 60, payload_lens=block_lens)
        text = block_to_text(block)
        assert "BLOCK_CONTENT" in text

    def test_lens_at_minimal(self):
        """Lens works at MINIMAL zoom (string result only)."""

        def my_lens(kind: str, payload: dict, zoom: Zoom) -> str:
            return "MINI"

        block = record_line(_ts(), "task", {"name": "x"}, Zoom.MINIMAL, 40, payload_lens=my_lens)
        text = block_to_text(block)
        assert "MINI" in text


class TestRecordLineWidth:
    """record_line width handling."""

    def test_truncates_long_content(self):
        """Content is truncated with ellipsis when too wide."""
        payload = {"topic": "A" * 200}
        block = record_line(_ts(), "decision", payload, Zoom.SUMMARY, 40)
        text = block_to_text(block)
        assert "…" in text

    def test_minimal_respects_width(self):
        """MINIMAL respects width parameter."""
        block = record_line(_ts(), "task", {"name": "x"}, Zoom.MINIMAL, 20)
        assert block.width == 20

    def test_wide_char_kind_renders(self):
        """Kind name with multi-byte chars renders correctly at DETAILED."""
        block = record_line(
            _ts(),
            "エラー",
            {"message": "test error"},
            Zoom.DETAILED,
            80,
        )
        text = block_to_text(block)
        assert "エ" in text
        assert "message:" in text
        lines = text.strip().split("\n")
        assert len(lines) > 1, "DETAILED should have continuation lines"

    def test_shallow_continuation_indent(self):
        """Continuation lines use shallow 2-char indent, not deep column alignment."""
        payload = {
            "topic": "SQLite",
            "message": "Chose SQLite over filesystem for atomic writes and query support",
        }
        block = record_line(_ts(), "decision", payload, Zoom.DETAILED, 80)
        text = block_to_text(block)
        lines = text.strip().split("\n")
        assert len(lines) > 1
        continuation = lines[1]
        leading_spaces = len(continuation) - len(continuation.lstrip())
        # Shallow indent: 2 spaces (gutter rail provides visual continuity)
        assert leading_spaces == 2

    def test_block_lens_constrained_to_content_width(self):
        """Block from PayloadLens is truncated to content_width at SUMMARY."""

        def wide_lens(kind: str, payload: dict, zoom: Zoom) -> Block:
            return Block.text("X" * 200, Style())

        block = record_line(_ts(), "task", {"name": "x"}, Zoom.SUMMARY, 40, payload_lens=wide_lens)
        # Total block should not exceed requested width
        assert block.width <= 40


class TestRecordLineKindSummary:
    """Default payload summary for different kinds."""

    def test_decision_combines_topic_and_message(self):
        block = record_line(
            _ts(),
            "decision",
            {"topic": "SQLite", "message": "good choice"},
            Zoom.SUMMARY,
            80,
        )
        text = block_to_text(block)
        assert "SQLite: good choice" in text

    def test_thread_shows_name_status_summary(self):
        block = record_line(
            _ts(),
            "thread",
            {"name": "routing", "status": "active", "summary": "Design it"},
            Zoom.SUMMARY,
            80,
        )
        text = block_to_text(block)
        assert "routing" in text
        assert "[active]" in text

    def test_tick_shows_name_status_fold(self):
        block = record_line(
            _ts(),
            "tick",
            {"name": "proj", "status": "running", "fold": "3 collected"},
            Zoom.SUMMARY,
            80,
        )
        text = block_to_text(block)
        assert "proj" in text
        assert "running" in text

    def test_generic_uses_summary_keys(self):
        block = record_line(
            _ts(),
            "custom",
            {"title": "Hello World"},
            Zoom.SUMMARY,
            60,
        )
        text = block_to_text(block)
        assert "Hello World" in text

    def test_generic_fallback_to_kv(self):
        block = record_line(
            _ts(),
            "custom",
            {"x": 1, "y": 2},
            Zoom.SUMMARY,
            60,
        )
        text = block_to_text(block)
        assert "x=1" in text


# ---------------------------------------------------------------------------
# record_timeline
# ---------------------------------------------------------------------------


class TestRecordTimeline:
    """record_timeline tests."""

    def test_empty_records(self):
        block = record_timeline([], Zoom.SUMMARY, 80)
        text = block_to_text(block)
        assert "no records" in text

    def test_minimal_shows_counts(self):
        records = [
            (_ts(0), "decision", {"topic": "A"}),
            (_ts(1), "decision", {"topic": "B"}),
            (_ts(2), "task", {"name": "X"}),
        ]
        block = record_timeline(records, Zoom.MINIMAL, 80)
        text = block_to_text(block)
        assert "2 decision" in text
        assert "1 task" in text

    def test_summary_groups_by_date(self):
        records = [
            (_ts(0, days=0), "decision", {"topic": "A"}),
            (_ts(0, days=1), "task", {"name": "X"}),
        ]
        block = record_timeline(records, Zoom.SUMMARY, 80)
        text = block_to_text(block)
        assert "2025-01-15:" in text
        assert "2025-01-16:" in text

    def test_with_payload_lens(self):
        def my_lens(kind: str, payload: dict, zoom: Zoom) -> str:
            return "LENSED"

        records = [(_ts(), "task", {"name": "X"})]
        block = record_timeline(records, Zoom.SUMMARY, 80, payload_lens=my_lens)
        text = block_to_text(block)
        assert "LENSED" in text

    def test_detailed_shows_continuation_lines(self):
        """DETAILED renders records at DETAILED zoom within date groups."""
        records = [
            (
                _ts(0),
                "decision",
                {
                    "topic": "SQLite",
                    "message": "Chose SQLite over filesystem for atomic writes",
                },
            ),
        ]
        block = record_timeline(records, Zoom.DETAILED, 80)
        text = block_to_text(block)
        assert "2025-01-15:" in text
        assert "message:" in text
        assert block.height > 2  # date header + primary line + continuation

    def test_full_shows_iso_timestamps(self):
        """FULL renders records at FULL zoom within date groups."""
        records = [
            (_ts(0), "task", {"name": "X", "status": "running"}),
        ]
        block = record_timeline(records, Zoom.FULL, 80)
        text = block_to_text(block)
        assert "2025-01-15T10:00:00Z" in text

    def test_indentation_shrinks_width(self):
        """Records within date groups render at width-2 for indentation."""
        records = [(_ts(0), "decision", {"topic": "A" * 200})]
        block = record_timeline(records, Zoom.SUMMARY, 40)
        # The record_line inside gets width=38 (40-2 for indent).
        # With 2-col indent pad, total should not exceed 40.
        assert block.width <= 40

    def test_block_lens_at_detailed(self):
        """Block-returning PayloadLens works within timeline at DETAILED zoom."""

        def block_lens(kind: str, payload: dict, zoom: Zoom) -> str | Block:
            if zoom >= Zoom.DETAILED:
                return "DETAIL_LENS"
            return "SUMMARY_LENS"

        records = [(_ts(0), "task", {"name": "X"})]
        block = record_timeline(records, Zoom.DETAILED, 80, payload_lens=block_lens)
        text = block_to_text(block)
        assert "DETAIL_LENS" in text


# ---------------------------------------------------------------------------
# Gutter functions
# ---------------------------------------------------------------------------


class TestGutterLifecycle:
    """gutter_lifecycle tests."""

    def test_blocked_is_error(self):
        ch, style = gutter_lifecycle("task", {"status": "blocked"})
        assert ch == "█"

    def test_running_is_success(self):
        ch, style = gutter_lifecycle("task", {"status": "running"})
        assert ch == "│"

    def test_stalled_is_warning(self):
        ch, style = gutter_lifecycle("task", {"status": "stalled"})
        assert ch == "▐"

    def test_completed_is_success(self):
        ch, style = gutter_lifecycle("task", {"status": "completed"})
        assert ch == "│"

    def test_unknown_status_is_muted(self):
        ch, style = gutter_lifecycle("task", {"status": "unknown"})
        assert ch == "│"

    def test_no_status_is_muted(self):
        ch, style = gutter_lifecycle("task", {})
        assert ch == "│"


class TestGutterFreshness:
    """gutter_freshness tests."""

    def test_fresh_is_accent(self):
        ch, _ = gutter_freshness("task", {"_age_days": 0})
        assert ch == "│"

    def test_stale_30_plus_is_dot(self):
        ch, _ = gutter_freshness("task", {"_age_days": 31})
        assert ch == "·"

    def test_default_is_fresh(self):
        ch, _ = gutter_freshness("task", {})
        assert ch == "│"


class TestGutterPassFail:
    """gutter_pass_fail tests."""

    def test_passed_is_success(self):
        ch, _ = gutter_pass_fail("test", {"status": "passed"})
        assert ch == "│"

    def test_failed_is_error(self):
        ch, _ = gutter_pass_fail("test", {"status": "failed"})
        assert ch == "█"

    def test_warning_is_warning(self):
        ch, _ = gutter_pass_fail("test", {"status": "warning"})
        assert ch == "▐"


# ---------------------------------------------------------------------------
# Attention functions
# ---------------------------------------------------------------------------


class TestAttentionStaleness:
    """attention_staleness tests."""

    def test_fresh_is_high(self):
        assert attention_staleness("x", {"_age_days": 0}) == 1.0

    def test_week_old_is_medium(self):
        assert attention_staleness("x", {"_age_days": 5}) == 0.7

    def test_month_old_is_low(self):
        assert attention_staleness("x", {"_age_days": 20}) == 0.3

    def test_ancient_is_minimal(self):
        assert attention_staleness("x", {"_age_days": 365}) == 0.1


class TestAttentionNovelty:
    """attention_novelty tests."""

    def test_first_occurrence_is_high(self):
        assert attention_novelty("x", {"occurrences": 1}) == 1.0

    def test_repeated_is_low(self):
        assert attention_novelty("x", {"occurrences": 50}) == 0.2

    def test_default_is_high(self):
        assert attention_novelty("x", {}) == 1.0


class TestAttentionBlocked:
    """attention_blocked tests."""

    def test_blocked_is_max(self):
        assert attention_blocked("x", {"status": "blocked"}) == 1.0

    def test_completed_is_low(self):
        assert attention_blocked("x", {"status": "completed"}) == 0.2

    def test_running_is_medium(self):
        assert attention_blocked("x", {"status": "running"}) == 0.5


class TestAttentionRelevance:
    """attention_relevance tests."""

    def test_reads_relevance(self):
        assert attention_relevance("x", {"_relevance": 0.95}) == 0.95

    def test_default_is_half(self):
        assert attention_relevance("x", {}) == 0.5


# ---------------------------------------------------------------------------
# apply_gutter / apply_attention
# ---------------------------------------------------------------------------


class TestApplyGutter:
    """apply_gutter tests."""

    def test_prepends_gutter(self):
        inner = Block.text("content", Style())
        result = apply_gutter(inner, "task", {"status": "running"}, gutter_lifecycle)
        text = block_to_text(result)
        assert "│" in text
        assert "content" in text

    def test_gutter_adds_width(self):
        inner = Block.text("hello", Style())
        result = apply_gutter(inner, "task", {}, gutter_lifecycle)
        assert result.width > inner.width

    def test_gutter_continuous_on_multiline(self):
        """Gutter rail covers every line, not just the first."""
        from painted.compose import join_vertical

        inner = join_vertical(
            Block.text("line1", Style()),
            Block.text("line2", Style()),
            Block.text("line3", Style()),
        )
        result = apply_gutter(inner, "task", {"status": "blocked"}, gutter_lifecycle)
        text = block_to_text(result)
        lines = text.strip().split("\n")
        assert len(lines) == 3
        # First line: full block █, continuation: half block ▐
        assert lines[0].startswith("█")
        assert lines[1].startswith("▐")
        assert lines[2].startswith("▐")

    def test_gutter_step_pass_stays_thin(self):
        """Pass/success gutter stays │ on continuation lines (baseline)."""
        from painted.compose import join_vertical

        inner = join_vertical(
            Block.text("line1", Style()),
            Block.text("line2", Style()),
        )
        result = apply_gutter(inner, "test", {"status": "passed"}, gutter_pass_fail)
        text = block_to_text(result)
        lines = text.strip().split("\n")
        assert lines[0].startswith("│")
        assert lines[1].startswith("│")

    def test_gutter_step_warning(self):
        """Warning gutter: ▐ on first line, │ on continuation."""
        from painted.compose import join_vertical

        inner = join_vertical(
            Block.text("line1", Style()),
            Block.text("line2", Style()),
        )
        result = apply_gutter(inner, "test", {"status": "warning"}, gutter_pass_fail)
        text = block_to_text(result)
        lines = text.strip().split("\n")
        assert lines[0].startswith("▐")
        assert lines[1].startswith("│")


class TestApplyAttention:
    """apply_attention tests."""

    def test_high_attention_has_marker(self):
        inner = Block.text("content", Style())
        result = apply_attention(inner, "decision", {}, lambda k, p: 1.0, width=60)
        text = block_to_text(result)
        assert "◆" in text

    def test_low_attention_collapses(self):
        inner = Block.text("content that is very long", Style())
        result = apply_attention(
            inner,
            "tick",
            {"name": "heartbeat"},
            lambda k, p: 0.1,
            width=60,
        )
        text = block_to_text(result)
        assert "·" in text  # collapsed marker

    def test_medium_attention_no_marker(self):
        inner = Block.text("content", Style())
        result = apply_attention(inner, "task", {}, lambda k, p: 0.5, width=60)
        text = block_to_text(result)
        assert "◆" not in text
        assert "·" not in text

    def test_low_attention_respects_width(self):
        """Collapsed one-liner should have the specified width."""
        inner = Block.text("content", Style())
        result = apply_attention(
            inner,
            "tick",
            {"name": "heartbeat"},
            lambda k, p: 0.1,
            width=50,
        )
        assert result.width == 50


# ---------------------------------------------------------------------------
# record_line_composed
# ---------------------------------------------------------------------------


class TestRecordLineComposed:
    """record_line_composed tests."""

    def test_no_modifiers_same_as_record_line(self):
        """Without modifiers, equivalent to record_line."""
        plain = record_line(_ts(), "task", {"name": "X"}, Zoom.SUMMARY, 60)
        composed = record_line_composed(_ts(), "task", {"name": "X"}, Zoom.SUMMARY, 60)
        assert block_to_text(plain) == block_to_text(composed)

    def test_with_gutter(self):
        block = record_line_composed(
            _ts(),
            "task",
            {"name": "X", "status": "blocked"},
            Zoom.SUMMARY,
            60,
            gutter_fn=gutter_lifecycle,
        )
        text = block_to_text(block)
        assert "█" in text  # blocked gutter

    def test_with_attention(self):
        block = record_line_composed(
            _ts(),
            "decision",
            {"topic": "new"},
            Zoom.SUMMARY,
            60,
            attention_fn=lambda k, p: 1.0,
        )
        text = block_to_text(block)
        assert "◆" in text

    def test_with_gutter_and_attention(self):
        block = record_line_composed(
            _ts(),
            "task",
            {"name": "X", "status": "blocked"},
            Zoom.SUMMARY,
            80,
            gutter_fn=gutter_lifecycle,
            attention_fn=attention_blocked,
        )
        text = block_to_text(block)
        # blocked = high attention (1.0) → ◆ marker
        assert "◆" in text
        # blocked = error gutter → █
        assert "█" in text


# ---------------------------------------------------------------------------
# record_map
# ---------------------------------------------------------------------------


class TestRecordMap:
    """record_map tests."""

    def test_empty_records(self):
        block = record_map([], Zoom.SUMMARY, 80)
        text = block_to_text(block)
        assert "no records" in text

    def test_minimal_shows_group_counts(self):
        records = [
            (_ts(0), "decision", {"topic": "A"}),
            (_ts(1), "decision", {"topic": "B"}),
            (_ts(2), "task", {"name": "X"}),
        ]
        block = record_map(records, Zoom.MINIMAL, 80)
        text = block_to_text(block)
        assert "decision (2)" in text
        assert "task (1)" in text

    def test_summary_shows_group_headers(self):
        records = [
            (_ts(0), "decision", {"topic": "A"}),
            (_ts(1), "task", {"name": "X"}),
        ]
        block = record_map(records, Zoom.SUMMARY, 80)
        text = block_to_text(block)
        assert "decision" in text
        assert "task" in text

    def test_custom_group_key(self):
        records = [
            (_ts(0), "decision", {"topic": "arch/doc"}),
            (_ts(1), "decision", {"topic": "arch/api"}),
            (_ts(2), "decision", {"topic": "design/x"}),
        ]
        block = record_map(
            records,
            Zoom.MINIMAL,
            80,
            group_key=lambda k, p: p.get("topic", k).split("/")[0],
        )
        text = block_to_text(block)
        assert "arch (2)" in text
        assert "design (1)" in text

    def test_hierarchical_keys(self):
        records = [
            (_ts(0), "decision", {"topic": "arch/doc"}),
            (_ts(1), "decision", {"topic": "arch/api"}),
        ]
        block = record_map(
            records,
            Zoom.SUMMARY,
            80,
            group_key=lambda k, p: p.get("topic", k),
        )
        text = block_to_text(block)
        # Should have top-level "arch" header with sub-groups
        assert "arch" in text

    def test_sort_groups_count(self):
        records = [
            (_ts(0), "a", {}),
            (_ts(1), "b", {}),
            (_ts(2), "b", {}),
            (_ts(3), "b", {}),
        ]
        block = record_map(records, Zoom.MINIMAL, 80, sort_groups="count")
        text = block_to_text(block)
        # "b" has 3 records, should appear first
        b_pos = text.find("b (3)")
        a_pos = text.find("a (1)")
        assert b_pos < a_pos

    def test_with_modifiers(self):
        records = [
            (_ts(0), "task", {"name": "X", "status": "blocked"}),
        ]
        block = record_map(
            records,
            Zoom.SUMMARY,
            80,
            gutter_fn=gutter_lifecycle,
        )
        text = block_to_text(block)
        assert "█" in text  # blocked gutter visible


# ---------------------------------------------------------------------------
# Protocol conformance
# ---------------------------------------------------------------------------


class TestProtocols:
    """Verify that concrete functions satisfy their protocols."""

    def test_gutter_lifecycle_is_gutter_fn(self):
        fn: GutterFn = gutter_lifecycle
        ch, style = fn("task", {"status": "running"})
        assert isinstance(ch, str)

    def test_gutter_freshness_is_gutter_fn(self):
        fn: GutterFn = gutter_freshness
        ch, style = fn("task", {"_age_days": 5})
        assert isinstance(ch, str)

    def test_gutter_pass_fail_is_gutter_fn(self):
        fn: GutterFn = gutter_pass_fail
        ch, style = fn("test", {"status": "passed"})
        assert isinstance(ch, str)

    def test_attention_staleness_is_attention_fn(self):
        fn: AttentionFn = attention_staleness
        assert isinstance(fn("x", {"_age_days": 1}), float)

    def test_attention_novelty_is_attention_fn(self):
        fn: AttentionFn = attention_novelty
        assert isinstance(fn("x", {"occurrences": 1}), float)

    def test_attention_blocked_is_attention_fn(self):
        fn: AttentionFn = attention_blocked
        assert isinstance(fn("x", {"status": "blocked"}), float)

    def test_attention_relevance_is_attention_fn(self):
        fn: AttentionFn = attention_relevance
        assert isinstance(fn("x", {"_relevance": 0.5}), float)
