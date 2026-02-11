# HANDOFF

Session continuity for the monorepo. Per-library details live in each lib's
own HANDOFF.md.

## The Model

See `LOOPS.md` for the fundamental model. See `VOCABULARY.md` for definitions.

**The Bet:** The cycle is the unit of computation.

**Three atoms:** Fact, Spec, Tick

**Four libraries (2+2):**
- **atoms** — what data looks like, how to get it (Fact, Spec, Source, Parse, Fold)
- **engine** — how it runs, when boundaries fire, compiles DSL to runtime (Vertex, Loop, Tick, Store, Grant, Compiler, Program)
- **lang** — `.loop` and `.vertex` file parser, pure grammar (AST + loader + validator, zero runtime deps)
- **cells** — terminal UI, separate concern

**Three apps:**
- **loops** — CLI for `.loop`/`.vertex` files (`uv run loops validate/compile/test/run/start/store`)
- **hlab** — Homelab monitoring CLI (`uv run hlab status/alerts/media audit`)
- **reader** — Personal reading intelligence (`uv run reader reactions/feeds`)

## Architecture

```
lang → ckdl                             (pure grammar)
engine → atoms, lang                    (runtime + compiler)
apps/loops → lang, atoms, engine, cells (CLI app)
apps/hlab → atoms, engine, cells        (no direct lang dep)
```

Key separation: `lang` is portable (only depends on `ckdl`). The compiler
backend (`engine.compiler`) and program orchestration (`engine.program`)
live in engine where the target runtime types are defined.

## Libraries

| Library | Focus |
|---------|-------|
| **atoms** | Observation + Contract + Ingress: Fact, Spec, Source, Parse, Fold |
| **engine** | Runtime + Identity + Compiler: Tick, Vertex, Loop, Store, StoreReader, Peer, Grant, compile_loop, load_vertex_program |
| **lang** | Pure grammar: .loop/.vertex files → AST, loader, validator (zero runtime deps) |
| **cells** | Terminal UI: Cell, Block, Buffer, Surface, Zoom, Lens |

## Documentation

| Doc | Purpose |
|-----|---------|
| `LOOPS.md` | The fundamental model — truths, atoms, data flow |
| `VOCABULARY.md` | Canonical definitions — Bet, Frame, Atoms, Rules, Libraries, Dissolutions |
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

### reader App

```bash
uv run reader reactions              # HN favorites
uv run reader feeds                  # subscribed feeds
uv run reader feeds add lobsters https://lobste.rs/rss   # add feed
uv run reader feeds rm lobsters      # remove feed
```

### Nested Vertex Discovery

The lang supports `discover:` for auto-finding child vertices:

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
# Grammar (lang — pure, no runtime deps)
from lang import parse_loop_file, parse_vertex_file, validate

# Compiler + runtime (engine)
from engine import compile_loop, compile_vertex, load_vertex_program
from engine import VertexProgram, materialize_vertex, Vertex, Tick

# Read-only store inspection (engine)
from engine import StoreReader
```

## Current Focus

**apps/loops** is the general-purpose CLI for the loops system (validate, test,
run, compile, start, store). **apps/hlab** is the first domain app.
**apps/reader** is the second domain app (personal reading intelligence).
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
│   ├── status.py             # from engine import load_vertex_program
│   ├── alerts.py             # from engine import VertexProgram, load_vertex_program
│   └── media_audit.py        # from engine import load_vertex_program
├── folds.py                  # Fold overrides: health_fold only
├── lenses/                   # Zoom-level rendering
└── main.py                   # Entry point

apps/reader/
├── loops/
│   ├── feeds.vertex          # from file — population from feeds.list
│   ├── reactions.vertex      # HN favorites via template source
│   ├── feeds.list            # External feed population (kind + URL)
│   └── sources/
│       └── feed.loop         # Unified RSS/Atom template (auto-detect)
└── src/reader/
    ├── config.py             # resolve_vars() for env-based substitution
    └── main.py               # reactions, feeds, feeds add/rm
```

### What Works

- **Template sources** — One .loop template instantiated with parameter table
- **Per-stack kinds** — Template expands to N sources with ${kind} substitution
- **`from file`** — External parameter source for templates. Population lives
  outside KDL. `feeds.list` is a header + data rows file.
- **`--var` flag** — `loops run/start` accept `--var KEY=VALUE` for vertex vars
- **tick.name IS the stack** — No re-grouping in render
- **Zoom rendering** — Zoom 0-3 controls detail level via cells
- **Polling** — `every "30s"` for live updates

## Next Steps

1. **Self-feeding detection** — `Fact.origin` now distinguishes external
   observations (`origin=""`) from derived facts. Build a query or fold that
   computes exhaust ratio: "what fraction of this loop's input is its own
   output?" Store has the data; the safeguard logic doesn't exist yet.
2. **`loops store` refresh loop** — Periodic re-fetch for live vertex viewing.
   SQLite concurrent readers make this straightforward. `start` and `store`
   may converge.
3. **Actions** — keypress → fact → automation loop (restart container)

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

- **Tick provenance** — should Tick carry `kinds_consumed`? Would make zoom
  drill show consumed facts, not just time-window facts.

- **Self-feeding risk** — when conclusions feed back as observations, the system
  can amplify its own output. Named in VOCABULARY.md Rule #7. `Fact.origin`
  now provides the structural basis for detection (external vs derived), but
  no safeguard logic exists yet. Becomes urgent when LLM-as-peer is implemented.

