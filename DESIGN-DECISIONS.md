# Design Decisions — Architectural North Star

The accumulated design decisions for the loops system, organized by architectural weight. This document is the functional reference for implementation priority — when in doubt about what to build next, trace back to the tier that governs it.

Produced 2026-03-07 from two design investigation sessions (4-agent + 5-agent teams). Refined via review passes — several decisions updated in place.

## Tier 1: Foundational

Everything else depends on these. If any of these change, most of the system reshapes.

### vertex-as-interface

The vertex is the read/emit/sync interface to the system, not a container queried around. The correct model: three operations (read, emit, sync), vertices are addresses that receive facts and produce state, lenses determine rendering.

### cli-verb-first (refined 2026-03-07)

CLI shape is verb-first: `loops <verb> <vertex>`. Three vertex operations:

- `loops read project` — explicit read (pure, no side effects)
- `loops project` — implicit read shorthand
- `loops emit project decision ...` — manual fact entry
- `loops sync project` — cadence-gated source execution

`try` is a dev tool for standalone `.loop` files: `loops try disk.loop` (preview, no persistence). Vertex names and verbs occupy different argument positions — no namespace collision.

### source-execution-model (resolved 2026-03-07)

Source execution dissolves to three concerns:

1. **Source** = command + parse → facts. Pure adapter in atoms. No scheduling fields. `stream()` becomes `collect()` — runs once. Source is an adapter, not a runtime.
2. **Cadence** = store predicate in engine. `should_run(store, now) → bool`. Same shape for time-based (`every`) and event-based (`trigger`). Evaluated at invocation time against `{kind}.complete` facts in the store.
3. **Executor** = evaluate cadence predicates, run qualifying sources per vertex execution plan (concurrent default, sequential mode), route facts through `vertex.receive()`.

`every` and `trigger` dissolve from Source runtime into Cadence predicates compiled from AST. The store is the clock — completion facts record when sources last ran. Topology is the scheduling surface — restructure vertices to change what runs when.

**What dissolves:** `Source.every`, `Source.trigger`, `Source.stream()` while loop, `Runner` class, `SequentialSource` class, `start` command, daemon mode.

**What's born:** `Cadence` (engine), `Source.collect()` (atoms), cadence-gated executor function (engine).

Prior art: `docs/CADENCE.md` (2026-01-31) proposed Source/Cadence split conceptually. The one-shot constraint made implementation simpler — scheduling can't live in Source because nothing stays alive to schedule.

### no-persistent-runtime

The system has no long-running processes. The vertex is reactive — facts arrive, it folds, boundaries fire, ticks cascade. Scheduling is an external concern (cron/systemd/launchd/hooks), not a vertex runtime concern. Every CLI interaction is: load vertex tree, replay stored facts, do operation, exit. The one-shot model IS the runtime. Performance at scale requires fold-materialization.

### three-surviving-concerns

After dissolution, three concerns remain in the app layer:

1. **Configuration** — vertex declarations, loop definitions, boundary conditions, source definitions, nesting topology. This is where behavior is authored.
2. **Lenses** — pure rendering functions that determine how reads present to different consumers (prompt lens for agents, default lens for humans, JSON for hooks).
3. **Runtime/drivers** — source execution via `sync` (cadence-gated, one-shot), and the CLI dispatch itself (verb routing, vertex resolution, read, emit).

atoms, engine, lang, painted, store all survive unchanged.

### read-is-pure (2026-03-07)

Read operations (`loops read`, `loops fold`, `loops stream`) are pure — no side effects, no source execution, fast and deterministic. `sync` is the explicit refresh operation. On-read-if-stale rejected.

This preserves composability (reads in scripts are predictable) and follows explicit-over-implicit. The hook/cron pattern provides the external heartbeat; cadence predicates on the vertex self-regulate which sources actually run.

### sync-locus-of-control (2026-03-07)

`sync` is the production verb for source execution. Locus-of-control distinction: `sync` means the **vertex** decides what runs (via cadence predicates), not the caller. The caller just says "check yourself."

- `loops sync project` — evaluate cadence, run stale sources
- `loops sync project --force` — run all sources unconditionally (old `run` behavior)
- `loops sync --all` — evaluate all vertices, cadence self-regulates

Default is cadence-gated because that is the common deployment pattern: one cron heartbeat, vertex self-regulates. `run` survives only as dev tool: `loops try disk.loop`. `start` dissolves entirely.

### cadence-as-store-predicate (2026-03-07)

Cadence predicates evaluate at invocation time against the store. Same shape for time-based and event-based — one mechanism, two instances:

- `Cadence.elapsed(kind, interval)` — true if interval seconds passed since last `{kind}.complete` fact
- `Cadence.triggered(trigger_kind, source_kind)` — true if `trigger_kind` fact exists since last `source_kind.complete`
- `Cadence.always()` — run-once sources (default when no `every`/`trigger`)

