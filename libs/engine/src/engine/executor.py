"""Executor: evaluate cadence, run qualifying sources, route facts.

One-shot execution model. No persistent runtime. External scheduling
(cron/hooks) provides the heartbeat.

1. Evaluate all cadence predicates against the store
2. Build dependency graph from trigger relationships
3. Execute in tiers: concurrent within tier, sequential between tiers
4. Route facts through vertex.receive()
5. Return ticks that fired
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


class CyclicDependencyError(Exception):
    """Raised when triggered source cadences form a cycle."""

    def __init__(self, kinds: list[str]) -> None:
        cycle_str = " -> ".join(kinds)
        super().__init__(f"Cyclic trigger dependency: {cycle_str}")
        self.kinds = kinds


def _build_dependency_graph(
    sources: list[tuple[Source, Cadence]],
) -> dict[int, set[int]]:
    """Build {source_index: set of source_indices it depends on}.

    Edge: source[i] depends on source[j] when
    f"{source[j].kind}.complete" is in sources[i].cadence.trigger_kinds.

    Uses source.kind (not cadence.kind) because Source.collect() emits
    {source.kind}.complete regardless of cadence mode.
    """
    # Map complete-kind -> source indices that produce it
    producers: dict[str, list[int]] = {}
    for j, (source, cadence) in enumerate(sources):
        if source.kind:
            complete_kind = f"{source.kind}.complete"
            producers.setdefault(complete_kind, []).append(j)

    deps: dict[int, set[int]] = {}
    for i, (source, cadence) in enumerate(sources):
        if cadence.mode != "triggered":
            continue
        for trigger_kind in cadence.trigger_kinds:
            for j in producers.get(trigger_kind, []):
                if j != i:
                    deps.setdefault(i, set()).add(j)

    return deps


def _toposort_tiers(
    qualifying: set[int],
    deps: dict[int, set[int]],
) -> list[list[int]]:
    """Topological sort into concurrent tiers.

    Returns list of tiers. Within a tier, sources run concurrently.
    Tiers execute sequentially. Raises CyclicDependencyError on cycle.
    """
    # Restrict deps to qualifying set
    local_deps: dict[int, set[int]] = {}
    for idx in qualifying:
        restricted = deps.get(idx, set()) & qualifying
        local_deps[idx] = restricted

    tiers: list[list[int]] = []
    remaining = set(qualifying)

    while remaining:
        # Find nodes with no remaining dependencies
        tier = [idx for idx in remaining if not local_deps[idx]]
        if not tier:
            # Cycle — all remaining nodes have unresolved deps
            raise CyclicDependencyError(sorted(
                str(idx) for idx in remaining
            ))
        tiers.append(sorted(tier))
        remaining -= set(tier)
        # Remove satisfied deps
        for idx in remaining:
            local_deps[idx] -= set(tier)

    return tiers


def validate_dependency_graph(sources: list[tuple[Source, Cadence]]) -> None:
    """Validate that trigger dependencies form a DAG.

    Called at compile time (VertexProgram construction). Raises
    CyclicDependencyError with source kind names if triggered cadences
    form a cycle.
    """
    deps = _build_dependency_graph(sources)
    all_indices = set(range(len(sources)))
    try:
        _toposort_tiers(all_indices, deps)
    except CyclicDependencyError as e:
        cycle_kinds = [sources[int(idx)][0].kind for idx in e.kinds]
        raise CyclicDependencyError(cycle_kinds) from None


@dataclass(frozen=True)
class SkippedSource:
    """A source skipped by cadence evaluation."""

    kind: str
    last_run_ts: float | None = None  # epoch of last successful .complete
    cadence_interval: float | None = None  # seconds, for elapsed mode


@dataclass
class SyncResult:
    """Result of a sync operation."""

    ticks: list[Tick]
    ran: list[str]  # kinds of sources that ran
    skipped: list[SkippedSource]  # sources skipped by cadence
    errors: list[Fact]  # source.error facts
    tiers: list[list[str]]  # execution order: each tier ran concurrently
    fact_counts: dict[str, int] = field(default_factory=dict)  # facts ingested per source kind


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
        """One-shot sync. Dependency-aware concurrency.

        Sources execute in tiers derived from trigger relationships.
        Independent sources run concurrently. Triggered sources wait
        for their dependencies to complete first.

        Args:
            store: Store for cadence evaluation. If None, uses vertex._store.
            grant: Optional grant for identity gating.
            force: If True, bypass cadence — run all sources.
        """
        import time

        if store is None:
            store = self.vertex._store

        start = time.time()
        qualifying_indices: list[int] = []
        skipped: list[SkippedSource] = []

        for i, (source, cadence) in enumerate(self.sources):
            if force or store is None or cadence.should_run(store, start):
                qualifying_indices.append(i)
            else:
                complete_kind = f"{source.kind}.complete"
                last = store.latest_by_kind_where(complete_kind, "status", "ok")
                skipped.append(SkippedSource(
                    kind=source.kind,
                    last_run_ts=last.ts if last else None,
                    cadence_interval=cadence._interval,
                ))

        ticks: list[Tick] = []
        errors: list[Fact] = []
        ran: list[str] = []
        tier_kinds: list[list[str]] = []
        fact_counts: dict[str, int] = {}
        fact_count = [0]  # mutable counter shared across async tasks

        if qualifying_indices:
            deps = _build_dependency_graph(self.sources)
            tiers = _toposort_tiers(set(qualifying_indices), deps)

            for tier in tiers:
                tier_sources = [self.sources[i][0] for i in tier]
                tasks = [
                    self._run_source(source, grant, ticks, errors, fact_counts, fact_count)
                    for source in tier_sources
                ]
                await asyncio.gather(*tasks)
                tier_kinds.append([s.kind for s in tier_sources])

            ran = [self.sources[i][0].kind for i in qualifying_indices]

        # Emit sync.complete — same sentinel pattern as source .complete
        from atoms import Fact

        duration_ms = int((time.time() - start) * 1000)
        sync_fact = Fact.of(
            "sync.complete",
            self.vertex.name,
            status="error" if errors else "ok",
            sources_run=len(ran),
            sources_skipped=len(skipped),
            total_facts=fact_count[0],
            duration_ms=duration_ms,
        )
        tick = self.vertex.receive(sync_fact, grant)
        if tick is not None:
            ticks.append(tick)

        return SyncResult(
            ticks=ticks, ran=ran, skipped=skipped,
            errors=errors, tiers=tier_kinds, fact_counts=fact_counts,
        )

    async def _run_source(
        self,
        source: Source,
        grant: Any,
        ticks: list,
        errors: list,
        fact_counts: dict[str, int] | None = None,
        fact_count: list[int] | None = None,
    ) -> None:
        """Run a single source and route its facts through the vertex."""
        count = 0
        try:
            async for fact in source.collect():
                if fact_count is not None:
                    fact_count[0] += 1
                if fact.kind == "source.error":
                    errors.append(fact)
                    if self.on_error is not None:
                        self.on_error(fact)
                elif not fact.kind.endswith(".complete"):
                    count += 1
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
            if fact_count is not None:
                fact_count[0] += 1
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
            if fact_count is not None:
                fact_count[0] += 1
            tick = self.vertex.receive(complete_fact)
            if tick is not None:
                ticks.append(tick)
        if fact_counts is not None:
            fact_counts[source.kind] = count

    def sync(self, store: Any = None, grant: Any = None, *, force: bool = False) -> SyncResult:
        """Synchronous wrapper around sync_async."""
        return asyncio.run(self.sync_async(store, grant, force=force))
