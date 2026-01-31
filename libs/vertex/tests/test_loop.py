"""Tests for Loop — explicit fold cycle with boundary semantics."""

from datetime import datetime, timezone

from vertex import Loop, Projection


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
            projection=Projection(0, fold=sum_fold),
        )

        # Period start is None before any receive
        assert loop._period_start is None

        # First receive sets period start
        loop.receive({"value": 10}, ts=EARLIER)
        assert loop._period_start == EARLIER

    def test_subsequent_receive_does_not_change_period_start(self):
        loop = Loop(
            name="counter",
            projection=Projection(0, fold=sum_fold),
        )

        loop.receive({"value": 10}, ts=EARLIER)
        loop.receive({"value": 20}, ts=NOW)
        loop.receive({"value": 30}, ts=LATER)

        # Period start remains the first timestamp
        assert loop._period_start == EARLIER

    def test_fire_includes_since_in_tick(self):
        loop = Loop(
            name="counter",
            projection=Projection(0, fold=sum_fold),
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
            projection=Projection(0, fold=sum_fold),
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
            projection=Projection(0, fold=sum_fold),
            reset=False,
        )

        loop.receive({"value": 10}, ts=EARLIER)
        tick = loop.fire(NOW, origin="test")

        # Without reset, period start is preserved
        assert loop._period_start == EARLIER

    def test_receive_without_ts_uses_now(self):
        loop = Loop(
            name="counter",
            projection=Projection(0, fold=sum_fold),
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
            projection=Projection(0, fold=sum_fold),
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
            projection=Projection(0, fold=sum_fold),
        )

        loop.receive({"value": 10})
        loop.receive({"value": 5})

        assert loop.state == 15

    def test_fire_produces_tick(self):
        loop = Loop(
            name="counter",
            projection=Projection(0, fold=sum_fold),
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
            projection=Projection(0, fold=sum_fold),
            reset=True,
        )

        loop.receive({"value": 10})
        loop.fire(NOW)

        assert loop.state == 0

    def test_fire_without_reset_preserves_state(self):
        loop = Loop(
            name="counter",
            projection=Projection(0, fold=sum_fold),
            reset=False,
        )

        loop.receive({"value": 10})
        loop.fire(NOW)

        assert loop.state == 10

    def test_version_tracks_fold_count(self):
        loop = Loop(
            name="counter",
            projection=Projection(0, fold=sum_fold),
        )

        assert loop.version == 0
        loop.receive({"value": 10})
        assert loop.version == 1
        loop.receive({"value": 5})
        assert loop.version == 2
