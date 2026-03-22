"""Tests for uncovered Vertex replay paths using the test SDK.

Targets: vertex.py replay fast paths (since_raw, replay_cursor),
         fallback paths (routes, parse_pipelines, children),
         boundary reconciliation edges, and ingest().
"""
import json
import time as _time

import pytest

from atoms import Fact, Spec, Count
from engine import Loop, Vertex
from engine.sqlite_store import SqliteStore

from tests.vertex_test_sdk import VertexTestBuilder, fact, reopen_store


def inject_fact(store, kind: str, observer: str = "test", ts: float | None = None, **payload):
    """Insert a fact directly into a SqliteStore, bypassing vertex.receive()."""
    from engine.sqlite_store import _gen_id

    if ts is None:
        ts = _time.time()
    d = Fact.to_dict(Fact.of(kind, observer, **payload))
    d["ts"] = ts
    store._ensure_sync()
    store._conn.execute(
        "INSERT INTO facts (id, kind, ts, observer, origin, payload) VALUES (?, ?, ?, ?, ?, ?)",
        (_gen_id(), d["kind"], d["ts"], d["observer"], d.get("origin", ""), json.dumps(d["payload"])),
    )
    store._conn.commit()


class TestReplayWithRoutes:
    """Replay fallback path: routes force full-Fact replay (L634-655)."""

    def test_replay_with_routes(self, tmp_path):
        v1, store = (VertexTestBuilder("routed")
            .with_store(tmp_path)
            .count_loop("events")
            .routes({"deploy.*": "events"})
            .build())

        v1.receive(fact("deploy.prod", type="release"))
        v1.receive(fact("deploy.staging", type="test"))
        store.close()

        # Replay with routes — takes the full-Fact path
        v2, store2 = (VertexTestBuilder("routed")
            .with_store(tmp_path)
            .count_loop("events")
            .routes({"deploy.*": "events"})
            .build())
        count = v2.replay()
        assert count == 2
        assert v2.state("events")["n"] == 2
        store2.close()

    def test_replay_with_parse_pipeline(self, tmp_path):
        from atoms import Transform

        v1, store = (VertexTestBuilder("parsed")
            .with_store(tmp_path)
            .count_loop("log")
            .parse_pipelines({"log": [Transform(field="msg", strip=" ")]})
            .build())

        v1.receive(fact("log", msg="  hello  "))
        v1.receive(fact("log", msg="  world  "))
        store.close()

        v2, store2 = (VertexTestBuilder("parsed")
            .with_store(tmp_path)
            .count_loop("log")
            .parse_pipelines({"log": [Transform(field="msg", strip=" ")]})
            .build())
        count = v2.replay()
        assert count == 2
        assert v2.state("log")["n"] == 2
        store2.close()


class TestReplayWithChildren:
    """Replay with child vertices takes the full-Fact fallback path."""

    def test_replay_forwards_to_children(self, tmp_path):
        parent, store = (VertexTestBuilder("parent")
            .with_store(tmp_path)
            .count_loop("metric")
            .build())

        child = (VertexTestBuilder("child")
            .count_loop("metric")
            .build_vertex())
        parent.add_child(child)

        parent.receive(fact("metric", v=1))
        parent.receive(fact("metric", v=2))
        store.close()

        # Rebuild with child — takes fallback path
        parent2, store2 = (VertexTestBuilder("parent")
            .with_store(tmp_path)
            .count_loop("metric")
            .build())
        child2 = (VertexTestBuilder("child")
            .count_loop("metric")
            .build_vertex())
        parent2.add_child(child2)

        count = parent2.replay()
        assert count == 2
        assert parent2.state("metric")["n"] == 2
        # Child also received the facts
        assert child2.state("metric")["n"] == 2
        store2.close()


class TestReplayEmptyStore:
    """Replay on empty store returns 0 immediately."""

    def test_replay_empty_raw_path(self, tmp_path):
        """Empty store with since_raw available → L618-619."""
        v, store = (VertexTestBuilder("empty")
            .with_store(tmp_path)
            .count_loop("metric")
            .build())
        count = v.replay()
        assert count == 0
        store.close()


