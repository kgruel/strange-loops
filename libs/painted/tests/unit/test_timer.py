"""Tests for FrameTimer: per-phase timing and profiling."""

from __future__ import annotations

import json
import time
from pathlib import Path

from painted._timer import FrameRecord, FrameTimer


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _run_frame(
    timer: FrameTimer, phases: dict[str, float] | None = None, meta: dict[str, object] | None = None
) -> None:
    """Run a complete frame with optional simulated phase durations."""
    timer.begin_frame()
    for name, _duration in (phases or {}).items():
        with timer.phase(name):
            pass  # real timing — duration is non-deterministic but > 0
    for key, value in (meta or {}).items():
        timer.set_meta(key, value)
    timer.end_frame()


# ---------------------------------------------------------------------------
# FrameRecord
# ---------------------------------------------------------------------------


class TestFrameRecord:
    """FrameRecord defaults and structure."""

    def test_defaults(self) -> None:
        """Empty FrameRecord has zero values and empty dicts."""
        rec = FrameRecord()
        assert rec.phases == {}
        assert rec.meta == {}
        assert rec.total == 0.0
        assert rec.timestamp == 0.0

    def test_mutable_fields(self) -> None:
        """Phases and meta can be populated after creation."""
        rec = FrameRecord()
        rec.phases["render"] = 1.5
        rec.meta["items"] = 42
        assert rec.phases["render"] == 1.5
        assert rec.meta["items"] == 42


# ---------------------------------------------------------------------------
# FrameTimer — creation and initial state
# ---------------------------------------------------------------------------


class TestFrameTimerInit:
    """FrameTimer construction and default state."""

    def test_initial_state(self) -> None:
        """Fresh timer has no history and no current frame."""
        timer = FrameTimer()
        assert timer.last() is None
        assert timer.avg_total() == 0.0
        assert timer.phase_names() == []

    def test_custom_history_size(self) -> None:
        """History parameter controls the ring buffer size."""
        timer = FrameTimer(history=3)
        for _ in range(5):
            _run_frame(timer)
        # Only the last 3 frames should remain
        assert len(timer._history) == 3

    def test_profile_flag_disabled(self) -> None:
        """Without profile=True, log stays empty even after frames."""
        timer = FrameTimer(profile=False)
        _run_frame(timer)
        assert timer._log == []

    def test_profile_flag_enabled(self) -> None:
        """With profile=True, log accumulates all frames."""
        timer = FrameTimer(profile=True)
        _run_frame(timer)
        _run_frame(timer)
        assert len(timer._log) == 2


# ---------------------------------------------------------------------------
# begin_frame / end_frame lifecycle
# ---------------------------------------------------------------------------


class TestFrameLifecycle:
    """Frame begin/end bookkeeping."""

    def test_end_frame_records_total(self) -> None:
        """Total ms is set when a frame ends."""
        timer = FrameTimer()
        timer.begin_frame()
        timer.end_frame()
        rec = timer.last()
        assert rec is not None
        assert rec.total >= 0.0

    def test_end_frame_clears_current(self) -> None:
        """After end_frame, no current frame is active."""
        timer = FrameTimer()
        timer.begin_frame()
        timer.end_frame()
        assert timer._current is None

    def test_end_frame_without_begin_is_noop(self) -> None:
        """Calling end_frame before begin_frame does nothing."""
        timer = FrameTimer()
        timer.end_frame()  # should not raise
        assert timer.last() is None

    def test_begin_frame_sets_timestamp(self) -> None:
        """begin_frame records the wall-clock timestamp."""
        timer = FrameTimer()
        before = time.time()
        timer.begin_frame()
        timer.end_frame()
        rec = timer.last()
        assert rec is not None
        assert rec.timestamp >= before


# ---------------------------------------------------------------------------
# phase context manager
# ---------------------------------------------------------------------------


class TestPhase:
    """Phase timing via context manager."""

    def test_phase_records_elapsed(self) -> None:
        """A phase records a non-negative elapsed time."""
        timer = FrameTimer()
        timer.begin_frame()
        with timer.phase("render"):
            pass
        timer.end_frame()
        rec = timer.last()
        assert rec is not None
        assert "render" in rec.phases
        assert rec.phases["render"] >= 0.0

    def test_multiple_phases(self) -> None:
        """Multiple phases are all recorded in the same frame."""
        timer = FrameTimer()
        timer.begin_frame()
        with timer.phase("fetch"):
            pass
        with timer.phase("render"):
            pass
        timer.end_frame()
        rec = timer.last()
        assert rec is not None
        assert set(rec.phases.keys()) == {"fetch", "render"}

    def test_phase_without_current_frame(self) -> None:
        """Phase outside a frame does not raise."""
        timer = FrameTimer()
        with timer.phase("orphan"):
            pass
        # No frame recorded, so nothing to check except no error
        assert timer.last() is None


# ---------------------------------------------------------------------------
# set_meta
# ---------------------------------------------------------------------------


class TestSetMeta:
    """Metadata attachment to frames."""

    def test_meta_attached_to_frame(self) -> None:
        """set_meta stores data on the current frame."""
        timer = FrameTimer()
        timer.begin_frame()
        timer.set_meta("items", 100)
        timer.end_frame()
        rec = timer.last()
        assert rec is not None
        assert rec.meta["items"] == 100

    def test_meta_without_current_frame(self) -> None:
        """set_meta outside a frame is a no-op."""
        timer = FrameTimer()
        timer.set_meta("orphan", 42)  # should not raise
        assert timer.last() is None


# ---------------------------------------------------------------------------
# last / avg / max / avg_total / phase_names
# ---------------------------------------------------------------------------


