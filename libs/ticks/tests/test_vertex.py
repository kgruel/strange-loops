"""Tests for Vertex — where loops meet."""

from datetime import datetime, timezone

import pytest

from facts import Fact
from peers import Peer
from ticks import EventStore, Tick, Vertex


NOW = datetime(2025, 6, 1, 12, 0, 0, tzinfo=timezone.utc)

# Default unrestricted peer for most tests
ROOT = Peer("root")


def fact(kind: str, **payload) -> Fact:
    """Create a Fact for testing."""
    return Fact.of(kind, **payload)


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

        v.receive(fact("metric", value=10), ROOT)
        v.receive(fact("metric", value=5), ROOT)

        assert v.state("metric") == 15

    def test_receive_unknown_kind_is_noop(self):
        v = Vertex()
        v.register("metric", 0, sum_fold)

        v.receive(fact("unknown", value=99), ROOT)

        assert v.state("metric") == 0

    def test_receive_routes_to_correct_fold(self):
        v = Vertex()
        v.register("metric", 0, sum_fold)
        v.register("event", 0, count_fold)

        v.receive(fact("metric", value=10), ROOT)
        v.receive(fact("event", type="deploy"), ROOT)
        v.receive(fact("metric", value=5), ROOT)

        assert v.state("metric") == 15
        assert v.state("event") == 1

    def test_receive_increments_version(self):
        v = Vertex()
        v.register("metric", 0, sum_fold)

        assert v.version("metric") == 0
        v.receive(fact("metric", value=1), ROOT)
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

        v.receive(fact("metric", value=10), ROOT)
        v.receive(fact("event", type="deploy"), ROOT)

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

        v.receive(fact("metric", value=10), ROOT)
        tick1 = v.tick("loop", NOW)

        v.receive(fact("metric", value=5), ROOT)
        tick2 = v.tick("loop", datetime(2025, 6, 1, 13, 0, 0, tzinfo=timezone.utc))

        assert tick1.payload == {"metric": 10}
        assert tick2.payload == {"metric": 15}


class TestVertexWithStore:
    """Vertex backed by a Store."""

    def test_receive_appends_to_store(self):
        store = EventStore()
        v = Vertex(store=store)
        v.register("metric", 0, sum_fold)

        v.receive(fact("metric", value=10), ROOT)
        v.receive(fact("metric", value=5), ROOT)

        assert len(store.events) == 2
        assert store.events[0] == ("metric", {"value": 10})
        assert store.events[1] == ("metric", {"value": 5})

    def test_unknown_kind_still_stored(self):
        store = EventStore()
        v = Vertex(store=store)
        v.register("metric", 0, sum_fold)

        v.receive(fact("unknown", data="x"), ROOT)

        assert len(store.events) == 1
        assert store.events[0] == ("unknown", {"data": "x"})

    def test_vertex_without_store(self):
        v = Vertex()
        v.register("metric", 0, sum_fold)

        v.receive(fact("metric", value=10), ROOT)

        assert v.state("metric") == 10


class TestVertexCollectFold:
    """Vertex with a collect (list-building) fold."""

    def test_collect_fold_accumulates(self):
        v = Vertex()
        v.register("log", [], collect_fold)

        v.receive(fact("log", msg="start"), ROOT)
        v.receive(fact("log", msg="end"), ROOT)

        assert v.state("log") == [{"msg": "start"}, {"msg": "end"}]

    def test_tick_with_collect_fold(self):
        v = Vertex()
        v.register("log", [], collect_fold)

        v.receive(fact("log", msg="hello"), ROOT)

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
        result = v.receive(fact("metric", value=1), ROOT)
        assert result is None


