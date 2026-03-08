"""Tests for Vertex — where loops meet."""

from datetime import datetime, timezone

import pytest

from atoms import Fact
from engine import Grant
from engine import EventStore, Tick, Vertex


NOW = datetime(2025, 6, 1, 12, 0, 0, tzinfo=timezone.utc)


def fact(kind: str, observer: str = "test", **payload) -> Fact:
    """Create a Fact for testing."""
    return Fact.of(kind, observer, **payload)


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

        v.receive(fact("metric", value=10))
        v.receive(fact("metric", value=5))

        assert v.state("metric") == 15

    def test_receive_unknown_kind_is_noop(self):
        v = Vertex()
        v.register("metric", 0, sum_fold)

        v.receive(fact("unknown", value=99))

        assert v.state("metric") == 0

    def test_receive_routes_to_correct_fold(self):
        v = Vertex()
        v.register("metric", 0, sum_fold)
        v.register("event", 0, count_fold)

        v.receive(fact("metric", value=10))
        v.receive(fact("event", type="deploy"))
        v.receive(fact("metric", value=5))

        assert v.state("metric") == 15
        assert v.state("event") == 1

    def test_receive_increments_version(self):
        v = Vertex()
        v.register("metric", 0, sum_fold)

        assert v.version("metric") == 0
        v.receive(fact("metric", value=1))
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

        v.receive(fact("metric", value=10))
        v.receive(fact("event", type="deploy"))

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

        v.receive(fact("metric", value=10))
        tick1 = v.tick("loop", NOW)

        v.receive(fact("metric", value=5))
        tick2 = v.tick("loop", datetime(2025, 6, 1, 13, 0, 0, tzinfo=timezone.utc))

        assert tick1.payload == {"metric": 10}
        assert tick2.payload == {"metric": 15}


class TestVertexWithStore:
    """Vertex backed by a Store."""

    def test_receive_appends_to_store(self):
        store = EventStore()
        v = Vertex(store=store)
        v.register("metric", 0, sum_fold)

        v.receive(fact("metric", value=10))
        v.receive(fact("metric", value=5))

        assert len(store.events) == 2
        # Store now holds full Fact objects (for replay support)
        assert store.events[0].kind == "metric"
        assert store.events[0].payload["value"] == 10
        assert store.events[1].kind == "metric"
        assert store.events[1].payload["value"] == 5

    def test_unknown_kind_still_stored(self):
        store = EventStore()
        v = Vertex(store=store)
        v.register("metric", 0, sum_fold)

        v.receive(fact("unknown", data="x"))

        assert len(store.events) == 1
        # Store now holds full Fact objects (for replay support)
        assert store.events[0].kind == "unknown"
        assert store.events[0].payload["data"] == "x"

    def test_vertex_without_store(self):
        v = Vertex()
        v.register("metric", 0, sum_fold)

        v.receive(fact("metric", value=10))

        assert v.state("metric") == 10


class TestVertexCollectFold:
    """Vertex with a collect (list-building) fold."""

    def test_collect_fold_accumulates(self):
        v = Vertex()
        v.register("log", [], collect_fold)

        v.receive(fact("log", msg="start"))
        v.receive(fact("log", msg="end"))

        assert v.state("log") == [{"msg": "start"}, {"msg": "end"}]

    def test_tick_with_collect_fold(self):
        v = Vertex()
        v.register("log", [], collect_fold)

        v.receive(fact("log", msg="hello"))

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
        result = v.receive(fact("metric", value=1))
        assert result is None


