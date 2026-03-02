# CLAUDE.md

The loops monorepo. See `LOOPS.md` for the fundamental model — three atoms (Fact, Spec, Tick), three truths, everything is loops.

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
  atoms/      Fact, Spec, Source, Parse, Fold — the data atoms and contracts
  engine/     Tick, Vertex, Store, Projection, Peer, Grant — runtime and identity
  lang/       KDL loader + validator for .loop/.vertex files
  painted/    Terminal rendering — Block, Style, Surface, run_cli, lenses
  store/      Store operations — slice, merge, search, transport

apps/
  loops/      CLI for the loops system — emit, log, status across vertices
  hlab/       Homelab monitoring — DSL-driven status, alerts, media
  strange-loops/  Task orchestration — tasks as loops, workers in worktrees

experiments/  Integration explorations and dissolved apps (discord, telegram, reader DSL files)
docs/         Deep dives — VERTEX.md, TEMPORAL.md, PERSISTENCE.md, IDENTITY.md
```

Each lib and app has its own CLAUDE.md. Start there when working in one.

## Project Knowledge

Two stores accumulate decisions, threads, and tasks. Query from anywhere:

```bash
loops status project                           # this repo — architecture, API, implementation
loops status meta                              # cross-cutting — ways of working, patterns, tooling
loops log project --kind decision              # project decisions
loops log meta --kind decision --since 7d      # recent cross-cutting decisions
```

**Project store** (`project.vertex`): loops-specific architecture, API design, lib boundaries.

**Meta store** (`~/Documents/meta-discussion`): cross-cutting patterns that apply to any project. Key decisions that govern how we work:
- `architecture/claude-md-levels` — four levels, each adds not repeats
- `architecture/claude-md-antipatterns` — God/stale/redundant/missing
- `architecture/doc-roles` — CLAUDE.md is working context, README for API consumers
- `workflow/handoff-as-fact` — handoff dissolves into the store
- `design/dissolution-method` — before building X, ask if X dissolves
- `design/progressive-vertex-chain` — CLAUDE.md is the lens, the store is the state

## Conventions

- Immutable by default — frozen dataclasses, pure functions
- `engine` depends on `atoms` (TYPE_CHECKING only). No other cross-lib imports.
- Each lib/app has: CLAUDE.md, pyproject.toml, src/, tests/
- `./dev check` must pass before commit
