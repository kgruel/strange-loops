"""Tests for Loop — explicit fold cycle with boundary semantics."""

from datetime import datetime, timezone

from engine import Loop


NOW = datetime(2025, 6, 1, 12, 0, 0, tzinfo=timezone.utc)
EARLIER = datetime(2025, 6, 1, 11, 0, 0, tzinfo=timezone.utc)
LATER = datetime(2025, 6, 1, 13, 0, 0, tzinfo=timezone.utc)


def sum_fold(state: int, payload: dict) -> int:
    return state + payload.get("value", 0)


class TestLoopPeriodTracking:
    """Loop tracks period start for fidelity traversal."""

    def test_first_receive_sets_period_start(self):
        loop = Loop(
            name="counter",
            initial=0,
            fold=sum_fold,
        )

        # Period start is None before any receive
        assert loop._period_start is None

        # First receive sets period start
        loop.receive({"value": 10}, ts=EARLIER)
        assert loop._period_start == EARLIER

    def test_subsequent_receive_does_not_change_period_start(self):
        loop = Loop(
            name="counter",
            initial=0,
            fold=sum_fold,
        )

        loop.receive({"value": 10}, ts=EARLIER)
        loop.receive({"value": 20}, ts=NOW)
        loop.receive({"value": 30}, ts=LATER)

        # Period start remains the first timestamp
        assert loop._period_start == EARLIER

    def test_fire_includes_since_in_tick(self):
        loop = Loop(
            name="counter",
            initial=0,
            fold=sum_fold,
            reset=True,
        )

        loop.receive({"value": 10}, ts=EARLIER)
        loop.receive({"value": 20}, ts=NOW)

        tick = loop.fire(LATER, origin="test")

        assert tick.since == EARLIER
        assert tick.ts == LATER
        assert tick.payload == 30

    def test_reset_clears_period_start(self):
        loop = Loop(
            name="counter",
            initial=0,
            fold=sum_fold,
            reset=True,
        )

        loop.receive({"value": 10}, ts=EARLIER)
        tick = loop.fire(NOW, origin="test")

        # After fire with reset, period start is cleared
        assert loop._period_start is None

        # Next receive starts a new period
        loop.receive({"value": 5}, ts=LATER)
        assert loop._period_start == LATER

    def test_no_reset_preserves_period_start(self):
        loop = Loop(
            name="counter",
            initial=0,
            fold=sum_fold,
            reset=False,
        )

        loop.receive({"value": 10}, ts=EARLIER)
        tick = loop.fire(NOW, origin="test")

        # Without reset, period start is preserved
        assert loop._period_start == EARLIER

    def test_receive_without_ts_uses_now(self):
        loop = Loop(
            name="counter",
            initial=0,
            fold=sum_fold,
        )

        # receive() without ts argument defaults to now
        loop.receive({"value": 10})

        assert loop._period_start is not None
        # Should be close to current time (within a second)
        now = datetime.now(timezone.utc)
        delta = abs((now - loop._period_start).total_seconds())
        assert delta < 1.0

    def test_tick_since_enables_fidelity_query(self):
        """Tick.since + Tick.ts define a time window for Store.between()."""
        loop = Loop(
            name="counter",
            initial=0,
            fold=sum_fold,
            reset=True,
        )

        # Simulate a period
        loop.receive({"value": 10}, ts=EARLIER)
        loop.receive({"value": 20}, ts=NOW)
        tick = loop.fire(LATER, origin="test")

        # The tick now has enough info for fidelity traversal:
        # Store.between(tick.since, tick.ts) would return facts in [EARLIER, LATER]
        assert tick.since == EARLIER
        assert tick.ts == LATER
        assert tick.since < tick.ts


class TestLoopBasics:
    """Basic Loop functionality."""

    def test_receive_folds_payload(self):
        loop = Loop(
            name="counter",
            initial=0,
            fold=sum_fold,
        )

        loop.receive({"value": 10})
        loop.receive({"value": 5})

        assert loop.state == 15

    def test_fire_produces_tick(self):
        loop = Loop(
            name="counter",
            initial=0,
            fold=sum_fold,
        )

        loop.receive({"value": 10})
        tick = loop.fire(NOW, origin="test-vertex")

        assert tick.name == "counter"
        assert tick.ts == NOW
        assert tick.payload == 10
        assert tick.origin == "test-vertex"

    def test_fire_with_reset_clears_state(self):
        loop = Loop(
            name="counter",
            initial=0,
            fold=sum_fold,
            reset=True,
        )

        loop.receive({"value": 10})
        loop.fire(NOW)

        assert loop.state == 0

    def test_fire_without_reset_preserves_state(self):
        loop = Loop(
            name="counter",
            initial=0,
            fold=sum_fold,
            reset=False,
        )

        loop.receive({"value": 10})
        loop.fire(NOW)

        assert loop.state == 10

    def test_version_tracks_fold_count(self):
        loop = Loop(
            name="counter",
            initial=0,
            fold=sum_fold,
        )

        assert loop.version == 0
        loop.receive({"value": 10})
        assert loop.version == 1
        loop.receive({"value": 5})
        assert loop.version == 2


