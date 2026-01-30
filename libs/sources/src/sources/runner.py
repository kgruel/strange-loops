"""Runner: orchestrates sources and feeds facts to a vertex."""

from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING, AsyncIterator

from facts import Fact

from .protocol import Source

if TYPE_CHECKING:
    from ticks import Tick, Vertex
    from peers import Grant


class Runner:
    """Orchestrates sources feeding facts into a vertex.

    Spawns an async task per source. Each task consumes the source's stream
    and routes facts through the vertex. Yields ticks as boundaries fire.

    Usage:
        runner = Runner(vertex)
        runner.add(source1)
        runner.add(source2)
        async for tick in runner.run():
            print(tick)
    """

    def __init__(self, vertex: Vertex) -> None:
        self._vertex = vertex
        self._sources: list[Source] = []
        self._tasks: list[asyncio.Task] = []
        self._tick_queue: asyncio.Queue[Tick] = asyncio.Queue()
        self._running = False

    def add(self, source: Source) -> None:
        """Register a source to be run."""
        self._sources.append(source)

    async def _consume_source(self, source: Source, grant: Grant | None = None) -> None:
        """Consume a source's stream and route facts to the vertex."""
        try:
            async for fact in source.stream():
                tick = self._vertex.receive(fact, grant)
                if tick is not None:
                    await self._tick_queue.put(tick)
        except asyncio.CancelledError:
            pass
        except Exception as e:
            # Emit error as fact
            error_fact = Fact.of(
                "source.error",
                source.observer,
                error=str(e),
                error_type=type(e).__name__,
            )
            self._vertex.receive(error_fact)

    async def run(self, grant: Grant | None = None) -> AsyncIterator[Tick]:
        """Run all sources and yield ticks as they fire.

        Spawns a task per source. Yields ticks as boundaries fire.
        Runs until stop() is called or all sources complete.
        """
        self._running = True
        self._tasks = [
            asyncio.create_task(self._consume_source(source, grant))
            for source in self._sources
        ]

        try:
            while self._running or not self._tick_queue.empty():
                # Check if all tasks are done
                if all(task.done() for task in self._tasks) and self._tick_queue.empty():
                    break

                try:
                    tick = await asyncio.wait_for(self._tick_queue.get(), timeout=0.1)
                    yield tick
                except asyncio.TimeoutError:
                    continue
        finally:
            await self.stop()

    async def stop(self) -> None:
        """Stop all running source tasks."""
        self._running = False
        for task in self._tasks:
            if not task.done():
                task.cancel()

        if self._tasks:
            await asyncio.gather(*self._tasks, return_exceptions=True)
        self._tasks = []