`every` stays in lang AST as scheduling hint, compiles to Cadence in engine, never reaches Source in atoms. The store is the clock. Topology is optimization — restructure vertices to change cadence granularity.

## Tier 2: Structural

These define WHERE things go. The layer boundaries.

### app-boundary (2026-03-07)

The loops CLI speaks vertex — three generic operations: read, emit, sync. Apps speak domain — they add domain-specific verbs (merge, search, ingest) composed from vertex primitives. Lenses are configuration that bridges them: vertex declarations carry rendering instructions, the loops CLI uses them without domain knowledge. Sensible defaults mean the generic lens path works without configuration.

**The graduation test:** when your domain needs verbs that aren't read, emit, or sync, you're building an app.

Apps never own the read path — you never need an app installed to SEE vertex state, only to ACT on it with domain verbs.

### lens-escalation-path (2026-03-07)

Three tiers of rendering:

1. **Generic default** — built-in fold_view, metadata-driven, handles any vertex adequately.
2. **Custom lens** — `.py` file, travels with vertex config, handles domain well. No painted requirement — the lens contract is abstract (fold state in, rendered output out). painted is one rendering backend; could also be HTML, TUI, or structured data.
3. **App** — domain verbs beyond read/emit/sync, composed operations with validation.

Each tier is a real graduation. Custom lenses don't reach into the CLI. Apps don't reach into lenses. Configuration travels with the vertex.

The prompt lens is identity configuration, not generic infrastructure — it's an aspect of being an agent, declared as `lens "prompt"` in `identity.vertex`.

### generic-defaults-simplicity (2026-03-07)

Generic defaults should be simple, not smart. The built-in fold lens renders sections with items, driven by metadata (`key_field`, `fold_type`). Counts, labels, bodies, progressive zoom. That's it.

If a domain needs more, write a custom lens. Stop trying to make the generic handle every domain well — make it handle every domain adequately. Domain-specific rendering belongs in custom lenses (configuration), not in the built-in layer.

### vertex-topology (refined)

Vertices are addresses — they exist, have stores, receive facts, produce state. The tree (root discovers children, ticks cascade up) is ONE routing pattern, not the only topology. Combine (query-time assembly) and direct addressing coexist. Organization is configuration, not architecture.

Cross-vertex cascading works in engine (`vertex.receive` forwards to children, child ticks re-enter parent). The tree gives namespace (paths like `dev/project`), cascade, and discovery. But it's routing infrastructure, not fundamental topology.

### unfiltered-stream-is-dev-tool (refined)

The unfiltered stream is a dev/diagnostic tool. But filtered fact queries (`--facts --kind decision --since 1d`) are first-class operations. Progressive unpacking from fold state to individual facts is core paradigm.

Three granularities: fold state (compressed default), filtered facts/ticks (queryable with composable filters), raw unfiltered stream (dev tool). `--facts`, `--ticks`, `--kind`, `--since` compose as a basic filter query language.

## Tier 3: Implementation

These tell you HOW to build things that Tier 1-2 require. Listed in dependency order.

### fold-state-typed-contract

FoldState/FoldSection/FoldItem as frozen dataclasses in `libs/atoms/`. The lens contract becomes `(atoms.FoldState, Zoom, width) -> Block`. FoldItem separates payload (`dict[str,Any]`) from metadata (ts, observer, origin). This is the foundation that all lenses build on.

**Dependency:** Enables generic-defaults-simplicity, lens-escalation-path, and app-boundary in practice.

### cadence-implementation

`Cadence` as frozen dataclass in `libs/engine/cadence.py`. Three constructors: `elapsed()`, `triggered()`, `always()`. One method: `should_run(store, now) → bool`. Compiler produces `(Source, Cadence)` pairs from AST. VertexProgram carries entries with cadence. Executor function replaces Runner class.

**Dependency:** Enables source-execution-model in practice. Requires `{kind}.complete` facts (already emitted by Source).

### source-simplification

Strip `every` and `trigger` from `Source` runtime type (atoms). Rename `stream()` to `collect()` — runs once, yields facts. Remove the `while True` + `asyncio.sleep` loop. Remove `Runner` class. Remove `SequentialSource` class — sequential logic moves to executor function. `every`/`trigger` stay in lang AST, consumed only by compiler to produce Cadence.

**Dependency:** Requires cadence-implementation to be in place first.

### vertex-lens-declarations

LensDecl in vertex AST with fold/stream fields. 4-tier resolution: `--lens` flag > vertex `lens{}` declaration > app override > built-in default. Custom lens contract: `render(data, zoom, width) -> Block`. File search: vertex-local > project-local > user-global > built-in.

### resolve-observer-canonical

`resolve_observer()` is the single source of truth for observer identity. Priority: flag > env > project `.vertex` > global `.vertex`. All ad-hoc resolution paths dissolved.

### plain-format-contract

`--plain` means same content, same layout, no ANSI styling. LLM-oriented rendering is a lens concern (`--lens prompt`), not a format concern.

