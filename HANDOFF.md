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
- **painted** — terminal UI, separate concern (external dep, `~/Code/painted`)

**Three apps:**
- **loops** — CLI for `.loop`/`.vertex` files (`uv run loops validate/compile/test/run/start/store/ls/add/rm`)
- **hlab** — Homelab monitoring CLI (`uv run hlab status/alerts/media audit`)
- **reader** — Personal reading intelligence (`uv run reader reactions/feeds`)

## Architecture

```
lang → ckdl                             (pure grammar)
engine → atoms, lang                    (runtime + compiler)
apps/loops → lang, atoms, engine, painted (CLI app)
apps/hlab → atoms, engine, painted      (no direct lang dep)
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
| **painted** | Terminal UI: Cell, Block, Buffer, Surface, Zoom, Lens, run_cli (external dep) |

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
| `docs/NAMED_SESSIONS.md` | Named sessions — scoped stores, directory convention |
| `apps/hlab/docs/prometheus-alerts-to-loops.md` | Design note: route Prometheus alerts into loops stream, drop Grafana |

## Run Guide

### Loops CLI

```bash
uv run loops validate disk.loop          # syntax check
uv run loops test disk.loop -i sample    # test parse pipeline
uv run loops run disk.loop               # execute, print facts (one round)
uv run loops run disk.loop --daemon      # run continuously
uv run loops compile system.vertex       # show compiled structure
uv run loops start system.vertex         # run vertex (one round, rendered)
uv run loops store system.vertex         # inspect persisted store contents
uv run loops store data/store.db         # inspect .db directly

# Population management (template parameter rows)
uv run loops ls reading                  # list populations in reading vertex
uv run loops ls economy/fred             # specific template in multi-template vertex
uv run loops add reading lobsters https://lobste.rs/rss   # add row
uv run loops rm reading lobsters         # remove row by key
uv run loops export reading              # inline with → .list file
uv run loops import reading              # .list file → inline with
uv run loops merge reading external.list # union external rows into population
```

### Session Continuity (Dissolved)

The `loops session` subcommand group has been dissolved. `status` and `log` are
now top-level commands that work on any local vertex store. `emit` works with
local vertex resolution (cwd first, LOOPS_HOME fallback).

```bash
loops status                                 # decisions, threads, tasks, changes
loops status --json                          # machine-readable
loops log                                    # last 7 days
loops log --since 24h --kind decision        # filtered

# Emit structured observations (vertex resolved from cwd or LOOPS_HOME)
loops emit decision topic="env-passthrough" "drop env line, rely on inheritance"
loops emit change files="compiler.py,source.py" summary="env wiring + test coverage"
loops emit thread name="sigil-migration" status="resolved"
loops emit task name="fix/review" status="merged" summary="env fix + tests"

# Initialize a local vertex
loops init --template session                # session vertex in LOOPS_HOME
loops init --template tasks                  # task-tracking vertex
```

Display commands (`status`, `log`, `store`) route through painted's `run_cli`
harness for automatic zoom/mode/format resolution, JSON serialization, and
styled error rendering. HANDOFF.md and LOG.md remain as reference.

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

# Population management (lang — pure, no runtime deps)
from lang import resolve_vertex, resolve_template, template_name
from lang import PopulationRow, PopulationInfo, read_population

# Compiler + runtime (engine)
from engine import compile_loop, compile_vertex, load_vertex_program
from engine import VertexProgram, materialize_vertex, Vertex, Tick

# Read-only store inspection (engine)
from engine import StoreReader
```

## Current Focus

**apps/strange-loops** is the active frontier — task orchestration built on
loops primitives. Full vertical slice working: create → assign → send → monitor
→ diff → merge → close. Shell harness spawns detached workers that write facts
to the shared store. Query-time fold derives task state. 56 tests, all passing.
Next: orchestrator skill (drive the lifecycle with judgment, not just wrapping
CLI commands) and Claude/Codex harnesses (different commands, same fact pipeline).
See `apps/strange-loops/DESIGN.md` for architecture.