class TestVertexBoundaryReceive:
    """Boundary triggering via receive()."""

    def test_returns_none_without_boundary(self):
        v = Vertex()
        v.register("metric", 0, sum_fold)
        result = v.receive(fact("metric", value=10))
        assert result is None

    def test_returns_tick_on_boundary(self):
        v = Vertex()
        v.register("metric", 0, sum_fold, boundary="end-of-day")
        v.receive(fact("metric", value=10))
        v.receive(fact("metric", value=5))

        tick = v.receive(fact("end-of-day"))
        assert isinstance(tick, Tick)
        assert tick.name == "metric"
        assert tick.payload == 15

    def test_correct_origin(self):
        v = Vertex("my-vertex")
        v.register("metric", 0, sum_fold, boundary="end-of-day")
        v.receive(fact("metric", value=10))

        tick = v.receive(fact("end-of-day"))
        assert tick.origin == "my-vertex"

    def test_reset_clears_state(self):
        v = Vertex()
        v.register("metric", 0, sum_fold, boundary="end-of-day", reset=True)
        v.receive(fact("metric", value=10))
        v.receive(fact("end-of-day"))

        # State should be reset to initial
        assert v.state("metric") == 0

    def test_carry_without_reset(self):
        v = Vertex()
        v.register("metric", 0, sum_fold, boundary="end-of-day", reset=False)
        v.receive(fact("metric", value=10))
        v.receive(fact("end-of-day"))

        # State carries forward
        assert v.state("metric") == 10

    def test_self_trigger_folds_before_boundary(self):
        """When boundary kind == fold kind, fold happens first."""
        v = Vertex()
        v.register("heartbeat", 0, count_fold, boundary="heartbeat")

        tick = v.receive(fact("heartbeat"))
        assert isinstance(tick, Tick)
        # Fold happened first: 0 → 1, then boundary snapshots 1
        assert tick.payload == 1
        assert tick.name == "heartbeat"

    def test_cross_engine_trigger(self):
        """Boundary kind registered on one engine, triggered by different kind."""
        v = Vertex()
        v.register("metric", 0, sum_fold, boundary="flush")
        v.register("event", 0, count_fold)

        v.receive(fact("metric", value=10))
        v.receive(fact("event", type="deploy"))

        # "flush" is not a registered fold kind, but it's a boundary kind for "metric"
        tick = v.receive(fact("flush"))
        assert isinstance(tick, Tick)
        assert tick.name == "metric"
        assert tick.payload == 10
        # "event" engine untouched by boundary
        assert v.state("event") == 1

    def test_unregistered_boundary_kind_returns_none(self):
        """A kind that isn't registered and isn't a boundary returns None."""
        v = Vertex()
        v.register("metric", 0, sum_fold, boundary="end-of-day")
        result = v.receive(fact("unknown"))
        assert result is None

    def test_multiple_cycles(self):
        v = Vertex()
        v.register("metric", 0, sum_fold, boundary="end-of-day")

        v.receive(fact("metric", value=10))
        tick1 = v.receive(fact("end-of-day"))

        v.receive(fact("metric", value=7))
        tick2 = v.receive(fact("end-of-day"))

        assert tick1.payload == 10
        assert tick2.payload == 7  # reset after first boundary

    def test_boundary_with_store(self):
        store = EventStore()
        v = Vertex(store=store)
        v.register("metric", 0, sum_fold, boundary="end-of-day")

        v.receive(fact("metric", value=10))
        tick = v.receive(fact("end-of-day"))

        assert isinstance(tick, Tick)
        assert tick.payload == 10
        assert len(store.events) == 2

    def test_non_boundary_kind_returns_none(self):
        v = Vertex()
        v.register("metric", 0, sum_fold, boundary="end-of-day")
        v.register("event", 0, count_fold)

        result = v.receive(fact("metric", value=10))
        assert result is None

        result = v.receive(fact("event", type="deploy"))
        assert result is None


class TestVertexBoundaryWithManualTick:
    """Manual tick() coexists with auto-boundary."""

    def test_manual_tick_unaffected(self):
        v = Vertex()
        v.register("metric", 0, sum_fold, boundary="end-of-day")
        v.register("event", 0, count_fold)

        v.receive(fact("metric", value=10))
        v.receive(fact("event", type="deploy"))

        tick = v.tick("snapshot", NOW)
        assert tick.payload == {"metric": 10, "event": 1}
        assert tick.name == "snapshot"

    def test_manual_tick_does_not_reset(self):
        v = Vertex()
        v.register("metric", 0, sum_fold, boundary="end-of-day")

        v.receive(fact("metric", value=10))
        v.tick("snapshot", NOW)

        # State preserved after manual tick
        assert v.state("metric") == 10
        v.receive(fact("metric", value=5))
        assert v.state("metric") == 15


