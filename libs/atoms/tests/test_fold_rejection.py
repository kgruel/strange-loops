"""R2 off-type rule: numeric folds skip + count, never crash or coerce.

decision:design/fold-off-type-skip-with-counter — an off-type value in a
numeric fold (Sum/Avg/Min/Max/TopN) or a missing _ts in Latest is skipped
without mutating the numeric state, and recorded in a deterministic
`{target}_rejected` counter. Bool is off-type (Python bool-is-int would
silently fold true as 1). Errors-as-state: visible in every snapshot,
deterministic under replay.
"""

from __future__ import annotations

from atoms.engine import (
    _make_avg,
    _make_latest,
    _make_max,
    _make_min,
    _make_sum,
    _make_top_n,
)


class TestSumRejection:
    def test_string_skipped_and_counted(self):
        fold = _make_sum("total", "v")
        state = {"total": 10}
        fold(state, {"v": "high"})  # was: TypeError mid-replay
        assert state["total"] == 10
        assert state["total_rejected"] == 1

    def test_bool_is_off_type(self):
        fold = _make_sum("total", "v")
        state = {}
        fold(state, {"v": True})  # was: sum(true) == 1
        assert "total" not in state
        assert state["total_rejected"] == 1

    def test_missing_field_is_silent_not_rejected(self):
        fold = _make_sum("total", "v")
        state = {}
        fold(state, {"other": 1})
        assert state == {}

    def test_numbers_still_fold(self):
        fold = _make_sum("total", "v")
        state = {}
        fold(state, {"v": 2})
        fold(state, {"v": 3.5})
        assert state["total"] == 5.5
        assert "total_rejected" not in state


class TestAvgRejection:
    def test_rejected_value_does_not_bump_denominator(self):
        fold = _make_avg("avg", "v")
        state = {}
        fold(state, {"v": 10})
        fold(state, {"v": True})
        fold(state, {"v": "n/a"})
        fold(state, {"v": 20})
        assert state["avg"] == 15.0
        assert state["avg_count"] == 2
        assert state["avg_rejected"] == 2


class TestMinMaxRejection:
    def test_bool_no_longer_wins_min(self):
        fold = _make_min("lo", "v")
        state = {}
        fold(state, {"v": 5})
        fold(state, {"v": True})  # was: min(5, True) == True
        assert state["lo"] == 5
        assert state["lo_rejected"] == 1

    def test_string_vs_int_no_longer_raises(self):
        fold = _make_max("hi", "v")
        state = {}
        fold(state, {"v": 5})
        fold(state, {"v": "low"})  # was: TypeError
        assert state["hi"] == 5
        assert state["hi_rejected"] == 1


class TestTopNRejection:
    def test_off_type_by_value_rejected(self):
        fold = _make_top_n("top", "name", "score", 3, desc=True)
        state = {"top": {}}
        fold(state, {"name": "a", "score": 9})
        fold(state, {"name": "b", "score": "best"})
        assert set(state["top"]) == {"a"}
        assert state["top_rejected"] == 1


class TestLatestRejection:
    def test_missing_ts_rejected_never_wall_clock(self):
        fold = _make_latest("last_seen")
        state = {}
        fold(state, {})  # was: state["last_seen"] = time.time()
        assert "last_seen" not in state
        assert state["last_seen_rejected"] == 1

    def test_ts_folds(self):
        fold = _make_latest("last_seen")
        state = {}
        fold(state, {"_ts": 1234567890.5})
        assert state["last_seen"] == 1234567890.5

    def test_replay_determinism(self):
        """Folding the same payloads twice yields identical state — the
        property time.time() violated."""
        payloads = [{"_ts": 100.0}, {}, {"_ts": 200.0}]
        states = []
        for _ in range(2):
            fold = _make_latest("last")
            state: dict = {}
            for p in payloads:
                fold(state, p)
            states.append(state)
        assert states[0] == states[1]
