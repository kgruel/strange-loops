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
| **facts** | Event | kind + data + ts | *what* | narrative |
| **ticks** | Tick | timestamp + payload | *when* | temporal |
| **shapes** | Shape | facets + folds | *how* | geometric |
| **cells** | Cell | char + style | *where* | spatial |

### Data Flow

The pipeline is a loop. You are a Peer in it.

    ┌─────────────────────────────────────────────────────────┐
    │  You (Peer) — your choices become new Events            │
    │                                                         │
    ▼                                                         │
  Event                                            facts      │
    │                                                         │
    ▼                                                         │
  Stream[Event] ─── tap ──→ any external consumer  ticks      │
    │                                                         │
    ├──→ Store ──→ FileWriter                      ticks      │
    │                                                         │
    ▼                                                         │
  Projection ← Shape                          ticks + shapes  │
    │                                                         │
    ├── live state ──→ Lens → Block → You ────────────────────┘
    │                              cells   peers
    │
    └── Tick[state] ──→ Stream[Tick] ─── tap ──→ any external consumer
                              │                      ticks
                              ▼
                         downstream
                   (project, persist, serve)

A Peer emits an Event. The Event flows through a Stream. A
Projection applies a Shape to fold events into state. You see
state through a Lens rendered as Cells. Your choices become new
Events — the loop continues.

At a temporal boundary, the folded state becomes a Tick — a frozen
snapshot. Ticks flow downstream as a new Stream for further
projection, persistence, or serving. Streams can be tapped at any
point to split off to external consumers without interrupting
the main pipeline.

### Core Libraries (libs/)

| Package | Atom | Purpose |
|---------|------|---------|
| **peers** | Peer | Scoped identity: name + scope (see, do, ask). Delegation creates child peers with narrower scope — the hierarchy encodes participation level (direct, delegated, automated). |
| **facts** | Event | Semantic contract: kind + data + ts. Result for completion. Emitter protocol. |
| **ticks** | Tick | Temporal envelope: ts + payload. Infrastructure: Stream, Store, Projection, FileWriter, Tailer. A Tick is a frozen snapshot at a temporal boundary — the output of folding events through a Shape over a period. |
| **shapes** | Shape | Data contracts: Facet (name + kind), Fold (op + target), Shape (facets + folds). Defines how events become state. |
| **cells** | Cell | Terminal UI: Cell, Block, Buffer, Span, Layer, Lens, RenderApp |

All libraries are independent — no lib imports another. They compose in experiments.

### Peer Participation

A Peer's level of participation is encoded in the delegation hierarchy,
not as a separate type. The root peer acts directly; children act on
behalf of the root with restricted scope.

    You (Peer: "kyle")                      → direct, full scope
      ├─ delegate("kyle/deploy-agent")      → autonomous, narrower scope
      ├─ delegate("kyle/backup-cron")       → automated, narrowest scope
      └─ delegate("kyle/subtask-worker")    → delegated, task-scoped

Stance (direct, guided, delegated, automated, observing) is an emergent
property of the topology — which peer emitted the event tells you the
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
- Shape is the contract at every boundary — describes what data looks like
