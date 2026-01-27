# HANDOFF

Monorepo overview. Per-library details live in each lib's own HANDOFF.md.

## Library Handoffs

| Library | Handoff | Focus |
|---------|---------|-------|
| **peers** | `libs/peers/HANDOFF.md` | Identity + capability |
| **facts** | `libs/facts/HANDOFF.md` | Observation atom |
| **ticks** | `libs/ticks/HANDOFF.md` | Temporal infrastructure |
| **shapes** | `libs/shapes/HANDOFF.md` | Data contracts + fold rules |
| **cells** | `libs/cells/HANDOFF.md` | Terminal UI |

## Architecture

See `ARCHITECTURE.md` for the definitive system overview (atoms, topology,
data flow, vocabulary). See `ARCHITECTURE-JOURNEY.md` for how we got there.

## Recent History

### 2026-01-26 — Structure alignment

Project structure normalized across all five libs: hatchling build
backend, `[dependency-groups]` for dev deps, `>=3.11` Python, identical
`.gitignore`, `py.typed` markers, canonical `pyproject.toml` ordering.
Per-lib CLAUDE.md and HANDOFF.md added.

Pipeline experiment reset: new test_atoms.py with 14 tests. Experiments
archived into `experiments/archive/`.

Container app (`experiments/containers.py`): first end-to-end wiring of
all five atoms. Needs Docker daemon to run live.

Six parallel fixes merged: Shape.apply() purity fix (deepcopy), Surface
lifecycle hooks, Fact.ts epoch float, UI kind namespacing, tooling
normalization (ruff + ty + pytest-cov), doc drift fixes, ticks async
cleanup.

### 2026-01-26 — Semantic journey

Extended conceptual session: monorepo naming (loops vs volta vs prism),
pivot concept (four universal atoms + cell as first surface), Peer
refactored to horizon + potential, capability-as-fact demonstrated,
"stream" vocabulary questioned, daemon/mill primitive built. Full
narrative in `ARCHITECTURE-JOURNEY.md`.

### 2026-01-27 — Architecture crystallization

Explored the ticks library identity: what IS the plumbing? Identified
primitives (fold, boundary, persist, replay, connection). Dissolved
lifecycle into facts, nesting into topology. Moved boundary to Shape.
Replaced Stream concept with vertex (intersection of loops). Explored
and rejected Tick-into-Fact collapse after comparative analysis
confirmed Tick as the key architectural differentiator. Tick gained
`name` field. Vertex settled as topology concept in ticks library, not
a sixth atom. Peer-vertex relationship flows through facts (capability
folding). Full narrative in `ARCHITECTURE-JOURNEY.md`.

### 2026-01-27 — Tick-to-Fact dissolved, Tick identity, fleet experiment

Three threads pulled in one session, each building on the last.

**Tick-to-Fact dissolved.** Open question #4. Built iteratively from
atomic level up through `experiments/fleet.py`: three-level vertex
hierarchy (4 VMs → 2 regions → global) with heterogeneous activities
(health, deploy, audit). Ticks are a level above Facts — temporal
groupings, not peers. No conversion needed. Same primitive at every
level. The question dissolved.

**Tick gained `origin` field.** Tick is the output primitive of the
system. It needs identity: which vertex produced it. `origin: str`
added to Tick (default `""` for backwards compat). Vertex gained
`name: str` parameter, stamps `origin=self._name` on produced Ticks.
Key insight: `origin` is the routing key at the next level — downstream
vertices register fold engines by source origin, not by cycle name.
`tick.name` = what cycle completed (semantic). `tick.origin` = where
it came from (structural). Fleet experiment updated to route via origin.

**Boundary triggering designed (not yet implemented).** Each loop
through a vertex has its own semantic boundary and cadence. A deploy
completes when it's done. A heartbeat fires every interval. An audit
finishes when all hosts are scanned. Per-kind boundaries on Vertex
(not per-vertex): `register(kind, initial, fold, boundary=..., reset=...)`.
`receive()` checks after each fold; when matched, that kind's fold
engine auto-produces a Tick. If `reset=True`, engine resets for the
next cycle. Different loops tick independently at the same vertex.
Design settled, implementation deferred to next session.

**Vocabulary updates.** "Loop" is the conceptual term, "Stream" is
plumbing. "Intersect" replaces "connect" for topology (loops intersect
at vertices). "Connect" reserved for infrastructure (network protocols).
ARCHITECTURE.md section renamed "How Loops Intersect", vocabulary
section added "The loop" definition. CLAUDE.md Data Flow rewritten
loop-centric.

**Bug found.** Surface.on_start is a callback (`__init__` parameter),
not a method override. Both fleet.py and containers.py had this wrong.

### 2026-01-27 — Genesis document + strata semantic tagging

Reconstructed the project's origin story from archived conversations via
strata. Six strata queries covered: intellectual pivots, vocabulary
evolution, dead ends, design principles, human story, AI collaboration
patterns. Synthesized into `docs/GENESIS.md` — a nine-act narrative from
the corrupt movie file through five-atom crystallization to the feedback
loop closing.

Discovered strata's `tag` and `query -l` CLI capabilities (not surfaced
by the skill interface). Used `strata ask --conversations` to semantic-
search for conversations matching 10 conceptual themes, then applied tags
to 58 conversations across ev, cells, experiments, gruel.network, and
prism workspaces. Tags are now durable retrieval keys:
`strata query -l dissolution` returns the exact conversations where
false distinctions were explored.

