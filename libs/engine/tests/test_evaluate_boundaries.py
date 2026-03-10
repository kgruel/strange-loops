"""Tests for decoupled boundary evaluation — evaluate_boundaries().

Boundaries normally fire inside receive() when a matching fact arrives.
evaluate_boundaries() handles facts that arrived via external emit (between
vertex runs) — folded during replay but boundaries suppressed.
"""

from __future__ import annotations

from datetime import datetime, timezone

import pytest

from atoms import Fact
from engine import Vertex
from engine.loop import Loop
from engine.sqlite_store import SqliteStore


def _fact(kind: str, **payload) -> Fact:
    return Fact.of(kind, "test", **payload)


def _ts(epoch: float) -> datetime:
    return datetime.fromtimestamp(epoch, tz=timezone.utc)


class TestEvaluateBoundaries:
    """Core evaluate_boundaries tests."""

    def test_fires_for_externally_emitted_fact(self, tmp_path):
        """The key test: external emit + replay + evaluate = boundary fires."""
        store = SqliteStore(
            path=tmp_path / "test.db",
            serialize=Fact.to_dict,
            deserialize=Fact.from_dict,
        )

        # Session 1: register vertex, emit a task fact directly to store
        v1 = Vertex("orchestration", store=store)
        v1.register("task", {}, lambda s, p: {**s, p["name"]: p})
        v1.register_vertex_boundary("task", match=(("status", "open"),))
        v1.receive(_fact("task", name="job1", status="open"))
        # Boundary fires because fact arrived via receive()
        store.close()

        # Session 2: external emit — bypass vertex, write directly to store
        store2 = SqliteStore(
            path=tmp_path / "test.db",
            serialize=Fact.to_dict,
            deserialize=Fact.from_dict,
        )
        # Simulate external emit: append fact directly to store
        store2.append(Fact.of("task", "kyle", name="job2", status="open"))

        # New vertex, replay, evaluate
        v2 = Vertex("orchestration", store=store2)
        v2.register("task", {}, lambda s, p: {**s, p["name"]: p})
        v2.register_vertex_boundary("task", match=(("status", "open"),))
        v2.replay()

        # Fold state has both jobs, but boundaries didn't fire during replay
        assert "job2" in v2.state("task")

        ticks = v2.evaluate_boundaries()
        assert len(ticks) == 1
        assert ticks[0].payload["task"]["job2"]["status"] == "open"
        store2.close()

    def test_no_fire_when_no_matching_facts(self, tmp_path):
        """evaluate_boundaries returns empty when no facts match triggers."""
        store = SqliteStore(
            path=tmp_path / "test.db",
            serialize=Fact.to_dict,
            deserialize=Fact.from_dict,
        )
        v = Vertex("test", store=store)
        v.register("item", {}, lambda s, p: {**s, p.get("name", "x"): p})
        v.register_vertex_boundary("session", match=(("status", "closed"),))

        # Emit a non-boundary fact
        v.receive(_fact("item", name="thing"))
        store.close()

        # Replay in new vertex
        store2 = SqliteStore(
            path=tmp_path / "test.db",
            serialize=Fact.to_dict,
            deserialize=Fact.from_dict,
        )
        v2 = Vertex("test", store=store2)
        v2.register("item", {}, lambda s, p: {**s, p.get("name", "x"): p})
        v2.register_vertex_boundary("session", match=(("status", "closed"),))
        v2.replay()

        ticks = v2.evaluate_boundaries()
        assert ticks == []
        store2.close()

    def test_no_fire_without_store(self):
        """evaluate_boundaries is a no-op without a store."""
        v = Vertex("test")
        v.register("task", {}, lambda s, p: {**s, p["name"]: p})
        assert v.evaluate_boundaries() == []

    def test_loop_level_boundary_fires(self, tmp_path):
        """Loop-level (non-vertex) boundaries also fire on evaluate."""
        store = SqliteStore(
            path=tmp_path / "test.db",
            serialize=Fact.to_dict,
            deserialize=Fact.from_dict,
        )

        # External emit: task fact directly to store
        store.append(Fact.of("task", "kyle", name="job1", status="open"))

        v = Vertex("test", store=store)
        loop = Loop(
            name="task",
            initial={},
            fold=lambda s, p: {**s, p["name"]: p},
            boundary_kind="task",
            boundary_match=(("status", "open"),),
        )
        v.register_loop(loop)
        v.replay()

        ticks = v.evaluate_boundaries()
        assert len(ticks) == 1
        assert ticks[0].name == "task"
        store.close()

    def test_predicate_boundary_checks_fold_state(self, tmp_path):
        """Predicate boundaries evaluate fold-state conditions."""
        from lang.ast import BoundaryCondition

        store = SqliteStore(
            path=tmp_path / "test.db",
            serialize=Fact.to_dict,
            deserialize=Fact.from_dict,
        )

        # External emit: enough readings to meet threshold
        for i in range(5):
            store.append(Fact.of("reading", "sensor", value=str(i)))

        v = Vertex("test", store=store)
        loop = Loop(
            name="reading",
            initial={"items": [], "count": 0},
            fold=lambda s, p: {
                "items": [*s["items"], p],
                "count": s["count"] + 1,
            },
            boundary_kind="reading",
            boundary_conditions=(
                BoundaryCondition(target="count", op=">=", value="5"),
            ),
        )
        v.register_loop(loop)
        v.replay()

        # Fold state has count=5, boundary condition met
        assert v.state("reading")["count"] == 5

        ticks = v.evaluate_boundaries()
        assert len(ticks) == 1
        store.close()

    def test_predicate_not_met_no_fire(self, tmp_path):
        """Predicate boundary doesn't fire when fold-state condition isn't met."""
        from lang.ast import BoundaryCondition

        store = SqliteStore(
            path=tmp_path / "test.db",
            serialize=Fact.to_dict,
            deserialize=Fact.from_dict,
        )

        # Only 2 readings — threshold is 5
        for i in range(2):
            store.append(Fact.of("reading", "sensor", value=str(i)))

        v = Vertex("test", store=store)
        loop = Loop(
            name="reading",
            initial={"items": [], "count": 0},
            fold=lambda s, p: {
                "items": [*s["items"], p],
                "count": s["count"] + 1,
            },
            boundary_kind="reading",
            boundary_conditions=(
                BoundaryCondition(target="count", op=">=", value="5"),
            ),
        )
        v.register_loop(loop)
        v.replay()

        assert v.state("reading")["count"] == 2

        ticks = v.evaluate_boundaries()
        assert ticks == []
        store.close()

    def test_payload_match_filters(self, tmp_path):
        """Payload match conditions filter which facts trigger the boundary."""
        store = SqliteStore(
            path=tmp_path / "test.db",
            serialize=Fact.to_dict,
            deserialize=Fact.from_dict,
        )

        # One fact matches, one doesn't
        store.append(Fact.of("task", "kyle", name="job1", status="assigned"))
        store.append(Fact.of("task", "kyle", name="job2", status="open"))

        v = Vertex("test", store=store)
        loop = Loop(
            name="task",
            initial={},
            fold=lambda s, p: {**s, p["name"]: p},
            boundary_kind="task",
            boundary_match=(("status", "open"),),
        )
        v.register_loop(loop)
        v.replay()

        ticks = v.evaluate_boundaries()
        assert len(ticks) == 1
        # The boundary payload should be from the matching fact
        assert ticks[0].payload.get("_boundary", {}).get("status") == "open"
        store.close()

    def test_one_fire_per_boundary_per_evaluation(self, tmp_path):
        """Each boundary fires at most once per evaluate_boundaries() call."""
        store = SqliteStore(
            path=tmp_path / "test.db",
            serialize=Fact.to_dict,
            deserialize=Fact.from_dict,
        )

        # Multiple matching facts for the same boundary
        store.append(Fact.of("task", "kyle", name="job1", status="open"))
        store.append(Fact.of("task", "kyle", name="job2", status="open"))
        store.append(Fact.of("task", "kyle", name="job3", status="open"))

        v = Vertex("test", store=store)
        loop = Loop(
            name="task",
            initial={},
            fold=lambda s, p: {**s, p["name"]: p},
            boundary_kind="task",
            boundary_match=(("status", "open"),),
        )
        v.register_loop(loop)
        v.replay()

        ticks = v.evaluate_boundaries()
        # Only one fire even though three facts match
        assert len(ticks) == 1
        store.close()

    def test_boundary_tick_is_persisted(self, tmp_path):
        """Ticks produced by evaluate_boundaries are stored."""
        store = SqliteStore(
            path=tmp_path / "test.db",
            serialize=Fact.to_dict,
            deserialize=Fact.from_dict,
        )

        store.append(Fact.of("task", "kyle", name="job1", status="open"))

        v = Vertex("test", store=store)
        v.register("task", {}, lambda s, p: {**s, p["name"]: p},
                   boundary="task")
        v.replay()

        ticks = v.evaluate_boundaries()
        assert len(ticks) == 1

        # Verify tick is in the store
        stored_ticks = store.ticks_since(0)
        assert len(stored_ticks) == 1
        assert stored_ticks[0].name == "task"
        store.close()

    def test_second_evaluate_no_double_fire(self, tmp_path):
        """Calling evaluate_boundaries() twice doesn't double-fire.

        After the first evaluation fires a boundary and produces a tick,
        the period resets. The second evaluation starts from the new period
        and finds no new matching facts.
        """
        store = SqliteStore(
            path=tmp_path / "test.db",
            serialize=Fact.to_dict,
            deserialize=Fact.from_dict,
        )

        store.append(Fact.of("task", "kyle", name="job1", status="open"))

        v = Vertex("test", store=store)
        v.register("task", {}, lambda s, p: {**s, p["name"]: p})
        v.register_vertex_boundary("task", match=(("status", "open"),))
        v.replay()

        ticks1 = v.evaluate_boundaries()
        assert len(ticks1) == 1

        ticks2 = v.evaluate_boundaries()
        assert ticks2 == []
        store.close()