class TestVertexGrantGating:
    """Grant-aware receive: potential and observer-state gating."""

    def test_no_grant_allows_any_kind(self):
        v = Vertex()
        v.register("metric", 0, sum_fold)
        v.register("event", 0, count_fold)

        # No grant = unrestricted
        v.receive(fact("metric", "alice", value=10))
        v.receive(fact("event", "alice", type="deploy"))

        assert v.state("metric") == 10
        assert v.state("event") == 1

    def test_restricted_grant_blocked_outside_potential(self):
        v = Vertex()
        v.register("metric", 0, sum_fold)
        v.register("event", 0, count_fold)

        # Can only emit "metric"
        restricted = Grant(potential=frozenset({"metric"}))

        v.receive(fact("metric", "bob", value=10), restricted)
        result = v.receive(fact("event", "bob", type="deploy"), restricted)

        assert v.state("metric") == 10
        assert v.state("event") == 0  # blocked, not folded
        assert result is None

    def test_restricted_grant_allowed_within_potential(self):
        v = Vertex()
        v.register("metric", 0, sum_fold)
        v.register("event", 0, count_fold)

        restricted = Grant(potential=frozenset({"metric", "event"}))

        v.receive(fact("metric", "bob", value=10), restricted)
        v.receive(fact("event", "bob", type="deploy"), restricted)

        assert v.state("metric") == 10
        assert v.state("event") == 1

    def test_observer_state_kind_ownership_enforced(self):
        """focus.{observer} kinds must match fact.observer."""
        v = Vertex()
        v.register("focus.alice", {"index": 0}, lambda s, p: {"index": p.get("index", 0)})
        v.register("focus.bob", {"index": 0}, lambda s, p: {"index": p.get("index", 0)})

        # Alice can update her own focus (observer="alice" matches focus.alice)
        v.receive(fact("focus.alice", "alice", index=5))
        assert v.state("focus.alice") == {"index": 5}

        # Alice cannot update Bob's focus (observer="alice" doesn't match focus.bob)
        v.receive(fact("focus.bob", "alice", index=10))
        assert v.state("focus.bob") == {"index": 0}  # unchanged

        # Bob can update his own focus
        v.receive(fact("focus.bob", "bob", index=3))
        assert v.state("focus.bob") == {"index": 3}

    def test_observer_state_kinds_scroll_and_selection(self):
        """scroll.{observer} and selection.{observer} also enforce ownership."""
        v = Vertex()
        v.register("scroll.alice", {"y": 0}, lambda s, p: {"y": p.get("y", 0)})
        v.register("selection.alice", {"start": 0, "end": 0}, lambda s, p: p)

        # Alice can update her own (observer matches kind suffix)
        v.receive(fact("scroll.alice", "alice", y=100))
        v.receive(fact("selection.alice", "alice", start=5, end=10))
        assert v.state("scroll.alice") == {"y": 100}
        assert v.state("selection.alice") == {"start": 5, "end": 10}

        # Bob cannot (observer="bob" doesn't match "alice" suffix)
        v.receive(fact("scroll.alice", "bob", y=200))
        v.receive(fact("selection.alice", "bob", start=0, end=0))
        assert v.state("scroll.alice") == {"y": 100}  # unchanged
        assert v.state("selection.alice") == {"start": 5, "end": 10}  # unchanged

    def test_non_observer_state_kinds_unaffected(self):
        """Regular kinds without observer-state pattern are not ownership-checked."""
        v = Vertex()
        v.register("focus", {"index": 0}, lambda s, p: {"index": p.get("index", 0)})

        # Both observers can update plain "focus" (no .{observer} suffix)
        v.receive(fact("focus", "alice", index=5))
        assert v.state("focus") == {"index": 5}

        v.receive(fact("focus", "bob", index=10))
        assert v.state("focus") == {"index": 10}

    def test_potential_and_observer_state_combined(self):
        """Both gates apply: potential first, then ownership."""
        v = Vertex()
        v.register("focus.alice", {"index": 0}, lambda s, p: {"index": p.get("index", 0)})

        # Grant restricted to only focus.alice
        alice_grant = Grant(potential=frozenset({"focus.alice"}))
        # Grant restricted to only focus.bob (which isn't registered)
        bob_grant = Grant(potential=frozenset({"focus.bob"}))

        # Alice's grant allows focus.alice, and observer matches
        v.receive(fact("focus.alice", "alice", index=5), alice_grant)
        assert v.state("focus.alice") == {"index": 5}

        # Bob's grant blocks focus.alice (not in potential)
        v.receive(fact("focus.alice", "bob", index=10), bob_grant)
        assert v.state("focus.alice") == {"index": 5}  # unchanged

    def test_rejected_fact_not_stored(self):
        """When a fact is rejected, it should not be stored."""
        store = EventStore()
        v = Vertex(store=store)
        v.register("metric", 0, sum_fold)

        restricted = Grant(potential=frozenset({"other"}))

        v.receive(fact("metric", "bob", value=10), restricted)

        assert len(store.events) == 0  # rejected, not stored

    def test_boundary_fact_needs_potential(self):
        """Boundary facts are also gated by potential."""
        v = Vertex()
        v.register("metric", 0, sum_fold, boundary="flush")

        # Has potential for metric but not flush
        restricted = Grant(potential=frozenset({"metric"}))

        v.receive(fact("metric", "bob", value=10), restricted)
        tick = v.receive(fact("flush", "bob"), restricted)

        assert v.state("metric") == 10  # folded
        assert tick is None  # boundary blocked


class TestVertexToFact:
    """Convert Tick to Fact for forwarding."""

    def test_to_fact_converts_tick(self):
        v = Vertex("my-vertex")
        v.register("metric", 0, sum_fold, boundary="flush")
        v.receive(fact("metric", "alice", value=10))
        tick = v.receive(fact("flush", "alice"))

        f = v.to_fact(tick)

        assert f.kind == "tick.metric"
        assert f.observer == "my-vertex"
        assert f.payload == 10

    def test_to_fact_timestamp_from_tick(self):
        v = Vertex("v1")
        tick = Tick(name="test", ts=NOW, payload={"x": 1}, origin="v1")

        f = v.to_fact(tick)

        assert f.ts == NOW.timestamp()

    def test_to_fact_preserves_origin(self):
        v = Vertex("my-vertex")
        v.register("metric", 0, sum_fold, boundary="flush")
        v.receive(fact("metric", "alice", value=10))
        tick = v.receive(fact("flush", "alice"))

        f = v.to_fact(tick)

        assert f.origin == "my-vertex"

    def test_tick_to_fact_preserves_origin(self):
        """_tick_to_fact (child tick re-entry) preserves tick.origin."""
        v = Vertex("parent")
        tick = Tick(name="child-metric", ts=NOW, payload={"x": 1}, origin="child-v")

        f = v._tick_to_fact(tick, "child-v")

        assert f.origin == "child-v"

    def test_external_fact_has_empty_origin(self):
        """Facts created via Fact.of() have empty origin (external observation)."""
        f = fact("metric", value=10)
        assert f.origin == ""


