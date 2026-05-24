# Rung 03 — Persistence & Replay

> **What you'll learn:** How to attach a store to a vertex for durable fact persistence, how to reconstruct fold state from stored history via replay, and how to inspect a store without a running vertex.
> **Prerequisites:** [Rung 02 — Vertices & Loops: the runtime](02-engine-vertices-and-loops.md)
> **Time:** ~15 min

In [Rung 02](02-engine-vertices-and-loops.md), the vertex held its fold state in memory — restart the process and state is gone. This rung adds durability: facts are appended to a store as they arrive, and the vertex can be reconstructed from that history at any time. The central invariant is: **state is always derived by replaying facts, never stored directly**.

---

## The Store protocol

All three store implementations share the same protocol:

```
append(event, *, id_override=None)    # add one fact
since(cursor)                         # return facts from logical index cursor onward
between(start, end)                   # return facts in time range [start, end]
latest_by_kind(kind)                  # most recent fact of a kind, or None
close()                               # release resources
```

`cursor=0` in `since()` returns all facts. Each store implementation manages its own cursor semantics internally.

Three implementations:

| Store | Backing | Best for |
|---|---|---|
| `EventStore` | In-memory (optional JSONL sidecar) | Tests, ephemeral runtime — not shown here; see `engine.EventStore` |
| `SqliteStore` | SQLite, WAL mode | Production, concurrent reads |
| `FileStore` | JSONL file | Simple, human-readable persistence |

---

## SqliteStore

`SqliteStore` is the production store. It uses WAL (Write-Ahead Logging) mode so readers don't block writers, enabling concurrent fold reads alongside live fact ingestion.

```python
from pathlib import Path
from atoms import Fact
from engine import SqliteStore, Vertex

store = SqliteStore(
    path=Path("data/project.db"),
    serialize=lambda f: f.to_dict(),
    deserialize=Fact.from_dict,
)

v = Vertex("project", store=store)
```

`Vertex(name, store=store)` wires the store in. From that point on, every `v.receive(fact)` appends the fact to the store *before* routing it through the fold. The store sees the fact regardless of whether any loop is registered for its kind.

### Schema

SqliteStore creates two tables:

- **`facts`** — id (ULID), kind, ts, observer, origin, payload (JSON)
- **`ticks`** — id (ULID), name, ts, since, origin, payload (JSON)