class TestBoundaryRunClause:
    """Test that the run clause propagates from boundary to Tick."""

    def test_vertex_boundary_run_on_tick(self, tmp_path):
        """Vertex-level boundary run clause carried on produced Tick."""
        store = SqliteStore(
            path=tmp_path / "test.db",
            serialize=Fact.to_dict,
            deserialize=Fact.from_dict,
        )
        store.append(Fact.of("task", "kyle", name="job1", status="open"))

        v = Vertex("orchestration", store=store)
        v.register("task", {}, lambda s, p: {**s, p["name"]: p})
        v.register_vertex_boundary(
            "task", match=(("status", "open"),),
            run="scripts/dispatch.sh",
        )
        v.replay()

        ticks = v.evaluate_boundaries()
        assert len(ticks) == 1
        assert ticks[0].run == "scripts/dispatch.sh"
        store.close()

    def test_loop_boundary_run_on_tick(self, tmp_path):
        """Loop-level boundary run clause carried on produced Tick."""
        from engine.loop import Loop

        store = SqliteStore(
            path=tmp_path / "test.db",
            serialize=Fact.to_dict,
            deserialize=Fact.from_dict,
        )
        store.append(Fact.of("task", "kyle", name="job1", status="open"))

        v = Vertex("test", store=store)
        loop = Loop(
            name="task",
            initial={},
            fold=lambda s, p: {**s, p["name"]: p},
            boundary_kind="task",
            boundary_match=(("status", "open"),),
            boundary_run="scripts/dispatch.sh",
        )
        v.register_loop(loop)
        v.replay()

        ticks = v.evaluate_boundaries()
        assert len(ticks) == 1
        assert ticks[0].run == "scripts/dispatch.sh"
        store.close()

    def test_no_run_clause_tick_run_is_none(self, tmp_path):
        """Ticks from boundaries without run clause have run=None."""
        store = SqliteStore(
            path=tmp_path / "test.db",
            serialize=Fact.to_dict,
            deserialize=Fact.from_dict,
        )
        store.append(Fact.of("task", "kyle", name="job1", status="open"))

        v = Vertex("test", store=store)
        v.register("task", {}, lambda s, p: {**s, p["name"]: p})
        v.register_vertex_boundary("task", match=(("status", "open"),))
        v.replay()

        ticks = v.evaluate_boundaries()
        assert len(ticks) == 1
        assert ticks[0].run is None
        store.close()

    def test_run_through_receive_path(self):
        """Run clause also set on ticks produced via receive()."""
        from engine.loop import Loop

        v = Vertex("test")
        loop = Loop(
            name="task",
            initial={},
            fold=lambda s, p: {**s, p.get("name", "x"): p},
            boundary_kind="task.done",
            boundary_run="scripts/on-done.sh",
        )
        v.register_loop(loop)

        # Fold some facts, then trigger the boundary
        v.receive(_fact("task", name="job1"))
        tick = v.receive(_fact("task.done"))
        assert tick is not None
        assert tick.run == "scripts/on-done.sh"


class TestEvaluateBoundariesWithExecutor:
    """Test that the Executor calls evaluate_boundaries during sync."""

    def test_sync_evaluates_boundaries(self, tmp_path):
        """Executor.sync() triggers boundary evaluation for external facts."""
        store = SqliteStore(
            path=tmp_path / "test.db",
            serialize=Fact.to_dict,
            deserialize=Fact.from_dict,
        )

        # External emit
        store.append(Fact.of("task", "kyle", name="job1", status="open"))

        v = Vertex("orchestration", store=store)
        v.register("task", {}, lambda s, p: {**s, p["name"]: p})
        v.register_vertex_boundary("task", match=(("status", "open"),))
        v.replay()

        from engine.executor import Executor, SyncResult

        executor = Executor(vertex=v, sources=[])
        result = executor.sync()

        # The boundary tick should be in the sync result
        # (one from evaluate_boundaries + one _sync fact)
        boundary_ticks = [t for t in result.ticks if t.name == "orchestration"]
        assert len(boundary_ticks) == 1
        assert boundary_ticks[0].payload["task"]["job1"]["status"] == "open"
        store.close()