class TestCountBasedBoundaryIntegration:
    """Vertex integration with count-based Loop boundaries."""

    def test_vertex_fires_tick_on_count_boundary(self):
        """Loop with boundary_count fires tick through Vertex."""
        from engine import Loop, Projection

        v = Vertex("batch-processor")
        loop = Loop(
            name="events",
            projection=Projection(0, fold=count_fold),
            boundary_count=3,
            boundary_mode="every",
            reset=True,
        )
        v.register_loop(loop)

        # First two facts — no tick
        tick1 = v.receive(fact("events", value=1))
        tick2 = v.receive(fact("events", value=2))
        assert tick1 is None
        assert tick2 is None

        # Third fact — tick fires
        tick3 = v.receive(fact("events", value=3))
        assert tick3 is not None
        assert tick3.name == "events"
        assert tick3.payload == 3  # count of 3
        assert tick3.origin == "batch-processor"

    def test_vertex_count_boundary_repeats_with_every(self):
        """boundary_mode='every' fires tick repeatedly."""
        from engine import Loop, Projection

        v = Vertex("windowed")
        loop = Loop(
            name="metrics",
            projection=Projection(0, fold=sum_fold),
            boundary_count=2,
            boundary_mode="every",
            reset=True,
        )
        v.register_loop(loop)

        # First batch
        v.receive(fact("metrics", value=10))
        tick1 = v.receive(fact("metrics", value=20))
        assert tick1 is not None
        assert tick1.payload == 30

        # Second batch
        v.receive(fact("metrics", value=100))
        tick2 = v.receive(fact("metrics", value=200))
        assert tick2 is not None
        assert tick2.payload == 300

    def test_vertex_count_boundary_exhausted_with_after(self):
        """boundary_mode='after' fires once then stops."""
        from engine import Loop, Projection

        v = Vertex("oneshot")
        loop = Loop(
            name="warmup",
            projection=Projection([], fold=collect_fold),
            boundary_count=2,
            boundary_mode="after",
            reset=True,
        )
        v.register_loop(loop)

        # First batch fires
        v.receive(fact("warmup", x=1))
        tick1 = v.receive(fact("warmup", x=2))
        assert tick1 is not None

        # Subsequent facts don't fire (exhausted)
        v.receive(fact("warmup", x=3))
        tick2 = v.receive(fact("warmup", x=4))
        assert tick2 is None


class TestReceiveStoresTick:
    """Verify that Vertex persists ticks to SqliteStore on boundary fire."""

    def test_kind_boundary_stores_tick(self, tmp_path):
        from engine.sqlite_store import SqliteStore
        from atoms import Fact

        store = SqliteStore(
            path=tmp_path / "test.db",
            serialize=lambda f: {"kind": f.kind, "ts": f.ts, "observer": f.observer, "origin": f.origin, "payload": dict(f.payload)},
            deserialize=lambda d: Fact(kind=d["kind"], ts=d["ts"], observer=d["observer"], origin=d.get("origin", ""), payload=d["payload"]),
        )
        v = Vertex("v1", store=store)
        v.register("metric", 0, sum_fold, boundary="flush")

        v.receive(fact("metric", value=10))
        tick = v.receive(fact("flush"))

        assert tick is not None
        ticks = store.ticks_since(0)
        assert len(ticks) == 1
        assert ticks[0].name == "metric"
        assert ticks[0].origin == "v1"
        store.close()

    def test_count_boundary_stores_tick(self, tmp_path):
        from engine import Loop, Projection
        from engine.sqlite_store import SqliteStore
        from atoms import Fact

        store = SqliteStore(
            path=tmp_path / "test.db",
            serialize=lambda f: {"kind": f.kind, "ts": f.ts, "observer": f.observer, "origin": f.origin, "payload": dict(f.payload)},
            deserialize=lambda d: Fact(kind=d["kind"], ts=d["ts"], observer=d["observer"], origin=d.get("origin", ""), payload=d["payload"]),
        )
        v = Vertex("v1", store=store)
        loop = Loop(
            name="events",
            projection=Projection(0, fold=count_fold),
            boundary_count=2,
            boundary_mode="every",
            reset=True,
        )
        v.register_loop(loop)

        v.receive(fact("events", value=1))
        tick = v.receive(fact("events", value=2))

        assert tick is not None
        ticks = store.ticks_since(0)
        assert len(ticks) == 1
        assert ticks[0].name == "events"
        store.close()


class TestRegisterCreatesLoop:
    """Verify that register() populates _loops (no _engines)."""

    def test_register_populates_loops(self):
        v = Vertex()
        v.register("metric", 0, sum_fold, boundary="flush")

        assert "metric" in v._loops
        assert not hasattr(v, '_engines')

    def test_register_boundary_ticks_have_since(self):
        """Ticks from register()-created loops now have since set."""
        v = Vertex()
        v.register("metric", 0, sum_fold, boundary="flush")

        v.receive(fact("metric", value=10))
        tick = v.receive(fact("flush"))

        assert tick is not None
        assert tick.since is not None


