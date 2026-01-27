"""Tests for Vertex — where loops meet."""

from datetime import datetime, timezone

import pytest

from ticks import EventStore, Tick, Vertex


NOW = datetime(2025, 6, 1, 12, 0, 0, tzinfo=timezone.utc)


def sum_fold(state: int, payload: dict) -> int:
    return state + payload["value"]


def count_fold(state: int, payload: dict) -> int:
    return state + 1


def collect_fold(state: list, payload: dict) -> list:
    return [*state, payload]


class TestVertexRegistration:
    """Kind registration and dispatch table."""

    def test_register_kind(self):
        v = Vertex()
        v.register("metric", 0, sum_fold)
        assert v.kinds == ["metric"]

    def test_register_multiple_kinds(self):
        v = Vertex()
        v.register("metric", 0, sum_fold)
        v.register("event", 0, count_fold)
        assert v.kinds == ["metric", "event"]

    def test_register_duplicate_kind_raises(self):
        v = Vertex()
        v.register("metric", 0, sum_fold)
        with pytest.raises(ValueError, match="Kind already registered"):
            v.register("metric", 0, count_fold)

    def test_empty_vertex_has_no_kinds(self):
        v = Vertex()
        assert v.kinds == []


class TestVertexReceive:
    """Fact routing via receive()."""

    def test_receive_folds_state(self):
        v = Vertex()
        v.register("metric", 0, sum_fold)

        v.receive("metric", {"value": 10})
        v.receive("metric", {"value": 5})

        assert v.state("metric") == 15

    def test_receive_unknown_kind_is_noop(self):
        v = Vertex()
        v.register("metric", 0, sum_fold)

        v.receive("unknown", {"value": 99})

        assert v.state("metric") == 0

    def test_receive_routes_to_correct_fold(self):
        v = Vertex()
        v.register("metric", 0, sum_fold)
        v.register("event", 0, count_fold)

        v.receive("metric", {"value": 10})
        v.receive("event", {"type": "deploy"})
        v.receive("metric", {"value": 5})

        assert v.state("metric") == 15
        assert v.state("event") == 1

    def test_receive_increments_version(self):
        v = Vertex()
        v.register("metric", 0, sum_fold)

        assert v.version("metric") == 0
        v.receive("metric", {"value": 1})
        assert v.version("metric") == 1

    def test_state_raises_for_unregistered_kind(self):
        v = Vertex()
        with pytest.raises(KeyError):
            v.state("missing")

    def test_version_raises_for_unregistered_kind(self):
        v = Vertex()
        with pytest.raises(KeyError):
            v.version("missing")


class TestVertexTick:
    """Temporal boundary firing."""

    def test_tick_snapshots_all_states(self):
        v = Vertex()
        v.register("metric", 0, sum_fold)
        v.register("event", 0, count_fold)

        v.receive("metric", {"value": 10})
        v.receive("event", {"type": "deploy"})

        tick = v.tick("my-loop", NOW)

        assert isinstance(tick, Tick)
        assert tick.name == "my-loop"
        assert tick.ts == NOW
        assert tick.payload == {"metric": 10, "event": 1}

    def test_tick_empty_vertex(self):
        v = Vertex()

        tick = v.tick("empty", NOW)

        assert tick.payload == {}

    def test_tick_before_any_receive(self):
        v = Vertex()
        v.register("metric", 0, sum_fold)

        tick = v.tick("fresh", NOW)

        assert tick.payload == {"metric": 0}

    def test_multiple_ticks_reflect_accumulated_state(self):
        v = Vertex()
        v.register("metric", 0, sum_fold)

        v.receive("metric", {"value": 10})
        tick1 = v.tick("loop", NOW)

        v.receive("metric", {"value": 5})
        tick2 = v.tick("loop", datetime(2025, 6, 1, 13, 0, 0, tzinfo=timezone.utc))

        assert tick1.payload == {"metric": 10}
        assert tick2.payload == {"metric": 15}


class TestVertexWithStore:
    """Vertex backed by a Store."""

    def test_receive_appends_to_store(self):
        store = EventStore()
        v = Vertex(store=store)
        v.register("metric", 0, sum_fold)

        v.receive("metric", {"value": 10})
        v.receive("metric", {"value": 5})

        assert len(store.events) == 2
        assert store.events[0] == ("metric", {"value": 10})
        assert store.events[1] == ("metric", {"value": 5})

    def test_unknown_kind_still_stored(self):
        store = EventStore()
        v = Vertex(store=store)
        v.register("metric", 0, sum_fold)

        v.receive("unknown", {"data": "x"})

        assert len(store.events) == 1
        assert store.events[0] == ("unknown", {"data": "x"})

    def test_vertex_without_store(self):
        v = Vertex()
        v.register("metric", 0, sum_fold)

        v.receive("metric", {"value": 10})

        assert v.state("metric") == 10


class TestVertexCollectFold:
    """Vertex with a collect (list-building) fold."""

    def test_collect_fold_accumulates(self):
        v = Vertex()
        v.register("log", [], collect_fold)

        v.receive("log", {"msg": "start"})
        v.receive("log", {"msg": "end"})

        assert v.state("log") == [{"msg": "start"}, {"msg": "end"}]

    def test_tick_with_collect_fold(self):
        v = Vertex()
        v.register("log", [], collect_fold)

        v.receive("log", {"msg": "hello"})

        tick = v.tick("collector", NOW)
        assert tick.payload == {"log": [{"msg": "hello"}]}