class TestVertexBoundaryReceive:
    """Boundary triggering via receive()."""

    def test_returns_none_without_boundary(self):
        v = Vertex()
        v.register("metric", 0, sum_fold)
        result = v.receive(fact("metric", value=10), ROOT)
        assert result is None

    def test_returns_tick_on_boundary(self):
        v = Vertex()
        v.register("metric", 0, sum_fold, boundary="end-of-day")
        v.receive(fact("metric", value=10), ROOT)
        v.receive(fact("metric", value=5), ROOT)

        tick = v.receive(fact("end-of-day"), ROOT)
        assert isinstance(tick, Tick)
        assert tick.name == "metric"
        assert tick.payload == 15

    def test_correct_origin(self):
        v = Vertex("my-vertex")
        v.register("metric", 0, sum_fold, boundary="end-of-day")
        v.receive(fact("metric", value=10), ROOT)

        tick = v.receive(fact("end-of-day"), ROOT)
        assert tick.origin == "my-vertex"

    def test_reset_clears_state(self):
        v = Vertex()
        v.register("metric", 0, sum_fold, boundary="end-of-day", reset=True)
        v.receive(fact("metric", value=10), ROOT)
        v.receive(fact("end-of-day"), ROOT)

        # State should be reset to initial
        assert v.state("metric") == 0

    def test_carry_without_reset(self):
        v = Vertex()
        v.register("metric", 0, sum_fold, boundary="end-of-day", reset=False)
        v.receive(fact("metric", value=10), ROOT)
        v.receive(fact("end-of-day"), ROOT)

        # State carries forward
        assert v.state("metric") == 10

    def test_self_trigger_folds_before_boundary(self):
        """When boundary kind == fold kind, fold happens first."""
        v = Vertex()
        v.register("heartbeat", 0, count_fold, boundary="heartbeat")

        tick = v.receive(fact("heartbeat"), ROOT)
        assert isinstance(tick, Tick)
        # Fold happened first: 0 → 1, then boundary snapshots 1
        assert tick.payload == 1
        assert tick.name == "heartbeat"

    def test_cross_engine_trigger(self):
        """Boundary kind registered on one engine, triggered by different kind."""
        v = Vertex()
        v.register("metric", 0, sum_fold, boundary="flush")
        v.register("event", 0, count_fold)

        v.receive(fact("metric", value=10), ROOT)
        v.receive(fact("event", type="deploy"), ROOT)

        # "flush" is not a registered fold kind, but it's a boundary kind for "metric"
        tick = v.receive(fact("flush"), ROOT)
        assert isinstance(tick, Tick)
        assert tick.name == "metric"
        assert tick.payload == 10
        # "event" engine untouched by boundary
        assert v.state("event") == 1

    def test_unregistered_boundary_kind_returns_none(self):
        """A kind that isn't registered and isn't a boundary returns None."""
        v = Vertex()
        v.register("metric", 0, sum_fold, boundary="end-of-day")
        result = v.receive(fact("unknown"), ROOT)
        assert result is None

    def test_multiple_cycles(self):
        v = Vertex()
        v.register("metric", 0, sum_fold, boundary="end-of-day")

        v.receive(fact("metric", value=10), ROOT)
        tick1 = v.receive(fact("end-of-day"), ROOT)

        v.receive(fact("metric", value=7), ROOT)
        tick2 = v.receive(fact("end-of-day"), ROOT)

        assert tick1.payload == 10
        assert tick2.payload == 7  # reset after first boundary

    def test_boundary_with_store(self):
        store = EventStore()
        v = Vertex(store=store)
        v.register("metric", 0, sum_fold, boundary="end-of-day")

        v.receive(fact("metric", value=10), ROOT)
        tick = v.receive(fact("end-of-day"), ROOT)

        assert isinstance(tick, Tick)
        assert tick.payload == 10
        assert len(store.events) == 2

    def test_non_boundary_kind_returns_none(self):
        v = Vertex()
        v.register("metric", 0, sum_fold, boundary="end-of-day")
        v.register("event", 0, count_fold)

        result = v.receive(fact("metric", value=10), ROOT)
        assert result is None

        result = v.receive(fact("event", type="deploy"), ROOT)
        assert result is None


class TestVertexBoundaryWithManualTick:
    """Manual tick() coexists with auto-boundary."""

    def test_manual_tick_unaffected(self):
        v = Vertex()
        v.register("metric", 0, sum_fold, boundary="end-of-day")
        v.register("event", 0, count_fold)

        v.receive(fact("metric", value=10), ROOT)
        v.receive(fact("event", type="deploy"), ROOT)

        tick = v.tick("snapshot", NOW)
        assert tick.payload == {"metric": 10, "event": 1}
        assert tick.name == "snapshot"

    def test_manual_tick_does_not_reset(self):
        v = Vertex()
        v.register("metric", 0, sum_fold, boundary="end-of-day")

        v.receive(fact("metric", value=10), ROOT)
        v.tick("snapshot", NOW)

        # State preserved after manual tick
        assert v.state("metric") == 10
        v.receive(fact("metric", value=5), ROOT)
        assert v.state("metric") == 15