class TestVertexLevelBoundary:
    """Vertex-level boundary fires all loops, not just one."""

    def test_vertex_boundary_fires_all_loops(self):
        v = Vertex("project")
        v.register("decision", {}, lambda s, p: {**s, p["topic"]: p})
        v.register("session", {}, lambda s, p: {**s, p["name"]: p})
        v.register_vertex_boundary("session", match=(("status", "closed"),))

        v.receive(fact("decision", topic="auth", position="JWT"))
        v.receive(fact("session", name="test", status="open"))
        tick = v.receive(fact("session", name="test", status="closed"))

        assert tick is not None
        assert tick.name == "project"  # vertex name, not loop name
        assert tick.origin == "project"
        assert "decision" in tick.payload
        assert "session" in tick.payload
        assert "_boundary" in tick.payload
        assert tick.payload["decision"]["auth"]["position"] == "JWT"
        assert tick.payload["session"]["test"]["status"] == "closed"
        assert tick.payload["_boundary"]["status"] == "closed"

    def test_vertex_boundary_no_match_returns_none(self):
        v = Vertex("project")
        v.register("session", {}, lambda s, p: {**s, p["name"]: p})
        v.register_vertex_boundary("session", match=(("status", "closed"),))

        tick = v.receive(fact("session", name="test", status="open"))
        assert tick is None

    def test_vertex_boundary_tracks_period(self):
        v = Vertex("project")
        v.register("decision", {}, lambda s, p: {**s, p["topic"]: p})
        v.register("session", {}, lambda s, p: {**s, p["name"]: p})
        v.register_vertex_boundary("session", match=(("status", "closed"),))

        v.receive(fact("session", name="test", status="open"))
        v.receive(fact("decision", topic="auth", position="JWT"))
        tick = v.receive(fact("session", name="test", status="closed"))

        assert tick is not None
        assert tick.since is not None
        assert tick.since <= tick.ts

    def test_vertex_boundary_period_resets(self):
        """After firing, next fact starts a new period."""
        v = Vertex("project")
        v.register("session", {}, lambda s, p: {**s, p["name"]: p})
        v.register_vertex_boundary("session", match=(("status", "closed"),))

        v.receive(fact("session", name="s1", status="open"))
        tick1 = v.receive(fact("session", name="s1", status="closed"))
        assert tick1 is not None

        v.receive(fact("session", name="s2", status="open"))
        tick2 = v.receive(fact("session", name="s2", status="closed"))
        assert tick2 is not None
        assert tick2.since >= tick1.ts

    def test_vertex_boundary_without_match(self):
        """Vertex boundary with no match fires on any fact of that kind."""
        v = Vertex("batch")
        v.register("metric", [], lambda s, p: [*s, p])
        v.register_vertex_boundary("flush")

        v.receive(fact("metric", value=1))
        v.receive(fact("metric", value=2))
        tick = v.receive(fact("flush"))

        assert tick is not None
        assert tick.payload["metric"] == [{"value": 1}, {"value": 2}]

    def test_vertex_boundary_conflicts_with_loop_boundary(self):
        """Can't register vertex boundary for a kind already claimed by a loop."""
        v = Vertex()
        v.register("metric", 0, sum_fold, boundary="flush")
        with pytest.raises(ValueError, match="already registered"):
            v.register_vertex_boundary("flush")

    def test_vertex_boundary_stores_tick(self, tmp_path):
        from engine.sqlite_store import SqliteStore

        store = SqliteStore(
            path=tmp_path / "test.db",
            serialize=Fact.to_dict,
            deserialize=Fact.from_dict,
        )
        v = Vertex("project", store=store)
        v.register("session", {}, lambda s, p: {**s, p["name"]: p})
        v.register_vertex_boundary("session", match=(("status", "closed"),))

        v.receive(fact("session", name="test", status="open"))
        v.receive(fact("session", name="test", status="closed"))

        ticks = store.ticks_since(0)
        assert len(ticks) == 1
        assert ticks[0].name == "project"
        assert "session" in ticks[0].payload
        assert "_boundary" in ticks[0].payload
        store.close()