class TestAggregations:
    """Statistical queries over frame history."""

    def test_last_returns_most_recent(self) -> None:
        """last() returns the most recently ended frame."""
        timer = FrameTimer()
        _run_frame(timer, phases={"a": 0})
        _run_frame(timer, phases={"b": 0})
        rec = timer.last()
        assert rec is not None
        assert "b" in rec.phases

    def test_avg_empty_history(self) -> None:
        """avg() returns 0.0 when no frames exist."""
        timer = FrameTimer()
        assert timer.avg("render") == 0.0

    def test_avg_with_frames(self) -> None:
        """avg() computes mean across history, defaulting missing phases to 0."""
        timer = FrameTimer()
        # Manually build controlled records
        timer._history.append(FrameRecord(phases={"render": 10.0}, total=10.0))
        timer._history.append(FrameRecord(phases={"render": 20.0}, total=20.0))
        assert timer.avg("render") == 15.0
        # Missing phase defaults to 0 in the average
        assert timer.avg("missing") == 0.0

    def test_max_empty_history(self) -> None:
        """max() returns 0.0 when no frames exist."""
        timer = FrameTimer()
        assert timer.max("render") == 0.0

    def test_max_with_frames(self) -> None:
        """max() returns the highest value for a phase."""
        timer = FrameTimer()
        timer._history.append(FrameRecord(phases={"render": 10.0}))
        timer._history.append(FrameRecord(phases={"render": 30.0}))
        timer._history.append(FrameRecord(phases={"render": 20.0}))
        assert timer.max("render") == 30.0

    def test_avg_total(self) -> None:
        """avg_total() averages frame total times."""
        timer = FrameTimer()
        timer._history.append(FrameRecord(total=10.0))
        timer._history.append(FrameRecord(total=20.0))
        assert timer.avg_total() == 15.0

    def test_phase_names_from_last_frame(self) -> None:
        """phase_names() returns keys from the most recent frame."""
        timer = FrameTimer()
        _run_frame(timer, phases={"fetch": 0, "render": 0})
        names = timer.phase_names()
        assert "fetch" in names
        assert "render" in names

    def test_phase_names_empty(self) -> None:
        """phase_names() returns empty list with no history."""
        timer = FrameTimer()
        assert timer.phase_names() == []


# ---------------------------------------------------------------------------
# dump_jsonl
# ---------------------------------------------------------------------------


class TestDumpJsonl:
    """JSONL file output for profiled frames."""

    def test_dump_writes_jsonl(self, tmp_path: Path) -> None:
        """dump_jsonl writes one JSON object per line."""
        timer = FrameTimer(profile=True)
        _run_frame(timer, phases={"render": 0}, meta={"items": 5})
        _run_frame(timer, phases={"render": 0})

        out = tmp_path / "profile.jsonl"
        count = timer.dump_jsonl(out)
        assert count == 2

        lines = out.read_text().strip().split("\n")
        assert len(lines) == 2

        first = json.loads(lines[0])
        assert "t" in first
        assert "total_ms" in first
        assert "phases" in first
        assert "render" in first["phases"]
        assert "meta" in first
        assert first["meta"]["items"] == 5

    def test_dump_excludes_meta_when_empty(self, tmp_path: Path) -> None:
        """Frames without metadata omit the meta key."""
        timer = FrameTimer(profile=True)
        _run_frame(timer, phases={"x": 0})

        out = tmp_path / "profile.jsonl"
        timer.dump_jsonl(out)

        obj = json.loads(out.read_text().strip())
        assert "meta" not in obj

    def test_dump_empty_log(self, tmp_path: Path) -> None:
        """dump_jsonl with no logged frames writes an empty file."""
        timer = FrameTimer(profile=True)
        out = tmp_path / "profile.jsonl"
        count = timer.dump_jsonl(out)
        assert count == 0
        assert out.read_text() == ""

    def test_dump_without_profile_flag(self, tmp_path: Path) -> None:
        """Without profile=True, dump_jsonl writes nothing even after frames."""
        timer = FrameTimer(profile=False)
        _run_frame(timer, phases={"render": 0})
        out = tmp_path / "profile.jsonl"
        count = timer.dump_jsonl(out)
        assert count == 0

    def test_dump_rounds_values(self, tmp_path: Path) -> None:
        """Timestamps and durations are rounded in output."""
        timer = FrameTimer(profile=True)
        # Inject a controlled record
        rec = FrameRecord(
            phases={"a": 1.23456789},
            total=9.87654321,
            timestamp=1700000000.123456789,
        )
        timer._log.append(rec)

        out = tmp_path / "profile.jsonl"
        timer.dump_jsonl(out)

        obj = json.loads(out.read_text().strip())
        assert obj["t"] == 1700000000.123
        assert obj["total_ms"] == 9.88
        assert obj["phases"]["a"] == 1.23


# ---------------------------------------------------------------------------
# History ring buffer
# ---------------------------------------------------------------------------


class TestHistoryBuffer:
    """Ring buffer behavior for frame history."""

    def test_history_maxlen(self) -> None:
        """History never exceeds the configured size."""
        timer = FrameTimer(history=2)
        _run_frame(timer, phases={"a": 0})
        _run_frame(timer, phases={"b": 0})
        _run_frame(timer, phases={"c": 0})
        assert len(timer._history) == 2
        # Oldest (a) should be evicted
        phases_seen = [list(r.phases.keys())[0] for r in timer._history]
        assert phases_seen == ["b", "c"]

    def test_profile_log_not_bounded(self) -> None:
        """Profile log keeps all frames regardless of history size."""
        timer = FrameTimer(history=2, profile=True)
        for i in range(5):
            _run_frame(timer, phases={f"p{i}": 0})
        assert len(timer._history) == 2
        assert len(timer._log) == 5
