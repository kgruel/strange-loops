"""Tests for Executor dependency-aware concurrency."""

import asyncio
import time
from unittest.mock import AsyncMock

import pytest

from atoms import Fact
from engine import Cadence, EventStore, Vertex
from engine.executor import (
    CyclicDependencyError,
    Executor,
    _build_dependency_graph,
    _toposort_tiers,
    validate_dependency_graph,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


class StubSource:
    """Minimal source that records when it ran and emits a .complete fact."""

    def __init__(self, kind: str, observer: str = "test", facts: list | None = None):
        self.kind = kind
        self.observer = observer
        self._facts = facts or []
        self.ran_at: float | None = None

    async def collect(self):
        self.ran_at = time.monotonic()
        for fact in self._facts:
            yield fact
        yield Fact.of(f"{self.kind}.complete", self.observer, status="ok")


def _make_vertex():
    """Create a minimal vertex with a store for testing."""
    store = EventStore(serialize=Fact.to_dict, deserialize=Fact.from_dict)
    return Vertex("test", store=store)


# ---------------------------------------------------------------------------
# Cadence properties
# ---------------------------------------------------------------------------


class TestCadenceProperties:
    def test_elapsed_properties(self):
        c = Cadence.elapsed("disk", 60.0)
        assert c.kind == "disk"
        assert c.mode == "elapsed"
        assert c.trigger_kinds == ()

    def test_triggered_properties(self):
        c = Cadence.triggered(("deploy.complete", "build.complete"), "smoke")
        assert c.kind == "smoke"
        assert c.mode == "triggered"
        assert c.trigger_kinds == ("deploy.complete", "build.complete")

    def test_always_properties(self):
        c = Cadence.always()
        assert c.kind == ""
        assert c.mode == "always"
        assert c.trigger_kinds == ()


# ---------------------------------------------------------------------------
# Graph construction
# ---------------------------------------------------------------------------


class TestBuildDependencyGraph:
    def test_no_triggers(self):
        """All elapsed/always sources — no dependency edges."""
        sources = [
            (StubSource("a"), Cadence.elapsed("a", 60)),
            (StubSource("b"), Cadence.always()),
            (StubSource("c"), Cadence.elapsed("c", 120)),
        ]
        deps = _build_dependency_graph(sources)
        assert deps == {}

    def test_simple_chain(self):
        """B triggers on A.complete — B depends on A."""
        sources = [
            (StubSource("deploy"), Cadence.elapsed("deploy", 60)),
            (StubSource("smoke"), Cadence.triggered("deploy.complete", "smoke")),
        ]
        deps = _build_dependency_graph(sources)
        assert deps == {1: {0}}

    def test_diamond(self):
        """C triggers on both A.complete and B.complete."""
        sources = [
            (StubSource("a"), Cadence.elapsed("a", 60)),
            (StubSource("b"), Cadence.elapsed("b", 60)),
            (StubSource("c"), Cadence.triggered(("a.complete", "b.complete"), "c")),
        ]
        deps = _build_dependency_graph(sources)
        assert deps == {2: {0, 1}}

    def test_multi_tier_chain(self):
        """A -> B -> C: three-tier chain."""
        sources = [
            (StubSource("a"), Cadence.elapsed("a", 60)),
            (StubSource("b"), Cadence.triggered("a.complete", "b")),
            (StubSource("c"), Cadence.triggered("b.complete", "c")),
        ]
        deps = _build_dependency_graph(sources)
        assert deps == {1: {0}, 2: {1}}

    def test_no_self_dependency(self):
        """A source triggering on its own .complete kind doesn't create self-edge."""
        sources = [
            (StubSource("x"), Cadence.triggered("x.complete", "x")),
        ]
        deps = _build_dependency_graph(sources)
        assert deps == {}

    def test_trigger_on_nonexistent_producer(self):
        """Trigger on a kind no source produces — no edges."""
        sources = [
            (StubSource("a"), Cadence.elapsed("a", 60)),
            (StubSource("b"), Cadence.triggered("missing.complete", "b")),
        ]
        deps = _build_dependency_graph(sources)
        assert deps == {}


# ---------------------------------------------------------------------------
# Topological sort
# ---------------------------------------------------------------------------


class TestToposortTiers:
    def test_single_tier(self):
        """All independent — single tier."""
        tiers = _toposort_tiers({0, 1, 2}, {})
        assert tiers == [[0, 1, 2]]

    def test_simple_chain(self):
        """A -> B: two tiers."""
        deps = {1: {0}}
        tiers = _toposort_tiers({0, 1}, deps)
        assert tiers == [[0], [1]]

    def test_three_tier_chain(self):
        """A -> B -> C: three tiers."""
        deps = {1: {0}, 2: {1}}
        tiers = _toposort_tiers({0, 1, 2}, deps)
        assert tiers == [[0], [1], [2]]

    def test_diamond(self):
        """A, B independent; C depends on both."""
        deps = {2: {0, 1}}
        tiers = _toposort_tiers({0, 1, 2}, deps)
        assert tiers == [[0, 1], [2]]

    def test_partial_qualifying(self):
        """Only some sources qualify — deps outside qualifying set are ignored."""
        # B depends on A, but A isn't qualifying
        deps = {1: {0}}
        tiers = _toposort_tiers({1}, deps)
        assert tiers == [[1]]

    def test_cycle_raises(self):
        """Cycle A -> B -> A raises CyclicDependencyError."""
        deps = {0: {1}, 1: {0}}
        with pytest.raises(CyclicDependencyError):
            _toposort_tiers({0, 1}, deps)


# ---------------------------------------------------------------------------
# validate_dependency_graph
# ---------------------------------------------------------------------------


class TestValidateDependencyGraph:
    def test_dag_passes(self):
        sources = [
            (StubSource("a"), Cadence.elapsed("a", 60)),
            (StubSource("b"), Cadence.triggered("a.complete", "b")),
        ]
        validate_dependency_graph(sources)  # should not raise

    def test_cycle_fails_at_validation_with_kind_names(self):
        sources = [
            (StubSource("deploy"), Cadence.triggered("smoke.complete", "deploy")),
            (StubSource("smoke"), Cadence.triggered("deploy.complete", "smoke")),
        ]
        with pytest.raises(CyclicDependencyError, match="deploy") as exc_info:
            validate_dependency_graph(sources)
        assert set(exc_info.value.kinds) == {"deploy", "smoke"}


# ---------------------------------------------------------------------------
# Executor integration
# ---------------------------------------------------------------------------


class TestExecutorTiers:
    def test_independent_sources_single_tier(self):
        """All independent sources run in one tier."""
        vertex = _make_vertex()
        sources = [
            (StubSource("a"), Cadence.always()),
            (StubSource("b"), Cadence.always()),
        ]
        executor = Executor(vertex, sources)
        result = asyncio.run(executor.sync_async(force=True))

        assert set(result.ran) == {"a", "b"}
        assert len(result.tiers) == 1
        assert set(result.tiers[0]) == {"a", "b"}

    def test_triggered_chain_ordering(self):
        """B triggers on A.complete — B runs after A, in a later tier."""
        vertex = _make_vertex()
        source_a = StubSource("deploy")
        source_b = StubSource("smoke")
        sources = [
            (source_a, Cadence.elapsed("deploy", 60)),
            (source_b, Cadence.triggered("deploy.complete", "smoke")),
        ]
        executor = Executor(vertex, sources)
        result = asyncio.run(executor.sync_async(force=True))

        assert result.tiers == [["deploy"], ["smoke"]]
        assert source_a.ran_at is not None
        assert source_b.ran_at is not None
        assert source_a.ran_at < source_b.ran_at

    def test_three_tier_chain(self):
        """A -> B -> C: three sequential tiers."""
        vertex = _make_vertex()
        sources = [
            (StubSource("a"), Cadence.elapsed("a", 60)),
            (StubSource("b"), Cadence.triggered("a.complete", "b")),
            (StubSource("c"), Cadence.triggered("b.complete", "c")),
        ]
        executor = Executor(vertex, sources)
        result = asyncio.run(executor.sync_async(force=True))

        assert result.tiers == [["a"], ["b"], ["c"]]

    def test_diamond_two_tiers(self):
        """A, B independent; C depends on both — two tiers."""
        vertex = _make_vertex()
        sources = [
            (StubSource("a"), Cadence.always()),
            (StubSource("b"), Cadence.always()),
            (StubSource("c"), Cadence.triggered(("a.complete", "b.complete"), "c")),
        ]
        executor = Executor(vertex, sources)
        result = asyncio.run(executor.sync_async(force=True))

        assert len(result.tiers) == 2
        assert set(result.tiers[0]) == {"a", "b"}
        assert result.tiers[1] == ["c"]

    def test_complete_fact_visible_to_later_tier(self):
        """After tier 0, A's .complete fact is in the store for tier 1."""
        vertex = _make_vertex()
        source_a = StubSource("deploy")
        source_b = StubSource("smoke")
        sources = [
            (source_a, Cadence.elapsed("deploy", 60)),
            (source_b, Cadence.triggered("deploy.complete", "smoke")),
        ]
        executor = Executor(vertex, sources)
        asyncio.run(executor.sync_async(force=True))

        # deploy.complete should be in the store
        store = vertex._store
        latest = store.latest_by_kind("deploy.complete")
        assert latest is not None
        assert latest.payload["status"] == "ok"

    def test_skipped_sources_not_in_tiers(self):
        """Skipped sources don't appear in tiers."""
        vertex = _make_vertex()
        sources = [
            (StubSource("a"), Cadence.always()),
            (StubSource("b"), Cadence.elapsed("b", 9999)),
        ]
        # Put a recent completion so b is skipped
        vertex._store.append(Fact.of("b.complete", "test", status="ok"))
        executor = Executor(vertex, sources)
        result = asyncio.run(executor.sync_async())

        assert result.ran == ["a"]
        assert result.skipped == ["b"]
        assert result.tiers == [["a"]]

    def test_empty_sources(self):
        """No sources — empty result with empty tiers."""
        vertex = _make_vertex()
        executor = Executor(vertex, [])
        result = asyncio.run(executor.sync_async())

        assert result.ran == []
        assert result.tiers == []
