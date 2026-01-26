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

`prism` is a uv workspace monorepo containing five core libraries and an experiments layer.

### Core Libraries (libs/)

| Package | Purpose |
|---------|---------|
| **peers** | Scoped identity primitives: Peer = name + scope |
| **facts** | Renderer-agnostic semantic contract for CLI output (Event/Result/Emitter) |
| **ticks** | Personal-scale event infrastructure (Stream, EventStore, Projection, FileWriter, Tailer) |
| **shapes** | Declarative schema shapes (Field, Fold, Form) |
| **cells** | Cell-buffer terminal UI framework (Cell, Buffer, Block, Span, Layer, App) |

### Dependency Flow

```
peers (identity) ─┐
facts (events)  ──┤
shapes (schema) ──┼── experiments (apps + framework)
ticks (streams) ──┤
cells (terminal) ─┘
```

### experiments/

Integration layer that wires the libraries together. Contains `framework/` (reusable patterns), `apps/` (concrete applications), `specs/` (declarative config), and `tests/`.

### demos/cells/

Standalone demo scripts and teaching materials extracted from the cells library.

## Key Patterns

- All libs use `src/` layout with hatchling (except facts which uses uv_build)
- Workspace dependencies use `{ workspace = true }` in `[tool.uv.sources]`
- Each lib has its own pyproject.toml, tests/, and build config
- Blocks are immutable; compose via functions, don't mutate