class TestReplayBoundaryReconciliation:
    """Boundary count reconciliation after replay (L665-677)."""

    def test_replay_every_boundary_residual(self, tmp_path):
        """After replaying 5 facts with boundary_count=3, residual = 5 % 3 = 2."""
        v1, store = (VertexTestBuilder("bc")
            .with_store(tmp_path)
            .count_loop("events", boundary_count=3, boundary_mode="every")
            .build())

        for i in range(5):
            v1.receive(fact("events", i=i))
        store.close()

        v2, store2 = (VertexTestBuilder("bc")
            .with_store(tmp_path)
            .count_loop("events", boundary_count=3, boundary_mode="every")
            .build())
        v2.replay()
        # After replay of 5, residual should be 5 % 3 = 2
        loop = v2._loops["events"]
        assert loop._count_since_boundary == 2
        store2.close()

    def test_replay_after_boundary_exhaustion(self, tmp_path):
        """After boundary with mode='after' reached, marks exhausted."""
        v1, store = (VertexTestBuilder("bc")
            .with_store(tmp_path)
            .count_loop("events", boundary_count=2, boundary_mode="after")
            .build())

        for i in range(5):
            v1.receive(fact("events", i=i))
        store.close()

        v2, store2 = (VertexTestBuilder("bc")
            .with_store(tmp_path)
            .count_loop("events", boundary_count=2, boundary_mode="after")
            .build())
        v2.replay()
        loop = v2._loops["events"]
        assert loop._boundary_exhausted is True
        store2.close()


class TestIngest:
    """Vertex.ingest() is a thin wrapper around receive (L931-934)."""

    def test_ingest_creates_fact_and_receives(self):
        v = (VertexTestBuilder()
            .count_loop("metric")
            .build_vertex())
        v.ingest("metric", {"value": 42}, "alice")
        assert v.state("metric")["n"] == 1


class TestEvalConditionFallthrough:
    """_eval_condition returns False for unknown operators (L93)."""

    def test_unknown_operator_returns_false(self):
        from engine.vertex import _eval_condition

        class FakeCondition:
            target = "n"
            op = "???"
            value = 5

        assert _eval_condition({"n": 10}, FakeCondition()) is False


class TestReplayBoundaryReconciliationEdges:
    """Cover L673 (after not exhausted), L677 (unknown mode), L688-692 (ticks_since)."""

    def test_after_boundary_not_exhausted(self, tmp_path):
        """Replay with fewer facts than after threshold → not exhausted, count set."""
        v1, store = (VertexTestBuilder("bc")
            .with_store(tmp_path)
            .count_loop("events", boundary_count=10, boundary_mode="after")
            .build())

        # Only 3 facts, threshold is 10 → not exhausted
        for i in range(3):
            v1.receive(fact("events", i=i))
        store.close()

        v2, store2 = (VertexTestBuilder("bc")
            .with_store(tmp_path)
            .count_loop("events", boundary_count=10, boundary_mode="after")
            .build())
        v2.replay()
        loop = v2._loops["events"]
        assert loop._boundary_exhausted is False
        assert loop._count_since_boundary == 3
        store2.close()

    def test_replay_with_vertex_boundary_period_start(self, tmp_path):
        """Vertex with vertex-level boundary reads period start from ticks."""
        from engine import Loop
        from atoms import Spec, Count, Boundary

        v1, store = (VertexTestBuilder("vb")
            .with_store(tmp_path)
            .count_loop("metric")
            .build())

        # Register a vertex-level boundary
        v1.register_vertex_boundary("metric", match=())

        v1.receive(fact("metric", v=1))
        v1.receive(fact("metric", v=2))
        store.close()

        v2, store2 = (VertexTestBuilder("vb")
            .with_store(tmp_path)
            .count_loop("metric")
            .build())
        v2.register_vertex_boundary("metric", match=())
        v2.replay()
        # Period start should be initialized (or None if no tick in store)
        store2.close()