Tags applied: `inciting-friction`, `vocabulary-as-architecture`,
`dissolution`, `declaration-over-procedure`, `self-similarity`,
`the-great-deletion`, `forcing-function`, `observation-as-participation`,
`the-missing-middle`, `co-creation`.

Strata feedback and retrospective written to `docs/STRATA_FEEDBACK.md`
and `docs/STRATA_RETROSPECTIVE.md`. Key finding: the strata skill and
strata CLI are two separate interfaces to the same system — the skill
doesn't surface tagging/querying capabilities.

### 2026-01-27 — Boundary triggering implemented

Implemented HANDOFF #5 (boundary triggering on Vertex). `Projection.reset()`
added. Vertex internals restructured: `_FoldEngine` dataclass (projection +
boundary config + initial), `_boundary_map` for O(1) lookup. `register()`
gains `boundary: str | None` and `reset: bool`. `receive()` returns
`Tick | None` — fold-before-boundary, optional reset, boundary kind uniqueness
enforced. Manual `tick()` unchanged.

Async ergonomics resolved by design: Vertex is a sync fold machine. The
Consumer protocol has no return channel, so the async bridge (kind extraction,
Tick routing to downstream Stream) lives at the composition point. Same
pattern as the Fact→Shape bridge. Closed as intentional, not deferred.

E2e integration tests: boundary→Stream[Tick]→Projection, two-level nested
loops, Shape.boundary descriptor wired to Vertex.register. 122 ticks tests.

**Next session**: review prior experiments (`fleet.py`, `containers.py`),
decide whether to update them for boundary triggering or design a new
experiment from scratch.

### 2026-01-27 — Refactor complete

Four refactors landed across three parallel subtasks:

**shapes**: `Boundary(kind: str, reset: bool)` frozen dataclass added.
`boundary: Boundary | None = None` on Shape. Declarative — apply()
unchanged, checked externally by fold engine. 12 new tests.

**ticks**: Tick gained `name: str` field. Store protocol (append, since,
close) with EventStore (memory) and FileStore (JSONL) implementations.
Vertex primitive: kind-based routing, fold engine management, tick
emission. Projection gained `fold_one()` sync method — Vertex uses
public API. 32 new tests.

**facts**: `Fact.tick(name, **data)` convenience classmethod. Auto-prefixes
kind to `tick.{name}` following infrastructure namespacing convention.
7 new tests.

**peers**: Already landed prior session (horizon + potential replacing
scope).

## Refactor

All structural refactors complete. Remaining: documentation alignment (in progress).

### Done

- **shapes**: Boundary type + Shape field (2026-01-27)
- **peers**: horizon + potential replacing scope (2026-01-27)
- **ticks**: Tick name + Vertex + Store + FileStore + fold_one (2026-01-27)
- **ticks**: Tick.origin + Vertex.name (2026-01-27)
- **ticks**: Boundary triggering on Vertex + Projection.reset (2026-01-27)
- **facts**: Fact.tick() convenience (2026-01-27)
- **cells**: no structural changes needed

### In progress

- **documentation**: align root CLAUDE.md, per-lib docs, experiments with post-refactor reality

## Explore

Open questions — resolved items kept for context.

1. ~~**Vertex as code**~~: Resolved. `Vertex` class in `ticks/vertex.py`.
   Manages Projection fold engines per kind, optional Store backing,
   produces Ticks via `tick(name, ts)`. Runtime infrastructure, not frozen.

2. ~~**Store interface**~~: Resolved. `Store` protocol: `append(event)`,
   `since(cursor) -> list`, `close()`. Two implementations: EventStore
   (memory, with eviction) and FileStore (JSONL). Cursor is int offset.

3. ~~**Kind-based routing**~~: Resolved. Explicit registration via
   `Vertex.register(kind, initial, fold)`. Not derived from input_facets.

4. ~~**Tick-to-Fact conversion**~~: Resolved. **The question dissolved.**
   Ticks are a level above Facts — temporal groupings, not peers. A Tick
   at level N is the atomic input at level N+1. The receiving vertex
   folds Ticks directly via `receive(tick.origin, tick.payload)` — origin
   is the routing key, not name. No conversion to Fact needed. Same
   primitive at every level. Proven in `experiments/fleet.py`.

5. ~~**Boundary triggering + reset**~~: Resolved. Implemented as designed.
   `register(kind, initial, fold, boundary=..., reset=...)` with
   `receive()` returning `Tick | None`. Fold-before-boundary, optional
   reset, boundary kind uniqueness enforced. `Projection.reset()` added.
   Vertex stays sync by design — async bridge lives at composition point.
   E2e tests prove: boundary→Stream[Tick], nested loops (upstream→Tick→
   downstream), Shape.boundary→Vertex wiring. 122 ticks tests.

6. **Fact.tick() role**: Open. The `Fact.tick(name, **data)` convenience
   was built for tick-to-fact conversion. That path dissolved. May still
   serve as "tick-as-observation" (a downstream system noting that a tick
   occurred) but no longer on the critical path. Revisit when real usage
   clarifies.

7. **Peer horizon/potential semantics**: Open. Concrete type is
   `frozenset[str]`. Semantic interpretation (what do the strings mean
   to a Vertex?) unresolved. Tick.origin connects here — horizon could
   filter by origin. Needs real usage to drive.

8. **Monorepo name**: Still prism.
