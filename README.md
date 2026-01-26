# prism

Scoped, event-driven, schema-shaped, terminal-rendered applications.

A uv workspace monorepo containing five core libraries:

- **peers** — Scoped identity primitives
- **facts** — Semantic contract for CLI output
- **ticks** — Personal-scale event infrastructure
- **shapes** — Declarative schema shapes
- **cells** — Cell-buffer terminal UI framework

## Setup

```bash
uv sync
```

## Test

```bash
uv run --package peers pytest libs/peers/tests
uv run --package facts pytest libs/facts/tests
uv run --package ticks pytest libs/ticks/tests
uv run --package shapes pytest libs/shapes/tests
uv run --package cells pytest libs/cells/tests
```