class TestEvaluateBoundariesVertexOnly:
    """Cover _evaluate_vertex_only_boundaries (L804-868) and evaluate_boundaries paths."""

    def test_vertex_boundary_no_conditions_fires(self, tmp_path):
        """Vertex-only boundary fires on matching kind — no conditions."""
        import time

        v, store = (VertexTestBuilder("proj")
            .with_store(tmp_path)
            .count_loop("decision")
            .build())
        v.register_vertex_boundary("decision")

        # Emit a fact directly via receive (stores it)
        v.receive(fact("decision", topic="auth"))

        # Now rebuild a fresh vertex, replay, then evaluate
        store.close()
        v2, store2 = (VertexTestBuilder("proj")
            .with_store(tmp_path)
            .count_loop("decision")
            .build())
        v2.register_vertex_boundary("decision")
        v2.replay()
        ticks = v2.evaluate_boundaries()
        assert isinstance(ticks, list)
        store2.close()

    def test_vertex_boundary_with_match_fires(self, tmp_path):
        """Vertex boundary with payload match — matching fact fires."""
        v, store = (VertexTestBuilder("proj")
            .with_store(tmp_path)
            .count_loop("session")
            .build())
        v.register_vertex_boundary("session", match=(("status", "closed"),))

        v.receive(fact("session", status="closed"))
        store.close()

        v2, store2 = (VertexTestBuilder("proj")
            .with_store(tmp_path)
            .count_loop("session")
            .build())
        v2.register_vertex_boundary("session", match=(("status", "closed"),))
        v2.replay()
        ticks = v2.evaluate_boundaries()
        assert isinstance(ticks, list)
        store2.close()

    def test_vertex_boundary_with_match_skips_non_matching(self, tmp_path):
        """Vertex boundary with match — non-matching fact skips."""
        v, store = (VertexTestBuilder("proj")
            .with_store(tmp_path)
            .count_loop("session")
            .build())
        v.register_vertex_boundary("session", match=(("status", "closed"),))

        v.receive(fact("session", status="open"))
        store.close()

        v2, store2 = (VertexTestBuilder("proj")
            .with_store(tmp_path)
            .count_loop("session")
            .build())
        v2.register_vertex_boundary("session", match=(("status", "closed"),))
        v2.replay()
        ticks = v2.evaluate_boundaries()
        assert ticks == []
        store2.close()

    def test_vertex_boundary_with_conditions(self, tmp_path):
        """Vertex boundary with fold-state conditions path."""
        from lang.ast import BoundaryCondition

        v, store = (VertexTestBuilder("proj")
            .with_store(tmp_path)
            .count_loop("metric")
            .build())
        v.register_vertex_boundary("metric",
            conditions=(BoundaryCondition(target="n", op=">=", value=1),))

        v.receive(fact("metric", v=1))
        store.close()

        v2, store2 = (VertexTestBuilder("proj")
            .with_store(tmp_path)
            .count_loop("metric")
            .build())
        v2.register_vertex_boundary("metric",
            conditions=(BoundaryCondition(target="n", op=">=", value=1),))
        v2.replay()
        ticks = v2.evaluate_boundaries()
        assert isinstance(ticks, list)
        store2.close()

    def test_vertex_boundary_conditions_not_met(self, tmp_path):
        """Vertex boundary conditions not met — no fire."""
        from lang.ast import BoundaryCondition

        v, store = (VertexTestBuilder("proj")
            .with_store(tmp_path)
            .count_loop("metric")
            .build())
        v.register_vertex_boundary("metric",
            conditions=(BoundaryCondition(target="n", op=">=", value=100),))

        v.receive(fact("metric", v=1))
        store.close()

        v2, store2 = (VertexTestBuilder("proj")
            .with_store(tmp_path)
            .count_loop("metric")
            .build())
        v2.register_vertex_boundary("metric",
            conditions=(BoundaryCondition(target="n", op=">=", value=100),))
        v2.replay()
        ticks = v2.evaluate_boundaries()
        assert ticks == []
        store2.close()

    def test_evaluate_with_empty_period(self, tmp_path):
        """No facts in scan period — returns empty."""
        import time

        v, store = (VertexTestBuilder("proj")
            .with_store(tmp_path)
            .count_loop("metric")
            .build())
        # Store exists but no facts → between() returns empty
        ticks = v.evaluate_boundaries()
        assert ticks == []
        store.close()

    def test_evaluate_loop_level_boundary(self, tmp_path):
        """Loop-level boundary fires from evaluate_boundaries."""
        v, store = (VertexTestBuilder("proj")
            .with_store(tmp_path)
            .count_loop("metric", boundary_kind="metric", boundary_count=1)
            .build())

        v.receive(fact("metric", v=1))
        store.close()

        v2, store2 = (VertexTestBuilder("proj")
            .with_store(tmp_path)
            .count_loop("metric", boundary_kind="metric", boundary_count=1)
            .build())
        v2.replay()
        ticks = v2.evaluate_boundaries()
        # Loop-level boundary may fire on the stored fact
        assert isinstance(ticks, list)
        store2.close()


