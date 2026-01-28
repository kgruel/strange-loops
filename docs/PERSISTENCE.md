# PERSISTENCE.md — How Loops Remember

Persistence is a property, not a type. Any fold can be durable.

See LOOPS.md for the foundational loop model. This document covers what
happens when loops survive across sessions — when folded state outlasts
the process that produced it.

---

## Ephemeral vs Durable

A fold engine has one degree of freedom: whether its state survives.

```
Ephemeral fold:  state lives in memory, dies with the process
Durable fold:    state persists to a Store, reconstructed on restart
```

This is configuration, not architecture. The same Vertex, same Shape,
same fold function. The only difference is whether a Store is attached.

```python
# Ephemeral — state lives and dies with the process
v = Vertex()
v.register("metric", 0, lambda s, p: s + p["value"])

# Durable — state survives via Store
v = Vertex(store=EventStore(path=Path("metrics.jsonl")))
v.register("metric", 0, lambda s, p: s + p["value"])
```

The fold doesn't know. It receives payloads, returns new state. The
Vertex decides whether to persist.

---

## What Gets Persisted

Three things can survive:

| What | Where | Purpose |
|------|-------|---------|
| **Facts** | Store (EventStore, FileStore) | The truth. Append-only log of observations. |
| **Fold state** | Reconstructed from facts | Derived. Never stored directly. |
| **Tick outputs** | Downstream vertex or file | Frozen snapshots at boundaries. |

Facts are the source of truth. Fold state is always derived — replay
the facts, get the state. Ticks are outputs, not inputs; they can be
stored for audit or downstream consumption, but the upstream vertex
doesn't need them.

The invariant: **fold state is never serialized directly.** If you can
replay the facts through the shape, you can reconstruct the state. This
means:

- Shape changes are safe — replay with the new shape, get updated state
- Corruption is detectable — replay should produce deterministic results
- Storage is simple — just append facts, never update

---

## Replay

Replay is the inverse of folding: given stored facts, reconstruct state.

```
Store.since(0) → [Fact, Fact, Fact, ...] → fold → state
```

The Vertex doesn't have a replay method — replay is composition-layer
wiring. The pattern:

```python
store = EventStore(path=Path("metrics.jsonl"))
v = Vertex(store=store)
v.register("metric", 0, fold_fn)

# Replay: catch up from stored facts
for fact in store.since(0):
    v.receive(fact.kind, fact.payload)

# Now live — new facts fold into the replayed state
```

Replay is just receiving facts in order. The fold doesn't distinguish
between "replaying from storage" and "receiving live." Both are facts
arriving at a vertex.

### Cursor semantics

Store tracks a logical offset. `since(cursor)` returns facts from that
position forward. This enables:

- **Incremental replay**: Only process new facts since last checkpoint
- **Multiple consumers**: Each tracks its own cursor position
- **Eviction-safe**: Logical offsets survive memory cleanup

---

## The Memory Pattern

A boundary-less fold is memory.

```python
# No boundary → folds forever, never produces Tick
v.register("log", [], lambda s, p: [*s, p], boundary=None)
```

Without a boundary, the fold accumulates indefinitely. No cycle completes.
No Tick is produced. State just grows.

This is the memory pattern: a durable fold with no boundary. Facts arrive,
state accumulates, nothing resets. The state *is* the memory.

Use cases:
- Audit logs: every observation, forever
- Configuration: latest value of each key, never reset
- Caches: bounded collection, no temporal boundary

The pattern composes with persistence:

```python
store = EventStore(path=Path("audit.jsonl"))
v = Vertex(store=store)
v.register("audit", [], lambda s, p: [*s, p])  # no boundary

# On restart: replay from store, continue accumulating
```

Memory without persistence is ephemeral cache. Memory with persistence
is durable state. Same fold, different survival semantics.

---

## The Persist Vertex Pattern

Some systems want acknowledgment that a fact was stored. The pattern:
a vertex that persists and emits confirmation.