**apps/loops** — full Painted rendering. All 9 display commands through `run_cli`
with zoom-aware lenses, all 5 action commands through `show(Block.text())`. Zero
raw `print()`. 45 golden snapshot tests lock output at all 4 zoom levels.
Auto-generated `apps/loops/docs/CLI.md`. Store targeting: `loops status meta`,
`loops log meta --kind task`, `loops store meta`. 191 tests.

**Meta-discussion workspace** at `~/Documents/meta-discussion/` — cross-project
analysis of development patterns (test layers, dev harness, dissolution method,
scaffold template, etc.). Feeds back into loops via design docs and conventions.

### Bend Experiments (Parked)

Three experiments in `experiments/bend/` confirmed the loops model maps to
interaction combinators. Parked — Python runtime is more productive for current
needs. See Open Threads for Bend2 revisit criteria.

### Structure

```
apps/hlab/
├── loops/
│   ├── status.vertex         # Template-based: 4 stacks from 1 template
│   ├── alerts.vertex         # Prometheus alerts pipeline
│   ├── media_audit.vertex    # Radarr media audit pipeline
│   └── stacks/
│       └── status.loop       # Template: {{kind}}, {{host}} placeholders
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
│       └── feed.loop         # Unified RSS/Atom template (auto-detect, link normalization)
└── src/reader/
    ├── config.py             # resolve_vars() for env-based substitution
    └── main.py               # reactions, feeds, feeds add/rm

apps/loops/
├── src/loops/
│   ├── main.py               # CLI: validate/test/run/start/store/status/log/emit/ls/add/rm
│   ├── commands/
│   │   ├── pop.py            # Population verbs: ls, add, rm, export, import, merge
│   │   ├── session.py        # Local store: fetch_status, fetch_log, emit helpers
│   │   └── store.py          # Store viewer: fetch/render for store (via run_cli)
│   └── lenses/               # Zoom-aware rendering (data, zoom, width) -> Block
│       ├── status.py         # Session status: decisions, threads, tasks, changes
│       ├── log.py            # Session log: chronological facts
│       ├── store.py          # Store inspection: ticks, facts, freshness
│       ├── start.py          # Vertex results: per-tick payloads
│       ├── compile.py        # AST structure: loops, sources, routes
│       ├── validate.py       # Validation results: per-file pass/fail
│       ├── test.py           # Test results: parse pipeline output
│       ├── run.py            # Streaming: facts and ticks
│       └── pop.py            # Population table: template rows
├── docs/
│   └── CLI.md                # Auto-generated from golden test fixtures
└── tests/
    ├── test_cli.py           # Core CLI tests
    ├── test_emit.py          # Emit command tests (6 tests)
    ├── test_session.py       # Session command tests (20 tests)
    ├── test_population.py    # Population CLI integration tests (30 tests)
    └── golden/               # Snapshot tests: every command × every zoom level
        ├── conftest.py       # Golden fixture + --update-goldens flag
        ├── fixtures.py       # Deterministic sample data (fixed timestamps)
        └── test_*.py         # 9 test files, 45 parametrized tests

apps/strange-loops/              # Task orchestration built on loops
├── dev                          # Dev harness (./dev check, test, lint, fmt)
├── scripts/                     # Dev scripts (siftd/painted pattern)
├── src/strange_loops/
│   ├── cli.py                   # Thin dispatcher
│   ├── store.py                 # Shared store helpers (observer, emit_fact, require_store)
│   ├── worktree.py              # Git worktree ops (create, remove, list, diff)
│   ├── harness.py               # Shell harness runner (detached, captures output as facts)
│   └── commands/
│       ├── session.py           # Session lifecycle
│       └── task.py              # Task lifecycle (create→assign→send→monitor→merge→close)
├── tests/                       # 56 tests (store, session, task, worktree, harness)
├── CLAUDE.md                    # Dev conventions + patterns
└── DESIGN.md                    # Architecture + fact kinds + harness interface
```

### What Works

- **Template sources** — One .loop template instantiated with parameter table
- **Per-stack kinds** — Template expands to N sources with {{kind}} substitution
- **`from file`** — External parameter source for templates. Population lives
  outside KDL. `feeds.list` is a header + data rows file.
- **Population management** — `loops ls/add/rm/export/import/merge` for any
  vertex's template populations. Auto-detects storage (file vs inline KDL).