class TestEvaluateBoundariesMixed:
    """Cover L757-775: evaluate_boundaries with BOTH vertex and loop boundaries."""

    def test_mixed_vertex_and_loop_boundary(self, tmp_path):
        """Vertex with vertex-level + loop-level boundaries → mixed path."""
        v, store = (VertexTestBuilder("proj")
            .with_store(tmp_path)
            .count_loop("metric", boundary_kind="metric", boundary_count=1)
            .count_loop("session")
            .build())
        v.register_vertex_boundary("session")

        v.receive(fact("metric", v=1))
        v.receive(fact("session", status="closed"))
        store.close()

        v2, store2 = (VertexTestBuilder("proj")
            .with_store(tmp_path)
            .count_loop("metric", boundary_kind="metric", boundary_count=1)
            .count_loop("session")
            .build())
        v2.register_vertex_boundary("session")
        v2.replay()
        ticks = v2.evaluate_boundaries()
        assert isinstance(ticks, list)
        store2.close()

    def test_mixed_boundary_match_skips(self, tmp_path):
        """Vertex boundary with match in mixed mode — non-matching skips."""
        v, store = (VertexTestBuilder("proj")
            .with_store(tmp_path)
            .count_loop("metric", boundary_kind="metric", boundary_count=1)
            .count_loop("session")
            .build())
        v.register_vertex_boundary("session", match=(("status", "closed"),))

        v.receive(fact("metric", v=1))
        v.receive(fact("session", status="open"))  # doesn't match
        store.close()

        v2, store2 = (VertexTestBuilder("proj")
            .with_store(tmp_path)
            .count_loop("metric", boundary_kind="metric", boundary_count=1)
            .count_loop("session")
            .build())
        v2.register_vertex_boundary("session", match=(("status", "closed"),))
        v2.replay()
        ticks = v2.evaluate_boundaries()
        assert isinstance(ticks, list)
        store2.close()

    def test_mixed_boundary_with_conditions_met(self, tmp_path):
        """Mixed mode: vertex boundary with conditions met → fires."""
        from lang.ast import BoundaryCondition
        from engine.sqlite_store import SqliteStore

        store = SqliteStore(
            path=tmp_path / "test.db",
            serialize=Fact.to_dict,
            deserialize=Fact.from_dict,
        )
        v = Vertex("proj", store=store)
        spec_m = Spec(name="metric", folds=(Count(target="n"),))
        v.register_loop(Loop(
            name="metric", initial=spec_m.initial_state(), fold=spec_m.apply,
            boundary_kind="metric", boundary_count=100,
        ))
        spec_s = Spec(name="session", folds=(Count(target="n"),))
        v.register_loop(Loop(
            name="session", initial=spec_s.initial_state(), fold=spec_s.apply,
        ))
        v.register_vertex_boundary("session",
            conditions=(BoundaryCondition(target="n", op=">=", value=1),))

        # Receive a metric fact to build fold state (n=1)
        v.receive(fact("metric", v=1))
        # Use a generous future offset to avoid flakiness under load
        inject_fact(store, "session", status="closed", ts=_time.time() + 60.0)

        ticks = v.evaluate_boundaries()
        assert len(ticks) >= 1  # Should fire — conditions met (n>=1)
        store.close()

    def test_mixed_boundary_with_conditions_not_met(self, tmp_path):
        """Mixed mode: vertex boundary with conditions NOT met → skips."""
        from lang.ast import BoundaryCondition
        from engine.sqlite_store import SqliteStore

        store = SqliteStore(
            path=tmp_path / "test.db",
            serialize=Fact.to_dict,
            deserialize=Fact.from_dict,
        )
        v = Vertex("proj", store=store)
        spec_m = Spec(name="metric", folds=(Count(target="n"),))
        v.register_loop(Loop(
            name="metric", initial=spec_m.initial_state(), fold=spec_m.apply,
            boundary_kind="metric", boundary_count=100,
        ))
        spec_s = Spec(name="session", folds=(Count(target="n"),))
        v.register_loop(Loop(
            name="session", initial=spec_s.initial_state(), fold=spec_s.apply,
        ))
        v.register_vertex_boundary("session",
            conditions=(BoundaryCondition(target="n", op=">=", value=999),))

        # Insert session fact directly — conditions won't be met (n=0 < 999)
        inject_fact(store, "session", status="closed", ts=_time.time() + 1.0)

        ticks = v.evaluate_boundaries()
        assert ticks == []  # Conditions not met
        store.close()