```
Fact("metric", payload)
  │
  ▼
Persist Vertex
  ├─ store.append(fact)
  └─ emit Fact("stored", {kind: "metric", ts: ...})
```

The downstream "stored" fact confirms persistence. Upstream producers
can wait for acknowledgment before proceeding.

This is composition, not a primitive. The vertex is just:

```python
async def persist_and_confirm(fact, store, downstream):
    store.append(fact)
    await downstream.emit(Fact.of("stored", {
        "kind": fact.kind,
        "ts": fact.ts
    }))
```

No special infrastructure. Facts go in, confirmation facts come out.

---

## Store Implementations

The ticks library provides two Store implementations:

### EventStore

In-memory with optional JSONL persistence.

```python
store = EventStore()                    # memory only
store = EventStore(path=Path("x.jsonl")) # memory + file

store.append(event)     # append (+ persist if path)
store.since(cursor)     # events from offset
store.evict_below(n)    # free memory, keep file
```

EventStore is the default for development. Memory-fast, file-durable,
eviction-friendly.

### FileStore

JSONL-native. Wraps FileWriter (append) and Tailer (read).

```python
store = FileStore(path, serialize_fn, deserialize_fn)
store.append(event)     # append to file
store.since(cursor)     # read from file position
```

FileStore is for append-heavy workloads where memory is constrained.
Tailer tracks byte offsets, not logical positions — reads are cheap.

### Store protocol

Both implement the same protocol:

```python
class Store(Protocol[T]):
    def append(self, event: T) -> None: ...
    def since(self, cursor: int) -> Iterable[T]: ...
    def close(self) -> None: ...
```

Vertex accepts any Store. Swap implementations without changing fold logic.

---

## No New Primitives

Persistence needs no new atoms:

- **Fact** is the unit of persistence — immutable, timestamped, storable
- **Shape** describes how facts fold — replay uses the same apply()
- **Vertex** optionally attaches a Store — configuration, not type
- **Tick** is the output — can be stored for audit, but isn't required

The primitives compose. Durability is a wiring decision. Memory is a
boundary-less fold. Replay is just receiving facts in order.

---

## Patterns

### Durable fold with boundary

State persists and produces Ticks at boundaries.

```python
v = Vertex(store=EventStore(path=Path("metrics.jsonl")))
v.register("metric", 0, fold_fn, boundary="end-of-day", reset=True)
```

Facts persist. State resets at boundary. Tick captures the cycle.
On restart: replay facts since last boundary, resume folding.

### Durable memory (no boundary)

State persists and accumulates forever.

```python
v = Vertex(store=EventStore(path=Path("audit.jsonl")))
v.register("audit", [], lambda s, p: [*s, p])  # no boundary
```

Every fact is stored. State is the full history. On restart: replay
all facts, continue accumulating.

### Ephemeral cache with boundary

State is temporary, but produces Ticks for downstream persistence.

```python
v = Vertex()  # no store
v.register("batch", [], collect_fn, boundary="flush", reset=True)
# Ticks go to a downstream vertex with a store
```

State lives only in memory. Ticks capture completed batches. Downstream
vertex persists the Ticks.

### Replay with schema evolution

Shape changes are safe because state is derived.

```python
# Old shape
old_shape = Shape("metric", folds=[Fold("sum", "total")])

# New shape adds a count
new_shape = Shape("metric", folds=[
    Fold("sum", "total"),
    Fold("count", "n")
])

# Replay with new shape — state includes both fields
for fact in store.since(0):
    v.receive(fact.kind, fact.payload)  # uses new shape
```

No migration scripts. Replay through the new shape. Missing fields
get initial values.

---

## The Insight

Persistence isn't a separate concern bolted onto the loop. It's a
property of how the vertex is configured.

The same fact, same fold, same shape — whether it survives is a one-line
change. State is always derived from facts. Replay is just folding.

Loops remember by replaying what they observed.