class TestVertexBoundaryRegistration:
    """Boundary configuration at registration time."""

    def test_register_with_boundary(self):
        v = Vertex()
        v.register("metric", 0, sum_fold, boundary="end-of-day")
        assert v.kinds == ["metric"]

    def test_boundary_kind_collision_raises(self):
        v = Vertex()
        v.register("metric", 0, sum_fold, boundary="end-of-day")
        with pytest.raises(ValueError, match="Boundary kind already registered"):
            v.register("event", 0, count_fold, boundary="end-of-day")

    def test_self_trigger_allowed(self):
        """Boundary kind == fold kind is valid (every fact of that kind triggers)."""
        v = Vertex()
        v.register("heartbeat", 0, count_fold, boundary="heartbeat")
        assert v.kinds == ["heartbeat"]

    def test_no_boundary_default(self):
        """Without boundary kwarg, no boundary is configured."""
        v = Vertex()
        v.register("metric", 0, sum_fold)
        result = v.receive("metric", {"value": 1})
        assert result is None


class TestVertexBoundaryReceive:
    """Boundary triggering via receive()."""

    def test_returns_none_without_boundary(self):
        v = Vertex()
        v.register("metric", 0, sum_fold)
        result = v.receive("metric", {"value": 10})
        assert result is None

    def test_returns_tick_on_boundary(self):
        v = Vertex()
        v.register("metric", 0, sum_fold, boundary="end-of-day")
        v.receive("metric", {"value": 10})
        v.receive("metric", {"value": 5})

        tick = v.receive("end-of-day", {})
        assert isinstance(tick, Tick)
        assert tick.name == "metric"
        assert tick.payload == 15

    def test_correct_origin(self):
        v = Vertex("my-vertex")
        v.register("metric", 0, sum_fold, boundary="end-of-day")
        v.receive("metric", {"value": 10})

        tick = v.receive("end-of-day", {})
        assert tick.origin == "my-vertex"

    def test_reset_clears_state(self):
        v = Vertex()
        v.register("metric", 0, sum_fold, boundary="end-of-day", reset=True)
        v.receive("metric", {"value": 10})
        v.receive("end-of-day", {})

        # State should be reset to initial
        assert v.state("metric") == 0

    def test_carry_without_reset(self):
        v = Vertex()
        v.register("metric", 0, sum_fold, boundary="end-of-day", reset=False)
        v.receive("metric", {"value": 10})
        v.receive("end-of-day", {})

        # State carries forward
        assert v.state("metric") == 10

    def test_self_trigger_folds_before_boundary(self):
        """When boundary kind == fold kind, fold happens first."""
        v = Vertex()
        v.register("heartbeat", 0, count_fold, boundary="heartbeat")

        tick = v.receive("heartbeat", {})
        assert isinstance(tick, Tick)
        # Fold happened first: 0 → 1, then boundary snapshots 1
        assert tick.payload == 1
        assert tick.name == "heartbeat"

    def test_cross_engine_trigger(self):
        """Boundary kind registered on one engine, triggered by different kind."""
        v = Vertex()
        v.register("metric", 0, sum_fold, boundary="flush")
        v.register("event", 0, count_fold)

        v.receive("metric", {"value": 10})
        v.receive("event", {"type": "deploy"})

        # "flush" is not a registered fold kind, but it's a boundary kind for "metric"
        tick = v.receive("flush", {})
        assert isinstance(tick, Tick)
        assert tick.name == "metric"
        assert tick.payload == 10
        # "event" engine untouched by boundary
        assert v.state("event") == 1

    def test_unregistered_boundary_kind_returns_none(self):
        """A kind that isn't registered and isn't a boundary returns None."""
        v = Vertex()
        v.register("metric", 0, sum_fold, boundary="end-of-day")
        result = v.receive("unknown", {})
        assert result is None

    def test_multiple_cycles(self):
        v = Vertex()
        v.register("metric", 0, sum_fold, boundary="end-of-day")

        v.receive("metric", {"value": 10})
        tick1 = v.receive("end-of-day", {})

        v.receive("metric", {"value": 7})
        tick2 = v.receive("end-of-day", {})

        assert tick1.payload == 10
        assert tick2.payload == 7  # reset after first boundary

    def test_boundary_with_store(self):
        store = EventStore()
        v = Vertex(store=store)
        v.register("metric", 0, sum_fold, boundary="end-of-day")

        v.receive("metric", {"value": 10})
        tick = v.receive("end-of-day", {})

        assert isinstance(tick, Tick)
        assert tick.payload == 10
        assert len(store.events) == 2

    def test_non_boundary_kind_returns_none(self):
        v = Vertex()
        v.register("metric", 0, sum_fold, boundary="end-of-day")
        v.register("event", 0, count_fold)

        result = v.receive("metric", {"value": 10})
        assert result is None

        result = v.receive("event", {"type": "deploy"})
        assert result is None


class TestVertexBoundaryWithManualTick:
    """Manual tick() coexists with auto-boundary."""

    def test_manual_tick_unaffected(self):
        v = Vertex()
        v.register("metric", 0, sum_fold, boundary="end-of-day")
        v.register("event", 0, count_fold)

        v.receive("metric", {"value": 10})
        v.receive("event", {"type": "deploy"})

        tick = v.tick("snapshot", NOW)
        assert tick.payload == {"metric": 10, "event": 1}
        assert tick.name == "snapshot"

    def test_manual_tick_does_not_reset(self):
        v = Vertex()
        v.register("metric", 0, sum_fold, boundary="end-of-day")

        v.receive("metric", {"value": 10})
        v.tick("snapshot", NOW)

        # State preserved after manual tick
        assert v.state("metric") == 10
        v.receive("metric", {"value": 5})
        assert v.state("metric") == 15