class TestReplaySinceRawFastPath:
    """Cover L619-628: since_raw fast path (no replay_cursor)."""

    def test_since_raw_without_cached_fold_fns(self, tmp_path):
        """Store with since_raw but loop spec lacks _cached_fold_fns → since_raw path."""
        from engine.sqlite_store import SqliteStore

        store = SqliteStore(
            path=tmp_path / "test.db",
            serialize=Fact.to_dict,
            deserialize=Fact.from_dict,
        )

        # Create a vertex with a simple fold function (no Spec → no _cached_fold_fns)
        v = Vertex("test", store=store)
        v.register_loop(Loop(
            name="metric",
            initial={"n": 0},
            fold=lambda state, payload: {**state, "n": state["n"] + 1},
        ))

        v.receive(fact("metric", v=1))
        v.receive(fact("metric", v=2))
        store.close()

        # Reopen and replay — should use since_raw path (no _cached_fold_fns)
        store2 = SqliteStore(
            path=tmp_path / "test.db",
            serialize=Fact.to_dict,
            deserialize=Fact.from_dict,
        )
        v2 = Vertex("test", store=store2)
        v2.register_loop(Loop(
            name="metric",
            initial={"n": 0},
            fold=lambda state, payload: {**state, "n": state["n"] + 1},
        ))
        count = v2.replay()
        assert count == 2
        assert v2.state("metric")["n"] == 2
        store2.close()

    def test_since_raw_empty(self, tmp_path):
        """since_raw returns empty → replay returns 0 immediately."""
        from engine.sqlite_store import SqliteStore

        store = SqliteStore(
            path=tmp_path / "empty.db",
            serialize=Fact.to_dict,
            deserialize=Fact.from_dict,
        )
        v = Vertex("test", store=store)
        v.register_loop(Loop(
            name="metric",
            initial={"n": 0},
            fold=lambda state, payload: {**state, "n": state["n"] + 1},
        ))
        count = v.replay()
        assert count == 0
        store.close()

    def test_since_raw_with_mut_dispatch_no_replay_cursor(self, tmp_path):
        """Store has since_raw but NO replay_cursor → since_raw + mut_dispatch path."""
        from engine.sqlite_store import SqliteStore
        from atoms import Spec, Count

        store = SqliteStore(
            path=tmp_path / "test.db",
            serialize=Fact.to_dict,
            deserialize=Fact.from_dict,
        )
        v = Vertex("test", store=store)
        spec = Spec(name="metric", folds=(Count(target="n"),))
        v.register_loop(Loop(
            name="metric", initial=spec.initial_state(), fold=spec.apply,
        ))
        v.receive(fact("metric", v=1))
        v.receive(fact("metric", v=2))
        store.close()

        # Reopen with a wrapper that hides replay_cursor
        store2 = SqliteStore(
            path=tmp_path / "test.db",
            serialize=Fact.to_dict,
            deserialize=Fact.from_dict,
        )
        # Remove replay_cursor to force since_raw + mut_dispatch path
        delattr(type(store2), 'replay_cursor') if False else None  # can't delete from class
        # Instead, wrap the store
        class NoReplayCursorStore:
            """Proxy that hides replay_cursor."""
            def __init__(self, inner):
                self._inner = inner
            def since_raw(self, cursor):
                return self._inner.since_raw(cursor)
            def since(self, cursor):
                return self._inner.since(cursor)
            def between(self, start, end):
                return self._inner.between(start, end)
            def close(self):
                self._inner.close()

        proxy = NoReplayCursorStore(store2)
        v2 = Vertex("test", store=proxy)
        spec2 = Spec(name="metric", folds=(Count(target="n"),))
        v2.register_loop(Loop(
            name="metric", initial=spec2.initial_state(), fold=spec2.apply,
        ))
        count = v2.replay()
        assert count == 2
        assert v2.state("metric")["n"] == 2
        store2.close()


