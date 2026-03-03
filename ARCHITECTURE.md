# ARCHITECTURE

The implementation of [STRANGE-LOOPS](STRANGE-LOOPS.md) in Python. The paradigm
is three shapes, four properties, one pattern. This document is how and why
those are instantiated as software.

## Why Python

Not because Python is fast, or because the ecosystem demands it. Because the
developer can see the shape of the code and fold out expectations without
reading it. Python is readable at a glance — the structure of a frozen
dataclass, the signature of a pure function, the flow of a pipeline. When
you're building a system for focusing attention, the implementation language
needs to not fight the focus. Python gets out of the way.

This also means the system is trivially portable. Everything is immutable,
append-only, unidirectional. There's no mutable state to coordinate, no
concurrency model baked in, no framework coupling. The Python is one
instantiation. The paradigm is what matters.

## Libraries

Five libraries. Each owns one concern. The dependency graph flows left to right:

```
atoms ──→ engine ──→ lang
             │
             └──→ store

painted (independent — no cross-lib imports)
```

**atoms** — The three shapes as code. Fact, Spec, Tick as frozen dataclasses.
Source as ingress configuration. Parse vocabulary (10 ops: Split, Pick, Rename,
Coerce...) for shaping raw input. Fold vocabulary (10 ops: Latest, Count, Sum,
Collect, Upsert...) for accumulating state. `Spec.apply(state, payload) → state`
is pure — deep copies, folds, returns. Zero runtime dependencies.

**engine** — The pattern as code. Vertex routes facts by kind to fold engines.
Loop executes Spec.apply, tracks state, fires at boundaries. SqliteStore provides
durable append-only persistence. StoreReader provides read-only inspection.
Peer/Grant provides identity and gating policy (implemented, not yet used in
production). The compiler translates lang AST into runtime vertices. Engine
depends on atoms at TYPE_CHECKING time only — no runtime import coupling.

**lang** — Configuration as code. KDL parser for `.loop` files (source
definitions) and `.vertex` files (vertex configurations). Pure grammar — no
runtime types, no execution. Produces frozen AST dataclasses. Validates shape
inference through parse pipelines. The only external dependency is `ckdl`.

**store** — Maintenance as code. Slice, merge, search, compact, push/pull for
vertex store databases. Operates on the same SQLite databases that engine writes.
ULID primary keys make cross-database dedup trivial — same fact in two stores
has the same ID, merge is `INSERT OR IGNORE`. Transport protocol for moving
stores between locations.

**painted** — Lenses as code. Terminal rendering primitives: Cell, Span, Line,
Block, Style. Composition: join, pad, border, truncate. The `run_cli` harness
wires zoom levels (MINIMAL, SUMMARY, DETAILED, FULL) and output modes (text,
JSON, plain) into a standard CLI pattern. Lenses are functions:
`(data, zoom, width) → Block`. Independent of all other libs — no cross-imports.

## The Concrete Data Flow

The paradigm says: observation → vertex → accumulate → boundary → tick. Here's
what that looks like in this implementation:

```
Shell command (df -h, curl, docker ps, ...)
      │
      ▼
   Source (atoms)
      command → stdout → format (lines/json/ndjson/blob)
      → parse pipeline [Split, Pick, Rename, Coerce]
      → Fact(kind="disk", ts=now, payload={fs: "/dev/sda1", use: 50}, observer="monitor")
      │
      ▼
   Vertex (engine)
      │
      ├── SqliteStore.append(fact)        # durable if configured
      │
      ├── route by fact.kind
      │     ├── "disk"   → disk Loop     (Spec.apply, fold state)
      │     ├── "health" → health Loop   (Spec.apply, fold state)
      │     └── "deploy" → deploy Loop   (Spec.apply, fold state)
      │
      └── boundary check
            │
            ├── data-driven: fact.kind == boundary.kind → fire
            ├── count-driven: N facts accumulated → fire
            └── manual: vertex.tick("name", now) → fire all
                  │
                  ▼
               Tick(name="disk", ts=now, payload={...}, origin="status")
                  │
                  ├── SqliteStore.append(tick)
                  ├── downstream vertex (tick.payload becomes fact.payload,
                  │                      tick.origin becomes fact.observer)
                  └── observer sees via lens → acts via fact emission
```

## Configuration: KDL

`.loop` files define sources. `.vertex` files define vertices. KDL is the surface
syntax — structured enough to express routing, folds, and parse pipelines;
readable enough that the configuration is self-documenting.

```kdl
// status.vertex
vertex "status" {
    store "./data/status.db"

    loop "health" {
        fold "events" collect max=10
        boundary when="health.close" reset=true
    }

    source "disk.loop"
    source "health.loop"
}
```

```kdl
// disk.loop
source {
    command "df -h"
    kind "disk"
    observer "monitor"
    format "lines"
    every 60

    parse {
        skip startswith="Filesystem"
        split
        pick 0 4
        rename 0="filesystem" 1="use_pct"
        coerce use_pct="int"
    }
}
```