### fold-materialization

Cache fold computation until new facts arrive. Current fold is O(all facts) per read. Critical now that vertex tree discovery happens on every invocation. Doesn't change the FoldState contract — same shape, computed more efficiently.

## Tier 4: Domain (painted roadmap)

Valid but separate from loops architecture. Guide painted development.

- **composition-primitives** — record_timeline, record_map, record_line
- **canvas-primitive / dag-lens-first** — 2D positioning, DAG visualization
- **rendering-semantics** — color encodes one dimension, fixed-width metadata
- **payload-lens / lens-modifiers** — gutter, attention modifiers

## Key Findings from Investigations (2026-03-07)

### Session 1: Architecture trace (4-agent team)

#### The engine IS the orchestration runtime

The engine has everything needed for task orchestration: boundary firing (3 modes), cascade (tick-to-fact conversion with loopback prevention), progressive unpacking (`Store.between(tick.since, tick.ts)`), replay with period initialization, Grant/Peer gating. All built, tested, working at three nested levels.

#### strange-loops doesn't use it

Every fact emission in strange-loops bypasses `Vertex.receive()` — goes straight to `SqliteStore`. Boundaries never fire; ticks are manual checkpoints hand-emitted by the harness. No vertex nesting, no cascade. The read-time pattern works (`vertex_read` for fold-at-query), but the runtime pattern is completely absent.

#### The gap is wiring, not invention

Three things need to happen for full paradigm compliance:

1. **Wire strange-loops through `vertex.receive()`** — replace `emit_fact(store)` with routing through a live Vertex instance.
2. **Add vertex nesting** — task vertex as child of project vertex. Task ticks cascade to parent.
3. **Agent poll loop for comms** — the no-persistent-runtime decision means no push. One-shot polling is the pattern.

#### Cross-vertex routing — current vs target

**Current implementation:** query-time assembly via SQLite ATTACH (combine/discover). Facts don't flow between vertices at runtime.

**Target architecture:** runtime routing through `vertex.receive()` → cascade. Facts emitted into child vertices produce ticks that become facts in the parent. `Loop.fire()` and `Vertex.receive()` IS the routing mechanism. The combine pattern is a workaround for the vertex tree not being fully wired yet.

### Session 2: Source execution model (5-agent team)

#### `every` is dead code in practice

Three domains declare polling intervals (reading 30m, economy 6h/24h, messaging 5m). Nothing runs them persistently. No cron, no launchd (except a zombie), no daemons. The only active scheduling is Claude Code hooks and manual CLI. hlab declares `every "30s"` but always calls `program.collect(rounds=1)`.

#### Source conflates what-to-run with when-to-run

The Source type in atoms carries both the command/parse logic AND scheduling policy (`every`, `trigger`). Two scheduling mechanisms consumed by two different components (`every` by Source.stream(), `trigger` by Runner). This conflation dissolves: Source becomes pure (command + parse → facts), scheduling becomes Cadence (store predicate in engine).

#### Cadence as topology optimization

Cadence predicates turn vertex topology into the scheduling surface. Restructure vertices to change what runs when — finer-grained vertices mean finer-grained cadence, coarser means coarser. No external scheduling config to update. The store is the only clock.

#### Prior art: CADENCE.md

`docs/CADENCE.md` (2026-01-31) proposed the Source/Cadence split conceptually ("timer as fact," "the clock is just another fact source"). Never implemented. The one-shot constraint makes the implementation simpler — "timer as fact" dissolves from a persistent loop into a store predicate. Completion facts ARE the timer. No materialized time-facts needed.

## Threads Dissolved by These Decisions

| Thread | Dissolved by | Rationale |
|--------|-------------|-----------|
| source-execution-model | source-execution-model + cadence-as-store-predicate | Resolved: Source pure, Cadence as predicate, sync as verb |
| gist-lens-generics | generic-defaults-simplicity | Kind-specific extractors dissolve into custom lenses |
| help-unification | generic-defaults-simplicity | Nothing to unify when generic layer is simple |
| app-block-wrapper | app-boundary | Lenses are vertex-level config, not app-level |
| consumer-logic | lens-escalation-path | Ranking/sorting is a custom lens concern |
| developer-app-split | app-boundary | The loops CLI IS the developer tool |
| combine-lens-propagation | lens-escalation-path | Each vertex declares its own lens, no inheritance |

## Implementation Dependency Chain

```
fold-state-types (atoms)
    |
    v
generic fold lens simplification (loops CLI)
    |
    v
cadence-implementation (engine) ──────────────┐
    |                                         |
    v                                         v
source-simplification (atoms)     lens-escalation-path (config)
    |                                         |
    v                                         v
cli-verb-first (loops CLI)        app-boundary realized (strange-loops)
    |                                         |
    v                                         v
sync command (loops CLI)          orchestration lifecycle
```

fold-state-types remains the concrete starting point. cadence-implementation can proceed in parallel with the lens path.
