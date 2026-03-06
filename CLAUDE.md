# CLAUDE.md

The strange-loops monorepo. A system for focusing attention.

See `STRANGE-LOOPS.md` for the paradigm — three shapes, four properties, one pattern.
See `ARCHITECTURE.md` for why it's built this way — libraries, persistence, rendering.

## Where to start

Each lib and app has its own progressive CLAUDE.md. Start at the level that matches your intent:

**Most work is configuration, not code.** The abstraction chain runs:

```
config (declare)  →  loops CLI (use)  →  engine (runtime)  →  atoms (data)
~/.config/loops/     emit/fold/stream    Vertex, Store        Fact, Spec
```

- **Query or emit** → `apps/loops/CLAUDE.md` Level 0
- **New vertex, lens, or data domain** → `config/CLAUDE.md` Levels 1–2
- **Modify a CLI command** → `apps/loops/CLAUDE.md` Level 2
- **Change data primitives** → `libs/atoms/CLAUDE.md`
- **Change runtime behavior** → `libs/engine/CLAUDE.md`
- **Change rendering** → `libs/painted/src/painted/CLAUDE.md` (consumer) or `libs/painted/CLAUDE.md` (contributor)

## Build & Test

```bash
uv sync                                                # install all workspace packages
uv run --package <name> pytest libs/<name>/tests       # test one lib
uv run --package <name> pytest apps/<name>/tests       # test one app
```

Each lib and app with a `./dev` script also supports `./dev check` (the CI gate).

## Structure

```
config/             User-level vertex declarations, lenses, hooks (mirrors ~/.config/loops/)

libs/
  atoms/            Fact, Spec, Source, Parse, Fold — the three shapes and ingress
  engine/           Vertex, Loop, Store, Peer, Grant — the pattern and persistence
  lang/             KDL loader + validator for .loop/.vertex files
  painted/          Terminal rendering — Block, Style, Surface, run_cli, zoom levels
  store/            Store operations — slice, merge, search, transport

apps/
  loops/            CLI — emit, fold, stream, store across vertices
  hlab/             Homelab monitoring — DSL-driven status, alerts, media
  siftd/            Conversation search — exchanges as facts, FTS5
  strange-loops/    Task orchestration — tasks as loops, workers in worktrees

experiments/        Integration explorations and dissolved apps
docs/               Deep dives — VERTEX.md, TEMPORAL.md, PERSISTENCE.md, IDENTITY.md
meta-discussion/    Cross-cutting design space — patterns, principles, ways of working
```

## Project Knowledge

Two stores accumulate decisions, threads, and tasks. Query from anywhere:

```bash
uv run loops fold project                              # this repo — architecture, API, implementation
uv run loops fold meta                                 # cross-cutting — ways of working, patterns, tooling
uv run loops stream project --kind decision            # project decisions
uv run loops stream meta --kind decision --since 7d    # recent cross-cutting decisions
```

**Project store** (`.loops/project.vertex`): architecture, API design, lib boundaries.

**Meta store** (`meta-discussion/meta.vertex`): cross-cutting patterns that apply to any project.

## Conventions

- Immutable by default — frozen dataclasses, pure functions
- `engine` depends on `atoms` (TYPE_CHECKING only). No other cross-lib imports.
- Each lib/app has: CLAUDE.md, pyproject.toml, src/, tests/
- `./dev check` must pass before commit
