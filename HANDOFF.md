# HANDOFF

Session continuity for the monorepo. Per-library details live in each lib's
own HANDOFF.md.

## The Model

See `LOOPS.md` for the fundamental model. See `VOCABULARY.md` for definitions.

**Three atoms:** Fact, Spec, Tick

**Two libraries:**
- **atoms** — what data looks like, how to get it (Fact, Spec, Source, Parse, Fold)
- **vertex** — how it runs, when boundaries fire, compiles DSL to runtime (Vertex, Loop, Store, Grant, Compiler, Program)

**One DSL:** dsl — `.loop` and `.vertex` file parser, pure grammar (AST + loader + validator, zero runtime deps)

**Two apps:**
- **loops** — CLI for `.loop`/`.vertex` files (`uv run loops validate/compile/test/run/start/store`)
- **hlab** — Homelab monitoring CLI (`uv run hlab status/alerts/media audit`)

**One surface:** cells — terminal UI, separate concern

## Architecture

```
dsl → ckdl                          (pure grammar)
vertex → atoms, dsl                 (runtime + compiler)
apps/loops → dsl, atoms, vertex, cells  (CLI app)
apps/hlab → atoms, vertex, cells    (no direct dsl dep)
```

Key separation: `dsl` is portable (only depends on `ckdl`). The compiler
backend (`vertex.compiler`) and program orchestration (`vertex.program`)
live in vertex where the target runtime types are defined.

## Libraries

| Library | Focus |
|---------|-------|
| **atoms** | Observation + Contract + Ingress: Fact, Spec, Source, Parse, Fold |
| **vertex** | Runtime + Identity + Compiler: Tick, Vertex, Loop, Store, StoreReader, Peer, Grant, compile_loop, load_vertex_program |
| **dsl** | Pure grammar: .loop/.vertex files → AST, loader, validator (zero runtime deps) |
| **cells** | Terminal UI: Cell, Block, Buffer, Surface |

## Documentation

| Doc | Purpose |
|-----|---------|
| `LOOPS.md` | The fundamental model — truths, atoms, data flow |
| `VOCABULARY.md` | Canonical definitions — concepts vs types, verbs |
| `CLAUDE.md` | Build commands, structure, conventions |
| `LOG.md` | Session history — what happened when |
| `docs/VERTEX.md` | Routing, folding, branching |
| `docs/TEMPORAL.md` | Boundaries and nesting |
| `docs/PERSISTENCE.md` | Durable state, replay |
| `docs/CADENCE.md` | Cadence/Source split — when vs what |

## Run Guide

### Loops CLI

```bash
uv run loops validate disk.loop          # syntax check
uv run loops test disk.loop -i sample    # test parse pipeline
uv run loops run disk.loop               # execute, print facts
uv run loops compile system.vertex       # show compiled structure
uv run loops start system.vertex         # run vertex (one round, rendered)
uv run loops store system.vertex         # inspect persisted store contents
uv run loops store data/store.db         # inspect .db directly
```

### hlab App

```bash
uv run hlab status              # stack container status
uv run hlab status -q           # one-liner
uv run hlab status -v           # detailed
uv run hlab status --json       # JSON output
uv run hlab alerts              # Prometheus alerts
uv run hlab media audit         # media corruption scan
```

### Nested Vertex Discovery

The DSL supports `discover:` for auto-finding child vertices:

```bash
uv run loops compile experiments/nested_flow/root.vertex
```

### TUI Experiments

```bash
uv run python experiments/cadence_viz.py      # nested temporal cascade
uv run python experiments/fidelity_lens.py    # zoom-to-fidelity lens
uv run python experiments/nested_flow/viz.py  # sibling fan-out
```

## Import Guide

```python
# Grammar (dsl — pure, no runtime deps)
from dsl import parse_loop_file, parse_vertex_file, validate

# Compiler + runtime (vertex)
from vertex import compile_loop, compile_vertex, load_vertex_program
from vertex import VertexProgram, materialize_vertex, Vertex, Tick

# Read-only store inspection (vertex)
from vertex import StoreReader
```

## Current Focus: apps/hlab — First Real App

**Active iteration target.** All homelab monitoring work happens here until further notice.
`experiments/homelab/` is archived predecessor — don't develop there.

### Structure

```
apps/hlab/
├── loops/
│   ├── status.vertex         # Template-based: 4 stacks from 1 template
│   ├── alerts.vertex         # Prometheus alerts pipeline
│   ├── media_audit.vertex    # Radarr media audit pipeline
│   └── stacks/
│       └── status.loop       # Template: ${kind}, ${host} placeholders
├── commands/
│   ├── status.py             # from vertex import load_vertex_program
│   ├── alerts.py             # from vertex import VertexProgram, load_vertex_program
│   └── media_audit.py        # from vertex import load_vertex_program
├── folds.py                  # Fold overrides: health_fold only
├── lenses/                   # Zoom-level rendering
└── main.py                   # Entry point
```