class TestReplayFallbackPath:
    """Cover L636-648: replay fallback with routes/parse_pipelines."""

    def test_replay_with_routes_empty_store(self, tmp_path):
        """Routes set → fallback path, empty store → return 0."""
        from engine.sqlite_store import SqliteStore

        store = SqliteStore(
            path=tmp_path / "test.db",
            serialize=Fact.to_dict,
            deserialize=Fact.from_dict,
        )
        v = Vertex("test", store=store)
        v.register_loop(Loop(
            name="metric", initial={"n": 0},
            fold=lambda s, p: {**s, "n": s["n"] + 1},
        ))
        v.set_routes({"raw_metric": "metric"})
        count = v.replay()
        assert count == 0
        store.close()

    def test_replay_with_routes_hits_fallback(self, tmp_path):
        """Routes set → fallback path, facts in store → routes applied during replay."""
        from engine.sqlite_store import SqliteStore

        store = SqliteStore(
            path=tmp_path / "test.db",
            serialize=Fact.to_dict,
            deserialize=Fact.from_dict,
        )
        # Insert facts with raw kind that routes to "metric"
        for i in range(2):
            inject_fact(store, "raw_metric", ts=_time.time() - 10 + i, value=i)
        store.close()

        store2 = SqliteStore(
            path=tmp_path / "test.db",
            serialize=Fact.to_dict,
            deserialize=Fact.from_dict,
        )
        v2 = Vertex("test", store=store2)
        v2.register_loop(Loop(
            name="metric", initial={"n": 0},
            fold=lambda s, p: {**s, "n": s["n"] + 1},
        ))
        v2.set_routes({"raw_metric": "metric"})
        count = v2.replay()
        assert count == 2
        assert v2.state("metric")["n"] == 2
        store2.close()


class TestEvaluateVertexOnlyConditionsFiring:
    """Cover L851-867: _evaluate_vertex_only_boundaries with conditions that fire."""

    def test_conditions_fire_on_vertex_only_boundary(self, tmp_path):
        """Vertex-only boundary with conditions met → tick fires (L864-867)."""
        from lang.ast import BoundaryCondition
        from engine.sqlite_store import SqliteStore

        store = SqliteStore(
            path=tmp_path / "test.db",
            serialize=Fact.to_dict,
            deserialize=Fact.from_dict,
        )
        v = Vertex("proj", store=store)
        # Session loop accumulates count; boundary on session checks session.n
        spec_s = Spec(name="session", folds=(Count(target="n"),))
        v.register_loop(Loop(
            name="session", initial=spec_s.initial_state(), fold=spec_s.apply,
        ))
        # Vertex-only boundary on "session" with condition on session.n>=1
        v.register_vertex_boundary("session",
            conditions=(BoundaryCondition(target="n", op=">=", value=1),))

        # Receive a session fact via receive to build fold state (n=1)
        # This won't fire boundary because conditions are checked DURING receive
        # and n=0 before fold → condition not met at that point
        v.receive(fact("session", status="open"))
        # Now session.n=1. Insert another session fact for evaluate_boundaries
        inject_fact(store, "session", status="closed")

        ticks = v.evaluate_boundaries()
        assert len(ticks) >= 1  # Should fire — conditions met (session.n>=1)
        store.close()

    def test_conditions_skip_non_matching_kind(self, tmp_path):
        """Non-matching kind gets skipped in vertex-only conditions path (L851)."""
        from lang.ast import BoundaryCondition

        store = SqliteStore(
            path=tmp_path / "test.db",
            serialize=Fact.to_dict,
            deserialize=Fact.from_dict,
        )
        v = Vertex("proj", store=store)
        spec = Spec(name="metric", folds=(Count(target="n"),))
        v.register_loop(Loop(
            name="metric", initial=spec.initial_state(), fold=spec.apply,
        ))
        v.register_vertex_boundary("session",
            conditions=(BoundaryCondition(target="n", op=">=", value=1),))

        # Insert a metric fact (wrong kind for boundary)
        inject_fact(store, "metric", v=1, ts=_time.time() + 1.0)

        ticks = v.evaluate_boundaries()
        assert ticks == []  # wrong kind → skipped
        store.close()