class TestPredicateBoundary:
    """Predicate boundaries: fire when fold state meets conditions."""

    def test_condition_fires_when_met(self):
        """Boundary fires when fold target exceeds threshold."""
        from lang.ast import BoundaryCondition
        from engine.loop import Loop
        from engine.projection import Projection

        v = Vertex("weather")
        loop = Loop(
            name="reading",
            projection=Projection({"high": 0}, fold=lambda s, p: {**s, "high": max(s["high"], p.get("temp", 0))}),
            boundary_kind="reading",
            boundary_conditions=(BoundaryCondition(target="high", op=">=", value=80),),
            reset=True,
        )
        v.register_loop(loop)

        # Below threshold — no tick
        tick = v.receive(fact("reading", temp=75))
        assert tick is None

        # At threshold — fires
        tick = v.receive(fact("reading", temp=82))
        assert tick is not None
        assert tick.payload["high"] == 82

    def test_condition_not_met_no_fire(self):
        """Boundary suppressed when condition not met."""
        from lang.ast import BoundaryCondition
        from engine.loop import Loop
        from engine.projection import Projection

        v = Vertex("weather")
        loop = Loop(
            name="reading",
            projection=Projection({"high": 0}, fold=lambda s, p: {**s, "high": max(s["high"], p.get("temp", 0))}),
            boundary_kind="reading",
            boundary_conditions=(BoundaryCondition(target="high", op=">=", value=100),),
            reset=True,
        )
        v.register_loop(loop)

        tick = v.receive(fact("reading", temp=75))
        assert tick is None
        tick = v.receive(fact("reading", temp=82))
        assert tick is None
        # State still accumulates
        assert v.state("reading")["high"] == 82

    def test_multiple_conditions_and_semantics(self):
        """All conditions must be true (AND)."""
        from lang.ast import BoundaryCondition
        from engine.loop import Loop
        from engine.projection import Projection

        def weather_fold(state, p):
            return {
                "high": max(state["high"], p.get("temp", 0)),
                "humidity": p.get("humidity", state["humidity"]),
            }

        v = Vertex("weather")
        loop = Loop(
            name="reading",
            projection=Projection({"high": 0, "humidity": 0}, fold=weather_fold),
            boundary_kind="reading",
            boundary_conditions=(
                BoundaryCondition(target="high", op=">=", value=80),
                BoundaryCondition(target="humidity", op=">", value=60),
            ),
            reset=True,
        )
        v.register_loop(loop)

        # High but not humid — no fire
        tick = v.receive(fact("reading", temp=85, humidity=50))
        assert tick is None

        # Humid but not hot (state reset? no — no fire happened, state persists)
        # Actually high is still 85 from previous, humidity now 70
        tick = v.receive(fact("reading", temp=60, humidity=70))
        assert tick is not None  # high=85 >= 80 AND humidity=70 > 60

    def test_condition_reset_cycle(self):
        """After fire with reset=True, conditions start fresh."""
        from lang.ast import BoundaryCondition
        from engine.loop import Loop
        from engine.projection import Projection

        v = Vertex("weather")
        loop = Loop(
            name="reading",
            projection=Projection({"high": 0}, fold=lambda s, p: {**s, "high": max(s["high"], p.get("temp", 0))}),
            boundary_kind="reading",
            boundary_conditions=(BoundaryCondition(target="high", op=">=", value=80),),
            reset=True,
        )
        v.register_loop(loop)

        # Fire once
        tick = v.receive(fact("reading", temp=85))
        assert tick is not None

        # After reset, high is back to 0 — below threshold
        tick = v.receive(fact("reading", temp=70))
        assert tick is None
        assert v.state("reading")["high"] == 70

        # Exceeds again — fires again
        tick = v.receive(fact("reading", temp=90))
        assert tick is not None

    def test_condition_with_match(self):
        """Conditions compose with payload match — both must pass."""
        from lang.ast import BoundaryCondition
        from engine.loop import Loop
        from engine.projection import Projection

        v = Vertex("weather")
        loop = Loop(
            name="reading",
            projection=Projection({"high": 0}, fold=lambda s, p: {**s, "high": max(s["high"], p.get("temp", 0))}),
            boundary_kind="alert",
            boundary_match=(("source", "outdoor"),),
            boundary_conditions=(BoundaryCondition(target="high", op=">=", value=80),),
            reset=True,
        )
        v.register_loop(loop)

        v.receive(fact("reading", temp=85))

        # Wrong payload match — no fire even though condition met
        tick = v.receive(fact("alert", source="indoor"))
        assert tick is None

        # Right payload match + condition met — fires
        tick = v.receive(fact("alert", source="outdoor"))
        assert tick is not None

    def test_vertex_level_condition(self):
        """Vertex-level boundary with conditions checks routed loop state."""
        from lang.ast import BoundaryCondition

        v = Vertex("monitor")
        v.register("metric", {"high": 0}, lambda s, p: {**s, "high": max(s["high"], p.get("value", 0))})
        v.register_vertex_boundary(
            "metric",
            conditions=(BoundaryCondition(target="high", op=">=", value=100),),
        )

        # Below threshold
        tick = v.receive(fact("metric", value=50))
        assert tick is None

        # Above threshold — vertex-level fires (snapshots all loops)
        tick = v.receive(fact("metric", value=150))
        assert tick is not None
        assert "metric" in tick.payload

    def test_condition_string_equality(self):
        """String conditions use == for non-numeric comparison."""
        from lang.ast import BoundaryCondition
        from engine.loop import Loop
        from engine.projection import Projection

        v = Vertex("status")
        loop = Loop(
            name="check",
            projection=Projection({"status": "unknown"}, fold=lambda s, p: {**s, "status": p.get("status", s["status"])}),
            boundary_kind="check",
            boundary_conditions=(BoundaryCondition(target="status", op="==", value="critical"),),
            reset=True,
        )
        v.register_loop(loop)

        tick = v.receive(fact("check", status="ok"))
        assert tick is None

        tick = v.receive(fact("check", status="critical"))
        assert tick is not None

    def test_invalid_operator_rejected(self):
        """BoundaryCondition rejects invalid operators at construction."""
        from lang.ast import BoundaryCondition

        with pytest.raises(ValueError, match="Invalid condition operator"):
            BoundaryCondition(target="high", op="~=", value=80)