class TestCountBasedBoundaries:
    """Count-based boundary semantics (after N, every N)."""

    def test_boundary_after_fires_once(self):
        """boundary_mode='after' fires once after N facts, then never again."""
        loop = Loop(
            name="batch",
            initial=0,
            fold=sum_fold,
            boundary_count=3,
            boundary_mode="after",
            reset=True,
        )

        # First two facts don't trigger
        assert loop.receive({"value": 1}, ts=EARLIER) is False
        assert loop.receive({"value": 2}, ts=NOW) is False

        # Third fact triggers
        assert loop.receive({"value": 3}, ts=LATER) is True

        # Fire the boundary
        tick = loop.fire(LATER, origin="test")
        assert tick.payload == 6  # 1+2+3
        assert loop.state == 0  # reset

        # After firing, subsequent facts never trigger again (exhausted)
        assert loop.receive({"value": 4}) is False
        assert loop.receive({"value": 5}) is False
        assert loop.receive({"value": 6}) is False

    def test_boundary_every_fires_repeatedly(self):
        """boundary_mode='every' fires every N facts, repeating."""
        loop = Loop(
            name="windowed",
            initial=0,
            fold=sum_fold,
            boundary_count=2,
            boundary_mode="every",
            reset=True,
        )

        # First batch
        assert loop.receive({"value": 10}) is False
        assert loop.receive({"value": 20}) is True
        tick1 = loop.fire(NOW, origin="test")
        assert tick1.payload == 30

        # Second batch (resets and fires again)
        assert loop.receive({"value": 100}) is False
        assert loop.receive({"value": 200}) is True
        tick2 = loop.fire(LATER, origin="test")
        assert tick2.payload == 300

    def test_boundary_count_with_reset_false(self):
        """Count-based boundary with reset=False preserves state."""
        loop = Loop(
            name="accumulator",
            initial=0,
            fold=sum_fold,
            boundary_count=2,
            boundary_mode="every",
            reset=False,
        )

        loop.receive({"value": 10})
        loop.receive({"value": 20})  # triggers
        tick1 = loop.fire(NOW, origin="test")
        assert tick1.payload == 30

        # State preserved, count resets for "every"
        loop.receive({"value": 5})
        loop.receive({"value": 5})  # triggers
        tick2 = loop.fire(LATER, origin="test")
        assert tick2.payload == 40  # 30 + 5 + 5

    def test_receive_returns_false_for_kind_based_boundary(self):
        """Kind-based boundaries don't use count tracking."""
        loop = Loop(
            name="events",
            initial=0,
            fold=sum_fold,
            boundary_kind="events.done",  # kind-based
            boundary_mode="when",
        )

        # receive() always returns False for kind-based boundaries
        assert loop.receive({"value": 1}) is False
        assert loop.receive({"value": 2}) is False
        assert loop.receive({"value": 3}) is False


class TestLoopRunClause:
    """Loop propagates boundary_run to produced Ticks."""

    def test_fire_sets_tick_run(self):
        loop = Loop(
            name="task",
            initial={},
            fold=lambda s, p: {**s, p.get("name", "x"): p},
            boundary_kind="task",
            boundary_run="scripts/dispatch.sh",
        )
        loop.receive({"name": "job1"}, ts=EARLIER)
        tick = loop.fire(NOW, origin="test")
        assert tick.run == "scripts/dispatch.sh"

    def test_fire_without_run_clause(self):
        loop = Loop(
            name="task",
            initial={},
            fold=lambda s, p: {**s, p.get("name", "x"): p},
            boundary_kind="task",
        )
        loop.receive({"name": "job1"}, ts=EARLIER)
        tick = loop.fire(NOW, origin="test")
        assert tick.run is None

    def test_run_survives_reset(self):
        """Run clause is a loop property, persists across fire/reset cycles."""
        loop = Loop(
            name="batch",
            initial=[],
            fold=lambda s, p: [*s, p],
            boundary_count=2,
            boundary_mode="every",
            boundary_run="scripts/process.sh",
            reset=True,
        )
        loop.receive({"x": 1}, ts=EARLIER)
        loop.receive({"x": 2}, ts=NOW)
        tick1 = loop.fire(NOW, origin="test")
        assert tick1.run == "scripts/process.sh"

        # After reset, next fire still carries run
        loop.receive({"x": 3}, ts=LATER)
        loop.receive({"x": 4}, ts=LATER)
        tick2 = loop.fire(LATER, origin="test")
        assert tick2.run == "scripts/process.sh"
