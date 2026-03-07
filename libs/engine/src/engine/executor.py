"""Executor: evaluate cadence, run qualifying sources, route facts.

One-shot execution model. No persistent runtime. External scheduling
(cron/hooks) provides the heartbeat.

1. Evaluate all cadence predicates against the store
2. Run qualifying sources concurrently (asyncio.gather)
3. Route facts through vertex.receive()
4. Return ticks that fired
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any, Callable

if TYPE_CHECKING:
    from atoms import Fact, Source
    from .cadence import Cadence
    from .tick import Tick
    from .vertex import Vertex


@dataclass
class SyncResult:
    """Result of a sync operation."""

    ticks: list[Tick]
    ran: list[str]  # kinds of sources that ran
    skipped: list[str]  # kinds of sources skipped by cadence
    errors: list[Fact]  # source.error facts


@dataclass
class Executor:
    """Evaluate cadence, run qualifying sources, route facts."""

    vertex: Vertex
    sources: list[tuple[Source, Cadence]]
    on_error: Callable[[Fact], None] | None = None

    async def sync_async(
        self,
        store: Any = None,
        grant: Any = None,
        *,
        force: bool = False,
    ) -> SyncResult:
        """One-shot sync. Concurrent by default.

        Args:
            store: Store for cadence evaluation. If None, uses vertex._store.
            grant: Optional grant for identity gating.
            force: If True, bypass cadence — run all sources.
        """
        import time

        if store is None:
            store = self.vertex._store

        now = time.time()
        qualifying = []
        skipped = []

        for source, cadence in self.sources:
            if force or store is None or cadence.should_run(store, now):
                qualifying.append(source)
            else:
                skipped.append(source.kind)

        ticks: list[Tick] = []
        errors: list[Fact] = []
        ran: list[str] = []

        if qualifying:
            tasks = [
                self._run_source(source, grant, ticks, errors)
                for source in qualifying
            ]
            await asyncio.gather(*tasks)
            ran = [s.kind for s in qualifying]

        return SyncResult(ticks=ticks, ran=ran, skipped=skipped, errors=errors)

    async def _run_source(
        self,
        source: Source,
        grant: Any,
        ticks: list,
        errors: list,
    ) -> None:
        """Run a single source and route its facts through the vertex."""
        try:
            async for fact in source.collect():
                if fact.kind == "source.error":
                    errors.append(fact)
                    if self.on_error is not None:
                        self.on_error(fact)
                tick = self.vertex.receive(fact, grant)
                if tick is not None:
                    ticks.append(tick)
        except Exception as e:
            from atoms import Fact

            error_fact = Fact.of(
                "source.error",
                source.observer,
                error=str(e),
                error_type=type(e).__name__,
            )
            errors.append(error_fact)
            self.vertex.receive(error_fact)
            if self.on_error is not None:
                self.on_error(error_fact)

            complete_fact = Fact.of(
                f"{source.kind}.complete",
                source.observer,
                status="error",
                error=str(e),
                error_type=type(e).__name__,
            )
            tick = self.vertex.receive(complete_fact)
            if tick is not None:
                ticks.append(tick)

    def sync(self, store: Any = None, grant: Any = None, *, force: bool = False) -> SyncResult:
        """Synchronous wrapper around sync_async."""
        return asyncio.run(self.sync_async(store, grant, force=force))