Lang parses these into frozen AST dataclasses. Engine's compiler translates AST
into runtime vertices. The separation means lang is portable — it could target
a different runtime without changing the grammar.

## Persistence: SQLite

Append-only SQLite with WAL mode. The schema:

```sql
facts(id TEXT PK DEFAULT (ulid()), kind, ts, observer, origin, payload JSON)
ticks(id TEXT PK DEFAULT (ulid()), name, ts, since, origin, payload JSON)
```

**Why SQLite:** Embeddable (no server), concurrent reads via WAL, FTS5 for
full-text search, battle-tested durability. The store is just a file — copy it,
merge it, slice it, push it to another machine.

**Why ULID:** Globally unique, time-sortable, deterministic for the same fact.
Makes cross-database merge trivial — `INSERT OR IGNORE` on the primary key.

**Why append-only:** The paradigm requires it. Facts don't change. State is
derived by replaying facts through folds. No updates, no deletes. Correction
by re-emission (latest-per-key fold resolves conflicts).

**State is never stored.** Fold state is always derived. Replay the facts through
the spec, get the state. This means spec changes are safe — replay with the
new shape, get updated state. No migrations.

Three store implementations serve different needs:

| Store | Backing | Use case |
|-------|---------|----------|
| `SqliteStore` | SQLite (WAL) | Production — concurrent reads, durable |
| `EventStore` | In-memory + optional JSONL | Tests, ephemeral workloads |
| `FileStore` | JSONL | Append-heavy, memory-constrained |

## Rendering: painted

The terminal is the shared focal plane — the surface where human and AI
observers can both focus attention on the same data at the fidelity level
that matters to each.

painted provides the primitives:

**Composition stack:** Cell → Span → Line → Block. Each level composes from
the level below. Block is the primary unit lenses produce.

**Lens pattern:** `(data, zoom, width) → Block`. Same function signature
everywhere. The data is vertex state. The zoom is fidelity level. The width
is the terminal. The output is styled text.

**Fidelity levels:** MINIMAL (single line — counts, summary stat), SUMMARY
(enough to orient, not drown), DETAILED (metadata, well-known keys), FULL
(everything, expanded). Progressive disclosure of attention.

**run_cli harness:** Wires a lens to a CLI command. Handles zoom flag, output
mode (text/JSON/plain), terminal width detection, error display. Every display
command in every app uses this — fetch data, apply lens, render.

**Why terminal-native:** Not aesthetic preference. The terminal is where the
collaboration happens. Both observers — human reading styled output, AI parsing
structured output — use the same tool on the same data. JSON output mode means
the same lens serves both. The terminal is the lowest-common-denominator focal
plane that works for everyone in the loop.

## Identity: Peer/Grant

Implemented in engine. Not yet used by any application.

**Observer** is a string on every Fact. Naming hierarchy encodes participation
level by convention: `kyle` (direct), `kyle/claude-session-123` (delegated),
`kyle/deploy-agent` (automated). The identity is part of the observation.

**Grant** attaches policy at the vertex level:
- **horizon:** what kinds the observer can see (field of view)
- **potential:** what kinds the observer can emit (ability to direct attention)
- **None** = unrestricted. **frozenset()** = locked out.

**Delegation** narrows — you can give a collaborator a focused view and a
constrained voice. `delegate(peer, "child", potential={"health"})` creates
a child peer that can only emit health observations.

This mechanism exists and is tested. Whether it survives real use or dissolves
further is an open question tracked in the project store.

## Conventions

- **Immutable by default.** Frozen dataclasses, `MappingProxyType` for payloads,
  pure functions. The paradigm requires immutability; Python makes it visible
  with `frozen=True`.
- **engine depends on atoms (TYPE_CHECKING only).** No runtime import coupling
  between libs. Each lib is independently testable.
- **Errors are facts.** Source failures emit `Fact(kind="source.error", ...)`
  instead of raising. The loop continues.
- **./dev check must pass.** Each lib and app with a dev script gates on:
  type checking + formatting → unit tests → golden snapshot tests.

## Build & Test

```bash
uv sync                                                # install all workspace packages
uv run --package <name> pytest libs/<name>/tests       # test one lib
uv run --package <name> pytest apps/<name>/tests       # test one app
```

## References

| Doc | Scope |
|-----|-------|
| [STRANGE-LOOPS.md](STRANGE-LOOPS.md) | The paradigm — shapes, properties, pattern |
| [VERTEX.md](docs/VERTEX.md) | Routing, folding, branching in the engine |
| [TEMPORAL.md](docs/TEMPORAL.md) | Boundaries, nesting, semantic time |
| [PERSISTENCE.md](docs/PERSISTENCE.md) | Durable state, replay, store protocol |
| [IDENTITY.md](docs/IDENTITY.md) | Observer attribution, gating policy |
| Lib CLAUDE.md files | Progressive API guides for each library |