class TestVertexPeerGating:
    """Peer-aware receive: potential and observer-state gating."""

    def test_unrestricted_peer_can_emit_any_kind(self):
        v = Vertex()
        v.register("metric", 0, sum_fold)
        v.register("event", 0, count_fold)

        unrestricted = Peer("alice")

        v.receive(fact("metric", value=10), unrestricted)
        v.receive(fact("event", type="deploy"), unrestricted)

        assert v.state("metric") == 10
        assert v.state("event") == 1

    def test_restricted_peer_blocked_outside_potential(self):
        v = Vertex()
        v.register("metric", 0, sum_fold)
        v.register("event", 0, count_fold)

        # Can only emit "metric"
        restricted = Peer("bob", potential=frozenset({"metric"}))

        v.receive(fact("metric", value=10), restricted)
        result = v.receive(fact("event", type="deploy"), restricted)

        assert v.state("metric") == 10
        assert v.state("event") == 0  # blocked, not folded
        assert result is None

    def test_restricted_peer_allowed_within_potential(self):
        v = Vertex()
        v.register("metric", 0, sum_fold)
        v.register("event", 0, count_fold)

        restricted = Peer("bob", potential=frozenset({"metric", "event"}))

        v.receive(fact("metric", value=10), restricted)
        v.receive(fact("event", type="deploy"), restricted)

        assert v.state("metric") == 10
        assert v.state("event") == 1

    def test_observer_state_kind_ownership_enforced(self):
        """focus.{peer} kinds must match the acting peer."""
        v = Vertex()
        v.register("focus.alice", {"index": 0}, lambda s, p: {"index": p.get("index", 0)})
        v.register("focus.bob", {"index": 0}, lambda s, p: {"index": p.get("index", 0)})

        alice = Peer("alice")
        bob = Peer("bob")

        # Alice can update her own focus
        v.receive(fact("focus.alice", index=5), alice)
        assert v.state("focus.alice") == {"index": 5}

        # Alice cannot update Bob's focus
        v.receive(fact("focus.bob", index=10), alice)
        assert v.state("focus.bob") == {"index": 0}  # unchanged

        # Bob can update his own focus
        v.receive(fact("focus.bob", index=3), bob)
        assert v.state("focus.bob") == {"index": 3}

    def test_observer_state_kinds_scroll_and_selection(self):
        """scroll.{peer} and selection.{peer} also enforce ownership."""
        v = Vertex()
        v.register("scroll.alice", {"y": 0}, lambda s, p: {"y": p.get("y", 0)})
        v.register("selection.alice", {"start": 0, "end": 0}, lambda s, p: p)

        alice = Peer("alice")
        bob = Peer("bob")

        # Alice can update her own
        v.receive(fact("scroll.alice", y=100), alice)
        v.receive(fact("selection.alice", start=5, end=10), alice)
        assert v.state("scroll.alice") == {"y": 100}
        assert v.state("selection.alice") == {"start": 5, "end": 10}

        # Bob cannot
        v.receive(fact("scroll.alice", y=200), bob)
        v.receive(fact("selection.alice", start=0, end=0), bob)
        assert v.state("scroll.alice") == {"y": 100}  # unchanged
        assert v.state("selection.alice") == {"start": 5, "end": 10}  # unchanged

    def test_non_observer_state_kinds_unaffected(self):
        """Regular kinds without observer-state pattern are not ownership-checked."""
        v = Vertex()
        v.register("focus", {"index": 0}, lambda s, p: {"index": p.get("index", 0)})

        alice = Peer("alice")
        bob = Peer("bob")

        # Both can update plain "focus" (no .{peer} suffix)
        v.receive(fact("focus", index=5), alice)
        assert v.state("focus") == {"index": 5}

        v.receive(fact("focus", index=10), bob)
        assert v.state("focus") == {"index": 10}

    def test_potential_and_observer_state_combined(self):
        """Both gates apply: potential first, then ownership."""
        v = Vertex()
        v.register("focus.alice", {"index": 0}, lambda s, p: {"index": p.get("index", 0)})

        # Alice restricted to only focus.alice
        alice = Peer("alice", potential=frozenset({"focus.alice"}))
        # Bob restricted to only focus.bob (which isn't registered)
        bob = Peer("bob", potential=frozenset({"focus.bob"}))

        # Alice can update her focus
        v.receive(fact("focus.alice", index=5), alice)
        assert v.state("focus.alice") == {"index": 5}

        # Bob blocked by potential (focus.alice not in his potential)
        v.receive(fact("focus.alice", index=10), bob)
        assert v.state("focus.alice") == {"index": 5}  # unchanged

    def test_rejected_fact_not_stored(self):
        """When a fact is rejected, it should not be stored."""
        store = EventStore()
        v = Vertex(store=store)
        v.register("metric", 0, sum_fold)

        restricted = Peer("bob", potential=frozenset({"other"}))

        v.receive(fact("metric", value=10), restricted)

        assert len(store.events) == 0  # rejected, not stored

    def test_boundary_fact_needs_potential(self):
        """Boundary facts are also gated by potential."""
        v = Vertex()
        v.register("metric", 0, sum_fold, boundary="flush")

        # Has potential for metric but not flush
        restricted = Peer("bob", potential=frozenset({"metric"}))

        v.receive(fact("metric", value=10), restricted)
        tick = v.receive(fact("flush"), restricted)

        assert v.state("metric") == 10  # folded
        assert tick is None  # boundary blocked