### What Works

- **Template sources** — One .loop template instantiated with parameter table
- **Per-stack kinds** — Template expands to N sources with ${kind} substitution
- **tick.name IS the stack** — No re-grouping in render
- **Fidelity rendering** — Zoom 0-3 controls detail level via cells
- **Polling** — `every "30s"` for live updates

## Next Steps

1. **Actions** — keypress → fact → automation loop (restart container)
2. **Persistence** — SqliteStore for tick history, replay on startup

## Open Threads (Deferred)

- **String structure** — observer, kind, origin namespacing. Pattern hasn't
  emerged yet.

- **Consumer logic** — ranking/sorting for display is custom code. Right
  boundary?

- **Store policy** — ephemeral, sliding window, sampling. Use case will clarify.

- **Boundary reset** — DSL hardcodes `reset=True`. Consider `reset: false` syntax.

- **Sole remaining fold override** — `health_fold` computes derived metrics
  (healthy/total) not expressible as a single fold op. Could be a `collect` +
  post-fold transform, but that's a new DSL concept. Defer until a second case
  emerges.

## Resolved

76. ~~Store viewer: `loops store`~~ — Read-only store inspection via `StoreReader` (vertex)
    + `commands/store.py` (data fetch) + `lenses/store.py` (zoom-aware render). StoreReader
    takes only a `Path`, uses `PRAGMA query_only=ON`, provides `summary()`, `recent_ticks()`,
    `recent_facts()`. Follows hlab's three-layer pattern: command (fetch) / lens (render) /
    main (routing). Zoom-aware enrichment at fetch layer (aggregates at low zoom, payloads at
    high zoom). 10 StoreReader tests, 20 SqliteStore tests unchanged.

75. ~~Decouple DSL from runtime~~ — `dsl` is now pure grammar (ast/loader/validator,
    depends only on ckdl). Compiler backend (`mapper.py` → `vertex/compiler.py`) and
    program orchestration (`program.py` → `vertex/program.py`) moved to vertex. CLI
    (`cli.py` → `apps/loops/main.py`) moved to new `apps/loops` workspace member.
    hlab drops direct dsl dependency. Vertex gains `register()` → Loop unification
    (deleted `_FoldEngine`), `Tick.to_dict/from_dict`, `SqliteStore` for tick persistence.
    435 tests across dsl (84), vertex (332), loops (19).

74. ~~Spec-first: full 4-step plan complete~~ — Multi-session plan. Steps 1-3: Added
    `Explode`, `Project`, `Where` parse ops to data + dsl. `run_parse_many()` for
    one-to-many pipelines. Rewrote all 5 Prometheus/Radarr `.loop` files with declarative
    parse blocks. Deleted 5 fold overrides (~120 lines) from `folds.py`. Rewired `alerts.py`
    and `media_audit.py` to use DSL-native folds. Only `health_fold` remains (genuine
    computation). Also: `VertexProgram.run()`/`collect()`, `load_vertex_program()` in CLI,
    store wiring, KDL migration. Step 4: Wired cells fidelity into `loop start` —
    `add_cli_args` for `-q`/`-v`/`--json`/`--plain` flags, `detect_context` for TTY-aware
    rendering, `shape_lens` for structured tick payload display. 286 data tests, 182 DSL tests.

73. ~~DSL source templates~~ — Parameterized source templates with `${var}` placeholders. Vertex
    declares `template:` + `with:` parameter table + optional `loop:` spec. Template instantiated
    per-row, variables substituted in source command, kind, and boundary condition. Collapsed
    4 nearly-identical .loop files → 1 template, 4 identical loop defs → 1 spec with ${kind}.
    Added `SourceParams`, `TemplateSource` AST types. Lexer handles ${} in identifiers. Parser
    handles `template:`/`with:`/`loop:` blocks. Mapper has `substitute_vars()`, `compile_sources()`.
    180 DSL tests. hlab produces identical output with cleaner config.

72. ~~hlab fold→lens~~ — `fold_overrides` for health computation (healthy/total in tick payload),
    `stack_lens` for zoom-level rendering. main.py is now pure orchestration — domain logic in
    fold, presentation in lens. -75 lines net in main.py.

71. ~~apps/hlab first app~~ — Created `apps/hlab/` as the first real app. Added `format: ndjson`
    to Source for JSON lines. Added `select` parse op for field extraction from JSON. Built
    proof.py, infra.loop, status.vertex. Cells-based TUI with fidelity zoom (0-3). Explored
    ancestor codebases (gruel.network, zsh config, hlab) for patterns.

See `LOG.md` for older resolved items and full session history.
