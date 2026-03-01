"""Runner: orchestrates sources and feeds facts to a vertex."""

from __future__ import annotations

import asyncio
import sys
from typing import TYPE_CHECKING, AsyncIterator, Callable

from atoms.fact import Fact

from .protocol import SourceProtocol

if TYPE_CHECKING:
    from engine import Tick, Vertex
    from engine import Grant


class Runner:
    """Orchestrates sources feeding facts into a vertex.

    Spawns an async task per source. Each task consumes the source's stream
    and routes facts through the vertex. Yields ticks as boundaries fire.

    Sources are partitioned by timing mode:
    - Polling (every or no trigger): spawned immediately
    - Triggered (trigger field set): spawned when a matching tick fires

    Usage:
        runner = Runner(vertex)
        runner.add(source1)
        runner.add(source2)
        async for tick in runner.run():
            print(tick)
    """

    def __init__(
        self,
        vertex: Vertex,
        *,
        on_error: Callable[[Fact], None] | None = None,
        yield_every: int = 64,
    ) -> None:
        self._vertex = vertex
        self._sources: list[SourceProtocol] = []
        self._tasks: list[asyncio.Task] = []
        self._tick_queue: asyncio.Queue[Tick] = asyncio.Queue()
        self._running = False
        self._triggered: dict[str, list[SourceProtocol]] = {}
        self._on_error = on_error
        self._yield_every = yield_every

    def add(self, source: SourceProtocol) -> None:
        """Register a source to be run."""
        self._sources.append(source)

    async def _consume_source(self, source: SourceProtocol, grant: Grant | None = None) -> None:
        """Consume a source's stream and route facts to the vertex."""
        try:
            count = 0
            async for fact in source.stream():
                if fact.kind == "source.error" and self._on_error is not None:
                    self._on_error(fact)
                tick = self._vertex.receive(fact, grant)
                if tick is not None:
                    await self._tick_queue.put(tick)
                count += 1
                if self._yield_every and count % self._yield_every == 0:
                    await asyncio.sleep(0)
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
            if self._on_error is not None:
                self._on_error(error_fact)

    async def run(self, grant: Grant | None = None) -> AsyncIterator[Tick]:
        """Run all sources and yield ticks as they fire.

        Partitions sources into polling (spawned immediately) and triggered
        (spawned when a matching tick fires). Yields ticks as boundaries fire.
        Runs until stop() is called or all sources complete.
        """
        self._running = True

        # Partition: polling sources spawn now, triggered sources wait
        self._triggered = {}
        polling = []
        for source in self._sources:
            trigger = getattr(source, "trigger", None)
            if trigger is not None:
                for kind in trigger:
                    self._triggered.setdefault(kind, []).append(source)
            else:
                polling.append(source)

        self._tasks = [
            asyncio.create_task(self._consume_source(source, grant))
            for source in polling
        ]

        try:
            while self._running or not self._tick_queue.empty():
                # Check if all tasks are done
                if all(task.done() for task in self._tasks) and self._tick_queue.empty():
                    break

                try:
                    tick = await asyncio.wait_for(self._tick_queue.get(), timeout=0.1)

                    # Spawn triggered sources matching this tick
                    triggered = self._triggered.get(tick.name, [])
                    for source in triggered:
                        self._tasks.append(
                            asyncio.create_task(self._consume_source(source, grant))
                        )

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
