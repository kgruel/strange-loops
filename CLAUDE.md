# CLAUDE.md

This file provides guidance to Claude Code when working with the prism monorepo.

## Build & Test Commands

```bash
# Install all workspace dependencies
uv sync

# Run tests for a specific package
uv run --package peers pytest libs/peers/tests
uv run --package facts pytest libs/facts/tests
uv run --package ticks pytest libs/ticks/tests
uv run --package shapes pytest libs/shapes/tests
uv run --package cells pytest libs/cells/tests

# Run a single test file
uv run --package cells pytest libs/cells/tests/test_span.py
```

## Architecture

`prism` is a uv workspace monorepo. Five core libraries, each with one atom.

### Atoms

| Package | Atom | Structure | Question | Metaphor |
|---------|------|-----------|----------|----------|
| **peers** | Peer | name + scope | *who* | social |
| **facts** | Fact | kind + ts + payload | *what* | narrative |
| **ticks** | Tick | ts + payload | *when* | temporal |
| **shapes** | Shape | facets + folds + apply | *how* | geometric |
| **cells** | Cell | char + style | *where* | spatial |

### Data Flow

The pipeline is a loop. You are a Peer in it.

    ┌─────────────────────────────────────────────────────────┐
    │  You (Peer) — your choices become new Facts             │
    │                                                         │
    ▼                                                         │
  Fact                                             facts      │
    │                                                         │
    ▼                                                         │
  Stream[Fact] ─── tap ──→ any external consumer   ticks      │
    │                                                         │
    ├──→ Store ──→ FileWriter                      ticks      │
    │                                                         │
    ▼                                                         │
  Projection(fold=shape.apply) ← Shape        ticks + shapes  │
    │                                                         │
    ├── live state ──→ Lens → Block → You ────────────────────┘
    │                              cells   peers
    │
    └── Tick[state] ──→ Stream[Tick] ─── tap ──→ any external consumer
                              │                      ticks
                              ▼
                         downstream
                   (project, persist, serve)

A Peer observes a Fact. The Fact flows through a Stream. A
Projection applies a Shape (via shape.apply) to fold facts into
state. You see state through a Lens rendered as Cells. Your
choices become new Facts — the loop continues.

At a temporal boundary, the folded state becomes a Tick — a frozen
snapshot. Ticks flow downstream as a new Stream for further
projection, persistence, or serving. Streams can be tapped at any
point to split off to external consumers without interrupting
the main pipeline.

### Feedback Loop (Surface → Facts)

Surface (cells) is the bidirectional boundary — renders state outward,
emits interactions inward. Facts enter the pipeline from two sources:
external observations (a deploy happened) and your own interactions
(you pressed a key, selected an item). Both are Fact. Both flow
through the same Stream. The pipeline doesn't distinguish.

Surface emits at three strata:

    Stratum        Auto?   Kind       Example payload
    ────────────────────────────────────────────────────────
    Raw input      yes     "key"      {key: "j"}
    UI structure   yes     "action"   {action: "pop", layer: "confirm"}
                   yes     "resize"   {width: 80, height: 24}
    Domain         no      (any)      {item: "deploy-prod"}

`Emit = Callable[[str, dict], None]` — cells defines the callback type,
the integration layer wires it to `Fact.of()` + `Stream.emit()`. No
cross-lib imports. The loop closes.

### Core Libraries (libs/)

| Package | Atom | Purpose |
|---------|------|---------|
| **peers** | Peer | Scoped identity: name + scope (see, do, ask). Delegation creates child peers with narrower scope — the hierarchy encodes participation level (direct, delegated, automated). |
| **facts** | Fact | Observation atom: kind + ts + payload. An intentional observation — something that happened at a specific time. Kind is an open string for routing; payload structure comes from Shape. |
| **ticks** | Tick | Temporal envelope: ts + payload. Infrastructure: Stream, Store, Projection, FileWriter, Tailer. A Tick is a frozen snapshot at a temporal boundary — the output of folding facts through a Shape over a period. |
| **shapes** | Shape | Data contracts: Facet (name + kind), Fold (op + target), Shape (facets + folds + apply). Shape.apply(state, payload) executes folds — pure dict→dict, no cross-lib imports. |
| **cells** | Cell | Terminal UI: Cell, Block, Buffer, Span, Layer, Lens, Surface |

All libraries are independent — no lib imports another. They compose in experiments.

Each lib has its own `CLAUDE.md` with detailed API, invariants, and source layout.
Each lib has its own `HANDOFF.md` with change log and open threads.

### Peer Participation

A Peer's level of participation is encoded in the delegation hierarchy,
not as a separate type. The root peer acts directly; children act on
behalf of the root with restricted scope.

    You (Peer: "kyle")                      → direct, full scope
      ├─ delegate("kyle/deploy-agent")      → autonomous, narrower scope
      ├─ delegate("kyle/backup-cron")       → automated, narrowest scope
      └─ delegate("kyle/subtask-worker")    → delegated, task-scoped

Stance (direct, guided, delegated, automated, observing) is an emergent
property of the topology — which peer observed the fact tells you the
participation level. No enum needed; the identity is the stance.

### experiments/

Integration layer that wires the libraries together. Contains `framework/` (reusable patterns), `apps/` (concrete applications), `specs/` (declarative config), and `tests/`.

### demos/cells/

Standalone demo scripts and teaching materials extracted from the cells library.

## Key Patterns

- All libs use `src/` layout with hatchling (except facts which uses uv_build)
- Workspace dependencies use `{ workspace = true }` in `[tool.uv.sources]`
- Each lib has its own pyproject.toml, tests/, and build config
- Immutable by default: frozen dataclasses, pure functions, compose don't mutate
- Shape is the contract at every boundary — describes what data looks like and how to fold it
- Projection accepts a fold callable: `Projection(initial, fold=shape.apply)` — no bridge class needed
- Facts go in, Ticks come out: Fact is the raw observation (input), Tick is the derived snapshot (output)