IDs are [ULIDs](https://github.com/ahawker/ulid) — 26-character Crockford base32 strings. The time-sortable property of ULIDs is load-bearing: lexicographic order approximates chronological order, which makes cross-store merge via `INSERT OR IGNORE` on the id primary key safe (deduplication is correct because equal IDs mean equal facts).

Both tables have indexes on `ts` and on the kind/name column for efficient time-range and kind-filtered queries.

### Using SqliteStore as a context manager

```python
with SqliteStore(path=Path("data/project.db"), serialize=..., deserialize=...) as store:
    v = Vertex("project", store=store)
    v.receive(Fact.of("decision", "kyle", topic="auth"))
    # store.close() called automatically on exit
```

---

## FileStore — the simpler alternative

`FileStore` stores facts as newline-delimited JSON. No schema, no SQL, human-readable. Useful when you want to inspect or process the raw stream with standard tools.

```python
from engine import FileStore

store = FileStore(
    Path("data/facts.jsonl"),
    serialize=lambda f: f.to_dict(),
    deserialize=Fact.from_dict,
)
```

FileStore loads existing records on construction and appends new ones to the open file handle. It does not support concurrent writers. For anything beyond single-process persistence, prefer `SqliteStore`.

---

## Replay — reconstructing state from history

The central operation of persistence is replay: feed stored facts back into a vertex in order, reconstructing fold state from history.

There are two paths, with different semantics.

### Path 1: Vertex.replay() — used by persistent vertices

When a `Vertex` is constructed with a store (`Vertex(name, store=store)`), the vertex has its own `replay()` method:

```python
v = Vertex("project", store=store)
v.replay()   # returns number of facts replayed
```

`Vertex.replay()` sets an internal `_replaying` flag before feeding facts through the folds. While replaying, **boundaries are suppressed** — the fold state is rebuilt without firing Ticks. This is the correct behavior: boundary Ticks were already produced and stored when the facts were first received. Re-firing them on replay would create spurious duplicate Ticks.

After replay, `Vertex.replay()` reconciles count-based boundary state and initializes the period start from the last stored tick, so the next boundary that fires will have a correct `since` timestamp.

### Path 2: the free replay() function — for tests and boundary re-evaluation

There is also a free function `from engine import replay`:

```python
from engine import replay

# Returns store.total — the absolute cursor position after replay
replay(vertex, store, from_cursor=0)
```

The free function does exactly: `for fact in store.since(from_cursor): vertex.receive(fact)`. It does **not** set the `_replaying` flag — boundaries fire as they would on live receipt. Use this when you want boundaries to re-evaluate against rebuilt fold state, or in test scenarios where you're not using a store-attached vertex.

**The production path** is `Vertex(name, store=store)` followed by `v.replay()`. Boundary Ticks were already produced and stored when facts were first received — re-firing them on replay would create spurious duplicates. `Vertex.replay()` rebuilds state without re-firing boundaries, then reconciles period tracking so the next live boundary fires with the correct `since` timestamp. This is how the `loops` CLI reconstructs vertex state on every invocation.

### Why replay rather than storing state

The design choice is principled: if derived state (the fold result) were stored separately, it could become inconsistent with the facts that produced it. By storing only facts and re-deriving state, the system is self-consistent — replay is the ground truth. The cost is proportional to history length, which the CLI amortizes via fast-path raw replay that avoids constructing full `Fact` objects.

---

## StoreReader — read-only inspection

`StoreReader` opens a SqliteStore with `PRAGMA query_only=ON`. It does not create the file and cannot write to it. Use it to inspect a vertex's store without running the vertex:

```python
from pathlib import Path
from engine import StoreReader

reader = StoreReader(Path("data/project.db"))

reader.summary()
# {
#   "facts": {"total": 142, "kinds": {"decision": {...}, "thread": {...}}},
#   "ticks": {"total": 8, "names": {"project": {...}}}
# }

reader.fact_kind_stats()
# {"decision": {"count": 12, "earliest": datetime(...), "latest": datetime(...)}, ...}

reader.recent_ticks("project", 5)   # last 5 ticks named "project", newest first
reader.recent_facts("decision", 10) # last 10 decision facts, newest first

reader.close()
```

`fact_kind_stats()` and `tick_name_stats()` each return a dict with per-kind/per-name counts and time ranges. These power the `loops store` command's dashboard view.

---

## Fidelity traversal — drilling from Tick to facts

Each `Tick` carries a `since` field: the timestamp of the first fact received after the previous boundary (or vertex construction). With `store.between(tick.since, tick.ts)`, you retrieve exactly the facts that were folded to produce the Tick's payload:

```python
# tick is a Tick you received or loaded from the ticks table
facts = store.between(tick.since, tick.ts)
# facts is the set of observations that produced tick.payload
```

This is the fidelity traversal pattern: navigate from a compressed summary (Tick) down to the raw evidence (Facts). See [deep dive: TEMPORAL](../TEMPORAL.md) for the full mechanics, including how `since` is set during replay.

---

## Putting it together — a durable vertex session

```python
from pathlib import Path
from atoms import Fact
from engine import SqliteStore, Vertex

path = Path("data/metrics.db")

store = SqliteStore(
    path=path,
    serialize=lambda f: f.to_dict(),
    deserialize=Fact.from_dict,
)

v = Vertex("metrics", store=store)

# Register folds
v.register(
    "metric",
    {"total": 0, "count": 0},
    lambda s, p: {**s, "total": s["total"] + p["value"], "count": s["count"] + 1},
    boundary="flush",
    reset=True,
)

# Rebuild state from stored history (suppresses boundaries during replay)
v.replay()

# Now receive new facts — these are appended and folded live
v.receive(Fact.of("metric", "sensor", value=42))
v.receive(Fact.of("metric", "sensor", value=18))

tick = v.receive(Fact.of("flush", "sensor"))
# tick.payload == {"total": <prior + 60>, "count": <prior + 2>}

store.close()
```

On the next process start, `v.replay()` re-reads all facts from the store and the fold picks up exactly where it left off.

---

## Choosing a store

| Scenario | Store |
|---|---|
| Tests, ephemeral data | `EventStore` (in-memory) |
| Single-process, human-readable output | `FileStore` (JSONL) |
| Multi-session persistence, concurrent reads, production use | `SqliteStore` |

For bulk maintenance operations on stores — slicing, merging, cross-store transport — see [Rung 09 — Store Maintenance & Transport](09-store-maintenance-and-transport.md) and `libs/store/`.

---

**Next:** [Rung 04 — Declaring Vertices in KDL](04-declaring-vertices-in-kdl.md)
**See also:** [deep dive: PERSISTENCE](../PERSISTENCE.md) · [deep dive: TEMPORAL](../TEMPORAL.md) · [API reference](../api-reference.md) · [guide index](README.md)