## Resolved

80. ~~`from file` + reader app + `--var`~~ — External parameter sources for templates.
    `FromFile` dataclass in lang AST, `_load_params_file()` in engine compiler.
    Reader app with feeds/reactions vertices, unified feed.loop (RSS+Atom auto-detect),
    `feeds add/rm` CLI commands. `--var KEY=VALUE` on loops run/start. 89 lang tests,
    357 engine tests.

79. ~~Add `origin` to Fact~~ — `origin: str = ""` on Fact, mirroring Tick's existing
    field. External observations get `""`, derived facts (from tick-to-fact bridging)
    carry the producing vertex name. `to_fact()` and `_tick_to_fact()` now preserve
    `tick.origin`. SqliteStore schema updated with idempotent migration for existing
    DBs. StoreReader queries return origin. VOCABULARY.md updated. 707 tests pass.

78. ~~Post-rename audit~~ — Full repo sweep for stale data/dsl/vertex references.
    All docs updated to atoms/lang/engine. No stale code imports found. Tests pass.

77. ~~Vocabulary revision~~ — Full restructure of VOCABULARY.md via four-agent
    team session (siftd + muser + cold-reader + lead). New structure: Bet →
    Frame → Atoms → Rules → Libraries → Dissolutions. Elevated "loop" to
    first-class concept. Named self-feeding risk. Library renames decided and
    merged: data→atoms, dsl→lang, vertex→engine. "The cycle is the unit of
    computation."

76. ~~Ticks-first store explorer~~ — Reoriented store viewer: ticks are primary,
    facts reachable via fidelity drill. Rich list items with sparkline + count +
    freshness + payload keys. `tick_timestamps()` on StoreReader for sparkline data
    without payload parsing. Adaptive TUI layout (drops chrome on small terminals).
    Fidelity dissolved into lens + zoom. Live/stored dissolved into refresh loop.
    48 tests.

75. ~~Store viewer: `loops store`~~ — Read-only store inspection via `StoreReader` (engine)
    + `commands/store.py` (data fetch) + `lenses/store.py` (zoom-aware render). StoreReader
    takes only a `Path`, uses `PRAGMA query_only=ON`, provides `summary()`, `recent_ticks()`,
    `recent_facts()`. Follows hlab's three-layer pattern: command (fetch) / lens (render) /
    main (routing). Zoom-aware enrichment at fetch layer (aggregates at low zoom, payloads at
    high zoom). 10 StoreReader tests, 20 SqliteStore tests unchanged.

74. ~~Decouple DSL from runtime~~ — `lang` is now pure grammar (zero deps beyond ckdl). The compiler
    backend (`mapper.py` → `engine/compiler.py`) and program orchestration (`program.py` →
    `engine/program.py`) moved to engine. CLI (`cli.py` → `apps/loops/main.py`) moved to new
    `apps/loops` workspace member. hlab drops direct lang dependency, imports compiler symbols
    from engine. 435 tests across lang (84), engine (332), loops (19).

73. ~~Spec-first: full 4-step plan complete~~ — Multi-session plan. Steps 1-3: Added
    `Explode`, `Project`, `Where` parse ops to atoms + lang. `run_parse_many()` for
    one-to-many pipelines. Rewrote all 5 Prometheus/Radarr `.loop` files with declarative
    parse blocks. Deleted 5 fold overrides (~120 lines) from `folds.py`. Rewired `alerts.py`
    and `media_audit.py` to use DSL-native folds. Only `health_fold` remains (genuine
    computation). Also: `VertexProgram.run()`/`collect()`, `load_vertex_program()` in CLI,
    store wiring, KDL migration. Step 4: Wired cells zoom into `loop start` —
    `add_cli_args` for `-q`/`-v`/`--json`/`--plain` flags, `detect_context` for TTY-aware
    rendering, `shape_lens` for structured tick payload display. 286 atoms tests, 182 lang tests.

72. ~~DSL source templates~~ — Parameterized source templates with `${var}` placeholders. Vertex
    declares `template:` + `with:` parameter table + optional `loop:` spec. Template instantiated
    per-row, variables substituted in source command, kind, and boundary condition. Collapsed
    4 nearly-identical .loop files → 1 template, 4 identical loop defs → 1 spec with ${kind}.
    Added `SourceParams`, `TemplateSource` AST types. Lexer handles ${} in identifiers. Parser
    handles `template:`/`with:`/`loop:` blocks. Mapper has `substitute_vars()`, `compile_sources()`.
    180 lang tests. hlab produces identical output with cleaner config.

71. ~~hlab fold→lens~~ — `fold_overrides` for health computation (healthy/total in tick payload),
    `stack_lens` for zoom-level rendering. main.py is now pure orchestration — domain logic in
    fold, presentation in lens. -75 lines net in main.py.

70. ~~apps/hlab first app~~ — Created `apps/hlab/` as the first real app. Added `format: ndjson`
    to Source for JSON lines. Added `select` parse op for field extraction from JSON. Built
    proof.py, infra.loop, status.vertex. Cells-based TUI with zoom (0-3). Explored
    ancestor codebases (gruel.network, zsh config, hlab) for patterns.

See `LOG.md` for older resolved items and full session history.
