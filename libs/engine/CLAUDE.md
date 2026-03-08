# engine — the runtime

Facts arrive, state accumulates, boundaries fire Ticks. Start at Level 0. Only escalate when you hit a trigger.

**You are here** in the abstraction chain:

```
atoms (data)  →  engine (runtime)  →  lang (grammar)  →  apps (CLI)
Fact, Spec        Tick, Vertex         .loop/.vertex      loops read/emit
```

Below: `libs/atoms/` defines what data looks like (Fact, Spec, Fold). Engine receives facts and runs them.
Above: `libs/lang/` defines the DSL grammar. `apps/loops/` is the CLI. `loops emit` creates a Fact, resolves a Vertex, calls `vertex.receive()`.

---

## Level 0 — Run a vertex program

**Trigger**: I have a `.vertex` file and want to run it.

```python
from engine import load_vertex_program

program = load_vertex_program(Path("status.vertex"))
results = program.collect(rounds=1)
# {"jellyfin": {"healthy": 3, "total": 4}, "arr": {"healthy": 2, "total": 2}}
```

`load_vertex_program` does everything: parses the `.vertex` file, compiles DSL to runtime types, wires sources. Returns a `VertexProgram` with `.collect()` (sync) and `.run()` (async iterator of Ticks).

```python
# Async — yields Ticks as boundaries fire
async for tick in program.run():
    print(f"{tick.name}: {tick.payload}")
```

A Tick is what comes out when a cycle completes — the folded state at a temporal boundary:

```python
Tick(name="jellyfin", ts=..., payload={"healthy": 3, "total": 4}, origin="status")
```

This is the same Tick that `loops run status.vertex` renders. Same primitive at every level.

**Don't reach for yet**: Vertex, Loop, Projection, Store, Peer.

---

## Level 1 — Fold and fire

**Trigger**: I need to build a vertex from code, not from a `.vertex` file.

```python
from engine import Vertex

v = Vertex("project")

# Register folds — kind routes to a fold function
# Decisions accumulate by topic (latest position wins)
v.register("decision", {}, lambda state, p: {**state, p["topic"]: p})

# Threads track by name
v.register("thread", {}, lambda state, p: {**state, p["name"]: p})
```

A Vertex routes facts by kind to fold functions. Each kind gets its own fold — state accumulates independently.

```python
from atoms import Fact

# Someone made a decision
fact = Fact.of("decision", "kyle", topic="auth", position="JWT")
v.receive(fact)

v.state("decision")  # {"auth": {"topic": "auth", "position": "JWT", ...}}
```

This is exactly what happens inside `loops emit project decision topic=auth ...` — the CLI creates a Fact, resolves the vertex, calls `receive()`.

**Boundaries** turn accumulated state into Ticks:

```python
from datetime import datetime, timezone

# Manual fire — snapshot all fold states
tick = v.tick("project", datetime.now(timezone.utc))
# Tick(name="project", payload={"decision": {...}, "thread": {...}})

# Or register a boundary kind that fires automatically
v.register("health", {"events": []},
    lambda s, p: {**s, "events": [*s["events"], p]},
    boundary="health.close")  # fires when a health.close fact arrives
```

**Loop** makes boundaries explicit:

```python
from engine import Loop

# Fire every 10 facts
loop = Loop(
    name="batch",
    initial=[],
    fold=lambda s, p: [*s, p],
    boundary_count=10,
    boundary_mode="every",
    reset=True,
)
v.register_loop(loop)
```

**Nesting**: vertices can contain children. Facts forward down, child Ticks re-enter the parent as facts.

**Don't reach for yet**: Store, StoreReader, Peer, Grant, Compiler.

---

## Level 2 — Persist

**Trigger**: I need fold state to survive restarts — durable storage.

```python
from engine import SqliteStore

store = SqliteStore(
    path=Path("data/project.db"),
    serialize=lambda f: f.to_dict(),
    deserialize=Fact.from_dict,
)

v = Vertex("project", store=store)
# Now every received fact is appended to SQLite before routing
```

The Store protocol is append-only: `append()`, `since(cursor)`, `between(start, end)`, `close()`. Three implementations:

| Store | Backing | Use case |
|-------|---------|----------|
| `EventStore` | In-memory (optional JSONL) | Tests, ephemeral |
| `SqliteStore` | SQLite (WAL mode) | Production, concurrent reads |
| `FileStore` | JSONL file | Simple persistence |

**StoreReader** — read-only inspector:

```python
from engine import StoreReader

reader = StoreReader(Path("data/project.db"))
reader.summary()        # {facts: {total, kinds}, ticks: {total, names}}
reader.recent_facts(5)  # last 5 facts
reader.recent_ticks(5)  # last 5 ticks
```

This is what `loops read project` and `loops store` use to query vertex state.

**Fidelity traversal** — drill from Tick to contributing facts:

```python
# Tick carries since/ts — the period it summarizes
tick = Tick(name="health", ts=..., since=..., payload={"healthy": 3})

# Retrieve the facts that produced this tick
facts = store.between(tick.since, tick.ts)
```

**Replay** — reconstruct vertex state from stored facts:

```python
from engine import replay

vertex = replay(store, vertex_config)  # rebuilds fold state from history
```

For bulk store operations (slice, merge, cross-DB queries), see `libs/store/`.

**Don't reach for yet**: Peer, Grant, Compiler internals.

---

## Level 3 — Gate access

**Trigger**: I need to control what an observer can see or do.

```python
from engine import Peer, Grant, delegate, grant_of

# Unrestricted peer — can see and do everything
admin = Peer("admin")

# Constrained peer — can only emit health and deploy facts
monitor = Peer("monitor", potential=frozenset({"health", "deploy"}))

# Create a child peer with narrower permissions
readonly = delegate(admin, "viewer", potential={"health"})
```

**Grant** separates policy from identity:

```python
grant = Grant(potential=frozenset({"health", "deploy"}))
v.receive(fact, grant=grant)  # gated — rejects facts not in potential
```

**None = unrestricted**. `frozenset()` = locked out. Constraints emerge through delegation, not upfront enumeration.

Operators: `grant()` (union/expand), `restrict()` (intersection/narrow), `delegate()` (child with narrowing).

**Observer-state ownership**: kinds like `focus.kyle`, `scroll.kyle` require `fact.observer == "kyle"`. The Vertex enforces this automatically.

---

## Key invariants

- Tick is frozen. Vertex is sync. Async bridge lives at composition (Runner in atoms).
- `engine` depends on `atoms` (TYPE_CHECKING only) — no runtime import coupling.
- Store is append-only. No updates, no deletes. Correction by re-emit (latest-per-key fold resolves).
- Projection is the internal fold engine. Callers register folds, not Projections.
- Vertex routes by kind. Loop owns fold-and-fire. Separation of routing from accumulation.

## Build & test

```bash
uv run --package engine pytest libs/engine/tests
uv run --package engine pytest libs/engine/tests/test_vertex.py  # single file
```

## Deep dives

For design rationale and internal mechanics beyond what this CLAUDE.md covers:

| Doc | Focus |
|-----|-------|
| `docs/VERTEX.md` | Routing, folding, branching — the intersection point |
| `docs/TEMPORAL.md` | Boundaries and nesting — how loops mark time |
| `docs/PERSISTENCE.md` | Durable state, replay, fidelity traversal |
| `docs/IDENTITY.md` | Observer and gating — who sees, who emits |