class TestVertexReplay:
    """Replay rebuilds fold state from stored facts."""

    def test_replay_rebuilds_state(self, tmp_path):
        from engine.sqlite_store import SqliteStore

        store = SqliteStore(
            path=tmp_path / "test.db",
            serialize=Fact.to_dict,
            deserialize=Fact.from_dict,
        )
        # First vertex: receive facts and close
        v1 = Vertex("project", store=store)
        v1.register("decision", {}, lambda s, p: {**s, p["topic"]: p})
        v1.receive(fact("decision", topic="auth", position="JWT"))
        v1.receive(fact("decision", topic="store", position="SQLite"))
        store.close()

        # Second vertex: fresh, same store — replay should rebuild
        store2 = SqliteStore(
            path=tmp_path / "test.db",
            serialize=Fact.to_dict,
            deserialize=Fact.from_dict,
        )
        v2 = Vertex("project", store=store2)
        v2.register("decision", {}, lambda s, p: {**s, p["topic"]: p})
        count = v2.replay()

        assert count == 2
        assert v2.state("decision") == {
            "auth": {"topic": "auth", "position": "JWT"},
            "store": {"topic": "store", "position": "SQLite"},
        }
        store2.close()

    def test_replay_does_not_fire_boundaries(self, tmp_path):
        from engine.sqlite_store import SqliteStore

        store = SqliteStore(
            path=tmp_path / "test.db",
            serialize=Fact.to_dict,
            deserialize=Fact.from_dict,
        )
        # Store a session open + close
        v1 = Vertex("project", store=store)
        v1.register("session", {}, lambda s, p: {**s, p["name"]: p})
        v1.register_vertex_boundary("session", match=(("status", "closed"),))
        v1.receive(fact("session", name="s1", status="open"))
        v1.receive(fact("session", name="s1", status="closed"))
        store.close()

        # Replay should NOT fire the boundary again
        store2 = SqliteStore(
            path=tmp_path / "test.db",
            serialize=Fact.to_dict,
            deserialize=Fact.from_dict,
        )
        v2 = Vertex("project", store=store2)
        v2.register("session", {}, lambda s, p: {**s, p["name"]: p})
        v2.register_vertex_boundary("session", match=(("status", "closed"),))
        v2.replay()

        # Only 1 tick from v1, not a second from replay
        ticks = store2.ticks_since(0)
        assert len(ticks) == 1
        store2.close()

    def test_replay_then_new_boundary_fires_with_full_state(self, tmp_path):
        """The key test: replay + new fact = tick with accumulated state."""
        from engine.sqlite_store import SqliteStore

        store = SqliteStore(
            path=tmp_path / "test.db",
            serialize=Fact.to_dict,
            deserialize=Fact.from_dict,
        )
        # Session 1: emit decisions
        v1 = Vertex("project", store=store)
        v1.register("decision", {}, lambda s, p: {**s, p["topic"]: p})
        v1.register("session", {}, lambda s, p: {**s, p["name"]: p})
        v1.register_vertex_boundary("session", match=(("status", "closed"),))
        v1.receive(fact("decision", topic="auth", position="JWT"))
        v1.receive(fact("session", name="s1", status="open"))
        store.close()

        # Session 2: fresh vertex, replay, then close
        store2 = SqliteStore(
            path=tmp_path / "test.db",
            serialize=Fact.to_dict,
            deserialize=Fact.from_dict,
        )
        v2 = Vertex("project", store=store2)
        v2.register("decision", {}, lambda s, p: {**s, p["topic"]: p})
        v2.register("session", {}, lambda s, p: {**s, p["name"]: p})
        v2.register_vertex_boundary("session", match=(("status", "closed"),))
        v2.replay()

        # Now close the session — tick should carry the decision from session 1
        tick = v2.receive(fact("session", name="s1", status="closed"))
        assert tick is not None
        assert tick.payload["decision"]["auth"]["position"] == "JWT"
        assert tick.payload["session"]["s1"]["status"] == "closed"
        store2.close()

    def test_replay_period_start_bridges_sessions(self, tmp_path):
        """Since field tracks the previous boundary, not the first-ever fact.

        Without this fix, one-shot CLI invocations set since to the first
        fact in history (replay sets period_start). With the fix, replay
        initializes period_start from the last stored tick, so subsequent
        boundaries produce ticks with since pointing to the previous boundary.
        """
        from engine.sqlite_store import SqliteStore

        db_path = tmp_path / "test.db"

        # Session 1: emit some facts and close — produces first tick
        store1 = SqliteStore(path=db_path, serialize=Fact.to_dict, deserialize=Fact.from_dict)
        v1 = Vertex("project", store=store1)
        v1.register("decision", {}, lambda s, p: {**s, p["topic"]: p})
        v1.register("session", {}, lambda s, p: {**s, p["name"]: p})
        v1.register_vertex_boundary("session", match=(("status", "closed"),))
        v1.receive(fact("decision", topic="auth", position="JWT"))
        tick1 = v1.receive(fact("session", name="s1", status="closed"))
        assert tick1 is not None
        store1.close()

        # Session 2: fresh vertex, replay, emit new facts, close
        store2 = SqliteStore(path=db_path, serialize=Fact.to_dict, deserialize=Fact.from_dict)
        v2 = Vertex("project", store=store2)
        v2.register("decision", {}, lambda s, p: {**s, p["topic"]: p})
        v2.register("session", {}, lambda s, p: {**s, p["name"]: p})
        v2.register_vertex_boundary("session", match=(("status", "closed"),))
        v2.replay()

        v2.receive(fact("decision", topic="deploy", position="k8s"))
        tick2 = v2.receive(fact("session", name="s2", status="closed"))
        assert tick2 is not None

        # The critical assertion: tick2.since should be tick1.ts,
        # NOT the timestamp of the first-ever fact
        assert tick2.since == tick1.ts

        # tick2 period is [tick1.ts, tick2.ts] — not [first_fact, tick2.ts]
        assert tick2.since > tick1.since  # tick1.since < tick1.ts always
        store2.close()