- **`--var` flag** — `loops run/start` accept `--var KEY=VALUE` for vertex vars
- **`--daemon` flag** — `loops run` defaults to one round; `--daemon`/`-d` for continuous
- **Session continuity** — `loops status/log/emit` with local vertex resolution.
  Facts as structured observations, query-time fold for state. `LOOPS_OBSERVER`
  for multi-agent tagging. Correction by re-emit (latest-per-key fold resolves).
- **tick.name IS the stack** — No re-grouping in render
- **Zoom rendering** — Zoom 0-3 controls detail level via painted
- **Polling** — `every "30s"` for live updates
- **run_cli harness** — All 9 display commands route through painted's `run_cli`
  with zoom-aware lenses. Action commands use `show(Block.text())`. Zero raw `print()`.
- **Store targeting** — `loops status meta`, `loops log meta --kind task`,
  `loops store meta` — vertex name resolution for query commands
- **Golden tests** — 45 snapshot tests lock output at all 4 zoom levels.
  Auto-generated `apps/loops/docs/CLI.md` from fixtures.

## Next Steps

1. **Painted help augmentation** — `run_cli --help` currently suppresses
   command-specific args. Open subtask in painted to fix: command help
   primary/prominent, rendering flags secondary/dim, zoom-aware help display.
2. **Self-feeding detection** — `Fact.origin` now distinguishes external
   observations (`origin=""`) from derived facts. Build a query or fold that
   computes exhaust ratio: "what fraction of this loop's input is its own
   output?" Store has the data; the safeguard logic doesn't exist yet.
3. **`loops store` refresh loop** — Periodic re-fetch for live vertex viewing.
   SQLite concurrent readers make this straightforward. `start` and `store`
   may converge.

## Open Threads (Deferred)

- **Bend / interaction combinators** — Three experiments confirmed the model
  maps to Bend (reader, vertex-as-Bend, persistent state). Key finding: Bend
  strips vertex to ~30 lines of pure computation but sprawls at ~3x Python
  for persistence/IO. Python runtime is richer and more productive for current
  needs. Revisit when Bend2 lands (32/64-bit numbers, native IO, spec-as-types
  with AI-proven correctness). HVM3/HVM4 in `~/Code/forks/`. Experiments in
  `experiments/bend/`.

- **Prometheus alerts → loops stream** — Replace Grafana with loops as the
  alert surface. Prometheus stays as collection/alerting engine (~160 MB,
  doing real work). Grafana gets dropped (~175 MB, nobody opens it). Alerts
  become `infra.alert` Facts via polling `/api/v1/alerts` — hlab already has
  the `.loop` files for this. Design note: `apps/hlab/docs/prometheus-alerts-to-loops.md`.

- **Population as facts** — Population commands dissolve into `emit`. Adding
  a row is emitting a `pop.add` fact; removing is `pop.rm`. The `.list` file
  becomes a materialized projection of fold state (facts → fold → write .list).
  Store becomes the audit trail for population changes (who added what, when).
  `import`/`merge` go away. `ls` becomes `status` scoped to pop facts. `export`
  is just the materialization step. Compiler reads `.list` as before — no
  compiler changes needed. Materializes on emit (simplest) or on compile (purest).
  Research confirmed: only one real `.list` in repo (reader/feeds.list), apps
  already manage populations directly, top-level verbs are disproportionate.

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

86. ~~Full Painted rendering + golden tests + store targeting~~ — All 9 display
    commands through `run_cli` with zoom-aware lenses (`lenses/` directory: status,
    log, store, start, compile, validate, test, run, pop). All 5 action commands
    through `show(Block.text())`. Zero raw `print()`. 45 golden snapshot tests
    (every command × 4 zoom levels) with `--update-goldens` regeneration.
    Auto-generated `apps/loops/docs/CLI.md` from fixtures. Store targeting:
    `_resolve_named_store()` composes `resolve_vertex()` + vertex store path
    extraction. `--kind` filter on status. Consistency pass: extracted status/log
    rendering from session.py to dedicated lenses, added FULL zoom to compile/validate,
    moved test warning into lens. 191 tests (146 + 45 golden).

