# CLAUDE.md

The strange-loops monorepo. A system for focusing attention.

See `STRANGE-LOOPS.md` for the paradigm — three shapes, four properties, one pattern.
See `ARCHITECTURE.md` for why it's built this way — libraries, persistence, rendering.

## Build & Test

```bash
uv sync                                                # install all workspace packages
uv run --package <name> pytest libs/<name>/tests       # test one lib
uv run --package <name> pytest apps/<name>/tests       # test one app
```

Each lib and app with a `./dev` script also supports `./dev check` (the CI gate).

## Structure

```
libs/
  atoms/      Fact, Spec, Source, Parse, Fold — the three shapes and ingress
  engine/     Vertex, Loop, Store, Peer, Grant — the pattern and persistence
  lang/       KDL loader + validator for .loop/.vertex files
  painted/    Terminal lenses — Block, Style, Surface, run_cli, zoom levels
  store/      Store operations — slice, merge, search, transport

apps/
  loops/      CLI — emit, log, status, store across vertices
  hlab/       Homelab monitoring — DSL-driven status, alerts, media
  strange-loops/  Task orchestration — tasks as loops, workers in worktrees

experiments/  Integration explorations and dissolved apps
docs/         Deep dives — VERTEX.md, TEMPORAL.md, PERSISTENCE.md, IDENTITY.md
```

Each lib and app has its own CLAUDE.md. Start there when working in one.

## Project Knowledge

Two stores accumulate decisions, threads, and tasks. Query from anywhere:

```bash
uv run loops status project                           # this repo — architecture, API, implementation
uv run loops status meta                              # cross-cutting — ways of working, patterns, tooling
uv run loops log project --kind decision              # project decisions
uv run loops log meta --kind decision --since 7d      # recent cross-cutting decisions
```

**Project store** (`.loops/project.vertex`): architecture, API design, lib boundaries.

**Meta store** (`meta-discussion/meta.vertex`): cross-cutting patterns that apply to any project.

## Conventions

- Immutable by default — frozen dataclasses, pure functions
- `engine` depends on `atoms` (TYPE_CHECKING only). No other cross-lib imports.
- Each lib/app has: CLAUDE.md, pyproject.toml, src/, tests/
- `./dev check` must pass before commit
