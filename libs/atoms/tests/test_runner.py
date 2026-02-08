"""Tests for Runner."""

import asyncio
from dataclasses import dataclass
from typing import AsyncIterator

import pytest

from atoms import Fact
from atoms import Runner, Source
from engine import Vertex


@dataclass
class MockSource:
    """Mock source that yields predetermined facts."""

    observer: str
    facts: list[Fact]
    delay: float = 0

    async def stream(self) -> AsyncIterator[Fact]:
        for fact in self.facts:
            if self.delay > 0:
                await asyncio.sleep(self.delay)
            yield fact


class TestRunner:
    """Tests for Runner behavior."""

    async def test_single_source_routes_to_vertex(self):
        """Single source's facts route through vertex."""
        vertex = Vertex("test-vertex")
        vertex.register("count", 0, lambda s, p: s + 1)

        source = MockSource(
            observer="mock",
            facts=[
                Fact.of("count", "mock"),
                Fact.of("count", "mock"),
            ],
        )

        runner = Runner(vertex)
        runner.add(source)

        ticks = []
        async for tick in runner.run():
            ticks.append(tick)

        assert vertex.state("count") == 2

    async def test_multiple_sources_run_concurrently(self):
        """Multiple sources run in parallel."""
        vertex = Vertex("test-vertex")
        vertex.register("a", [], lambda s, p: s + [p.get("v")])
        vertex.register("b", [], lambda s, p: s + [p.get("v")])

        source_a = MockSource(
            observer="source-a",
            facts=[
                Fact.of("a", "source-a", v=1),
                Fact.of("a", "source-a", v=2),
            ],
            delay=0.01,
        )
        source_b = MockSource(
            observer="source-b",
            facts=[
                Fact.of("b", "source-b", v=10),
                Fact.of("b", "source-b", v=20),
            ],
            delay=0.01,
        )

        runner = Runner(vertex)
        runner.add(source_a)
        runner.add(source_b)

        async for _ in runner.run():
            pass

        assert vertex.state("a") == [1, 2]
        assert vertex.state("b") == [10, 20]

    async def test_boundary_fires_yield_ticks(self):
        """Ticks are yielded when boundaries fire."""
        vertex = Vertex("test-vertex")
        vertex.register(
            "metric",
            0,
            lambda s, p: s + p.get("value", 0),
            boundary="metric.close",
            reset=True,
        )

        source = MockSource(
            observer="metric-source",
            facts=[
                Fact.of("metric", "metric-source", value=10),
                Fact.of("metric", "metric-source", value=5),
                Fact.of("metric.close", "metric-source"),
                Fact.of("metric", "metric-source", value=3),
                Fact.of("metric.close", "metric-source"),
            ],
        )

        runner = Runner(vertex)
        runner.add(source)

        ticks = []
        async for tick in runner.run():
            ticks.append(tick)

        assert len(ticks) == 2
        assert ticks[0].payload == 15
        assert ticks[1].payload == 3

    async def test_stop_cancels_tasks(self):
        """stop() cancels running source tasks."""
        vertex = Vertex("test-vertex")
        vertex.register(
            "tick",
            0,
            lambda s, p: s + 1,
            boundary="tick",  # Every fact triggers a tick
            reset=False,
        )

        @dataclass
        class InfiniteSource:
            observer: str = "infinite"

            async def stream(self) -> AsyncIterator[Fact]:
                while True:
                    yield Fact.of("tick", self.observer)
                    await asyncio.sleep(0.01)

        runner = Runner(vertex)
        runner.add(InfiniteSource())

        count = 0
        async for tick in runner.run():
            count += 1
            if count >= 3:
                await runner.stop()
                break

        # Should have exited cleanly
        assert count >= 3

    async def test_empty_sources_completes(self):
        """Runner with no sources completes immediately."""
        vertex = Vertex("test-vertex")
        runner = Runner(vertex)

        ticks = []
        async for tick in runner.run():
            ticks.append(tick)

        assert ticks == []

    async def test_source_yielding_no_facts(self):
        """Source that yields nothing still completes."""
        vertex = Vertex("test-vertex")

        source = MockSource(observer="empty", facts=[])

        runner = Runner(vertex)
        runner.add(source)

        ticks = []
        async for tick in runner.run():
            ticks.append(tick)

        assert ticks == []


class TestRunnerWithCommandSource:
    """Integration tests with real CommandSource."""

    async def test_command_source_integration(self):
        """CommandSource works with Runner and Vertex."""
        from atoms import CommandSource

        vertex = Vertex("test-vertex")
        vertex.register("greeting", {"count": 0}, lambda s, p: {"count": s["count"] + 1})

        source = CommandSource(
            command='echo "hello"',
            kind="greeting",
            observer="echo",
        )

        runner = Runner(vertex)
        runner.add(source)

        async for _ in runner.run():
            pass

        assert vertex.state("greeting")["count"] == 1

    async def test_success_criteria_example(self):
        """The exact example from the task description works."""
        from atoms import CommandSource

        source = CommandSource(
            command='echo "hello"',
            kind="greeting",
            observer="echo",
            every=None,  # Run once for test
        )

        vertex = Vertex()
        vertex.register(
            "greeting",
            {},
            lambda s, p: {"count": s.get("count", 0) + 1},
        )

        runner = Runner(vertex)
        runner.add(source)

        ticks = []
        async for tick in runner.run():
            ticks.append(tick)

        # No boundary configured, so no ticks
        assert ticks == []
        # But state was updated
        assert vertex.state("greeting")["count"] == 1


class TestVertexIngest:
    """Tests for Vertex.ingest() convenience method."""

    def test_ingest_creates_fact_and_receives(self):
        """ingest() creates a Fact and calls receive()."""
        vertex = Vertex("test-vertex")
        vertex.register("metric", 0, lambda s, p: s + p.get("value", 0))

        tick = vertex.ingest("metric", {"value": 42}, "test-observer")

        assert tick is None  # No boundary
        assert vertex.state("metric") == 42

    def test_ingest_with_boundary(self):
        """ingest() returns Tick when boundary fires."""
        vertex = Vertex("test-vertex")
        vertex.register(
            "metric",
            0,
            lambda s, p: s + p.get("value", 0),
            boundary="metric.close",
            reset=True,
        )

        vertex.ingest("metric", {"value": 10}, "observer")
        vertex.ingest("metric", {"value": 5}, "observer")
        tick = vertex.ingest("metric.close", {}, "observer")

        assert tick is not None
        assert tick.payload == 15
        assert vertex.state("metric") == 0  # Reset

    def test_ingest_with_grant(self):
        """ingest() respects grant potential."""
        from engine import Peer, grant_of

        peer = Peer("user", potential=frozenset({"allowed"}))
        grant = grant_of(peer)

        vertex = Vertex("test-vertex")
        vertex.register("allowed", 0, lambda s, p: s + 1)
        vertex.register("blocked", 0, lambda s, p: s + 1)

        vertex.ingest("allowed", {}, "user", grant)
        vertex.ingest("blocked", {}, "user", grant)

        assert vertex.state("allowed") == 1
        assert vertex.state("blocked") == 0  # Gated out
