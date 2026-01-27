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

4. **Tick-to-Fact conversion**: Open. When a Tick propagates to a new
   vertex, does it arrive as a Fact? What kind? `Fact.tick()` provides
   the `tick.{name}` convention — does Vertex use that on output?

5. **Boundary triggering**: Partially resolved. `Boundary` on Shape
   declares which fact kind completes a cycle. But triggering is still
   manual (`Vertex.tick()`). Auto-triggering (time, count, kind-match)
   is deferred. State-dependent boundaries live in application logic.

6. **Peer horizon/potential semantics**: Open. Concrete type is
   `frozenset[str]`. Semantic interpretation (what do the strings mean
   to a Vertex?) unresolved. Needs real usage to drive.

7. **Monorepo name**: Still prism.