class TestParseAtVertex:
    """Per-kind parse pipelines applied at Vertex.receive() time."""

    def test_select_filters_payload(self):
        """Parse pipeline with Select filters payload fields before fold."""
        from atoms import Select as RuntimeSelect

        v = Vertex()
        v.register("exchange", [], collect_fold)
        v.set_parse_pipelines({
            "exchange": [RuntimeSelect("prompt", "response")],
        })

        v.receive(fact("exchange", prompt="hello", response="world", model="gpt-4", extra="noise"))
        state = v.state("exchange")
        assert len(state) == 1
        assert state[0] == {"prompt": "hello", "response": "world"}

    def test_parse_preserves_unregistered_kinds(self):
        """Facts for kinds without parse pipelines pass through unmodified."""
        from atoms import Select as RuntimeSelect

        v = Vertex()
        v.register("exchange", [], collect_fold)
        v.register("other", [], collect_fold)
        v.set_parse_pipelines({
            "exchange": [RuntimeSelect("prompt")],
        })

        v.receive(fact("other", prompt="hello", extra="kept"))
        state = v.state("other")
        assert len(state) == 1
        assert "extra" in state[0]

    def test_flatten_adds_derived_field(self):
        """Flatten parse op adds a text field derived from array elements."""
        from atoms import Flatten as RuntimeFlatten

        v = Vertex()
        v.register("exchange", [], collect_fold)
        v.set_parse_pipelines({
            "exchange": [RuntimeFlatten(
                field="tool_calls",
                into="tool_text",
                extract=("name", "input"),
            )],
        })

        v.receive(fact("exchange", tool_calls=[
            {"name": "read_file", "input": "foo.py"},
            {"name": "write_file", "input": "bar.py"},
        ], prompt="hello"))

        state = v.state("exchange")
        assert len(state) == 1
        assert "tool_text" in state[0]
        assert "read_file" in state[0]["tool_text"]
        assert "write_file" in state[0]["tool_text"]
        # Original field preserved
        assert "tool_calls" in state[0]
        assert "prompt" in state[0]

    def test_parse_with_route(self):
        """Parse pipeline applies when fact kind is resolved via route."""
        from atoms import Select as RuntimeSelect

        v = Vertex()
        v.register("exchange", [], collect_fold)
        v.set_routes({"exchange.*": "exchange"})
        v.set_parse_pipelines({
            "exchange": [RuntimeSelect("prompt")],
        })

        v.receive(fact("exchange.siftd", prompt="hello", model="gpt-4"))
        state = v.state("exchange")
        assert len(state) == 1
        assert state[0] == {"prompt": "hello"}

    def test_integration_parse_then_fold(self):
        """End-to-end: parse transforms payload, then fold accumulates."""
        from atoms import Select as RuntimeSelect

        def upsert_fold(state, payload):
            key = payload.get("topic", "unknown")
            return {**state, key: payload}

        v = Vertex()
        v.register("decision", {}, upsert_fold)
        v.set_parse_pipelines({
            "decision": [RuntimeSelect("topic", "position")],
        })

        v.receive(fact("decision", topic="auth", position="JWT", extra="noise"))
        v.receive(fact("decision", topic="deploy", position="k8s", tags=["prod"]))

        state = v.state("decision")
        assert "auth" in state
        assert state["auth"] == {"topic": "auth", "position": "JWT"}
        assert "deploy" in state
        assert state["deploy"] == {"topic": "deploy", "position": "k8s"}
        # "extra" and "tags" were stripped by Select

    def test_parse_none_skips_fold(self):
        """When parse returns None, the fact is dropped — not silently passed through."""
        from atoms import Where

        v = Vertex()
        v.register("event", [], collect_fold)
        # Where filter: only pass through facts with status=active
        v.set_parse_pipelines({
            "event": [Where(path="status", op="equals", value="active")],
        })

        v.receive(fact("event", status="active", name="a"))
        v.receive(fact("event", status="closed", name="b"))  # should be dropped
        v.receive(fact("event", status="active", name="c"))

        state = v.state("event")
        assert len(state) == 2
        assert state[0]["name"] == "a"
        assert state[1]["name"] == "c"

    def test_parse_none_still_stores(self):
        """Rejected facts are still stored (for audit) even though fold is skipped."""
        from atoms import Where

        store = EventStore()
        v = Vertex("test", store=store)
        v.register("event", [], collect_fold)
        v.set_parse_pipelines({
            "event": [Where(path="status", op="equals", value="active")],
        })

        v.receive(fact("event", status="closed", name="dropped"))

        # Fold should be empty — fact was rejected by parse
        assert v.state("event") == []
        # But store should have the fact
        assert len(list(store.since(0))) == 1