85. ~~Session dissolution + cells→painted + run_cli harness~~ — Dissolved `loops session`
    subcommand group. `status`/`log` promoted to top-level, work on any local store via
    `_resolve_local_store()` (cwd vertex → LOOPS_HOME fallback). Migrated all cells imports
    to painted. Display commands (status, log, store) now route through painted's `run_cli`
    with `fetch()`/`render(ctx, data)` pattern. Pre-parsing with `parse_known_args` for
    command-specific flags (--since, --kind). Fixed `print_block` default arg in painted
    (late-bind `sys.stdout` for testability). 147 loops tests, 1169 painted tests.

84. ~~Population as facts~~ — `loops add/rm` emit `pop.add`/`pop.rm` facts, `.list`
    materialized as projection. `loops ls` reads fold state.

83. ~~Session continuity + strange-loops scaffold~~ — `loops session start/end/status/log`
    backed by vertex store at `LOOPS_HOME/session/`. Query-time fold: latest per
    topic/name for decisions/threads/tasks, collect for changes. `LOOPS_OBSERVER`
    env var for multi-agent. Emit parser fix (`key.isidentifier()` gate). 20 session
    tests. `apps/strange-loops/` scaffolded with dev harness (siftd/painted pattern),
    CLAUDE.md, DESIGN.md. 148 loops tests, 2 strange-loops smoke tests.

82. ~~Structural LoopFile AST + `{{var}}` template sigil~~ — Made LoopFile AST fields
    (`every`, `timeout`, `format`) raw strings instead of typed values. Moved type
    conversion (Duration.parse, format validation) from loader to compiler. Changed
    template sigil from `${var}` to `{{var}}` to disambiguate compile-time template
    vars from shell env vars (e.g., `${FRED_API_KEY}`). Wired dead `env` field through
    Source → subprocess. `instantiate_template()` now substitutes ALL string fields
    uniformly. Migrated 7 `.loop` files, 6 `.vertex` files, personal instance files,
    and all tests. 786 tests pass (126 lang, 365 engine, 295 atoms).

81. ~~Population management CLI + Atom link fix + `--rounds` default~~ — Generic
    `loops ls/add/rm/export/import/merge` for any vertex's template populations.
    Core primitives in `libs/lang/src/lang/population.py` (resolve vertex/template,
    read/write .list files, KDL text manipulation, export/import transforms).
    CLI handlers in `apps/loops/src/loops/commands/pop.py`. Auto-detects storage
    (file-backed vs inline KDL vs both). Duplicate template stems resolved by
    preferring file-backed template. Atom feed link normalization in `feed.loop`
    (`.link.["+@href"] // .link`). `loops run` now defaults to `--rounds 1`;
    `--daemon`/`-d` for continuous. 37 lang population tests, 30 CLI tests.
    126 total lang, 122 total loops tests.

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

72. ~~DSL source templates~~ — Parameterized source templates with `{{var}}` placeholders. Vertex
    declares `template:` + `with:` parameter table + optional `loop:` spec. Template instantiated
    per-row, variables substituted in source command, kind, and boundary condition. Collapsed
    4 nearly-identical .loop files → 1 template, 4 identical loop defs → 1 spec with {{kind}}.
    Added `SourceParams`, `TemplateSource` AST types. Lexer handles {{}} in identifiers. Parser
    handles `template:`/`with:`/`loop:` blocks. Compiler has `substitute_vars()`, `compile_sources()`.
    180 lang tests. hlab produces identical output with cleaner config.

71. ~~hlab fold→lens~~ — `fold_overrides` for health computation (healthy/total in tick payload),
    `stack_lens` for zoom-level rendering. main.py is now pure orchestration — domain logic in
    fold, presentation in lens. -75 lines net in main.py.

70. ~~apps/hlab first app~~ — Created `apps/hlab/` as the first real app. Added `format: ndjson`
    to Source for JSON lines. Added `select` parse op for field extraction from JSON. Built
    proof.py, infra.loop, status.vertex. Cells-based TUI with zoom (0-3). Explored
    ancestor codebases (gruel.network, zsh config, hlab) for patterns.

See `LOG.md` for older resolved items and full session history.
