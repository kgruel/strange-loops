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

| Package | Atom | Structure | Question |
|---------|------|-----------|----------|
| **peers** | Peer | name + scope | *who* |
| **facts** | Event | kind + data + ts | *what* |
| **ticks** | Tick | timestamp + payload | *when* |
| **shapes** | Shape | facets + folds | *how* |
| **cells** | Cell | char + style | *where* |

### Data Flow

The pipeline is a loop. The human is a Peer in it.

    ┌──────────────────────────────────────────────────────────┐
    │                                                          │
    ▼                                                          │
  Event                                            facts       │
    │                                                          │
    ▼                                                          │
  Stream                                           ticks       │
    │                                                          │
    ▼                                                          │
  Store ──→ FileWriter                             ticks       │
    │                                                          │
    ▼                                                          │
  Projection                                       ticks       │
    │  delegates to Shape                          shapes      │
    │                                                          │
    ▼                                                          │
  state ─── shaped by Shape ───                                │
    │                          │              │                │
    ▼                          ▼              ▼                │
  Lens → Block → You    Store → SQLite    OpenAPI spec         │
  cells          peers   ticks             shapes              │
    │                                                          │
    └──────────────────────────────────────────────────────────┘

State is a dict that conforms to a Shape. Any consumer that reads
the Shape can use the state: render it, persist it, serve it,
or feed it downstream.

### Core Libraries (libs/)

| Package | Atom | Purpose |
|---------|------|---------|
| **peers** | Peer | Scoped identity: name + scope (see, do, ask) |
| **facts** | Event | Semantic contract: kind + data + ts. Result for completion. Emitter protocol. |
| **ticks** | Tick | Event infrastructure: Stream, Store, Projection, FileWriter, Tailer |
| **shapes** | Shape | Data contracts: Facet (name + kind), Fold (op + target), Shape (facets + folds + apply) |
| **cells** | Cell | Terminal UI: Cell, Block, Buffer, Span, Layer, Lens, RenderApp |

All libraries are independent — no lib imports another. They compose in experiments.

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
