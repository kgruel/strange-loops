# CLAUDE.md — ticks

The respiratory system. Answers: **when did state change?**

## Build & Test

```bash
uv run --package ticks pytest libs/ticks/tests
```

## Atom

```
Tick[T]
 ├─ name: str       # which loop produced this tick
 ├─ ts: datetime    # temporal boundary timestamp
 └─ payload: T      # frozen snapshot (folded state, batch, or single value)
```

## Public API

| Export | Kind | Purpose |
|--------|------|---------|
| `Tick` | frozen dataclass, Generic[T] | temporal snapshot: name + ts + payload |
| `Vertex` | class | where loops meet: kind routing + fold engines + tick emission |
| `Store` | Protocol | append-only log interface: append, since, close |
| `EventStore[T]` | class | in-memory Store with optional JSONL persistence |
| `FileStore[T]` | class | JSONL-backed Store (wraps FileWriter + Tailer) |
| `Stream[T]` | class | async event multiplexer with fan-out |
| `Tap[T]` | dataclass | handle for consumer attachment (filter, transform) |
| `Consumer[T]` | Protocol | `async consume(event: T) -> None` |
| `Projection[S, T]` | class | incremental fold: events -> state (internal to Vertex) |
| `FileWriter[T]` | class | Consumer that appends to JSONL |
| `Tailer[T]` | class | incremental JSONL reader (inverse of FileWriter) |
| `Forward[T, U]` | class | bridges Stream[T] -> Stream[U] via transform |
| `Source[T]` | Protocol | async iterator for event producers |
| `ClosableSource[T]` | Protocol | Source with lifecycle (close) |

## Key Types

### Vertex
```python
v = Vertex(store=my_store)         # optional Store backing
v.register("metric", 0, fold_fn)  # register fold for a kind
v.receive("metric", payload)       # route fact to fold engine
tick = v.tick("my-loop", now)      # fire boundary → Tick
v.state("metric")                  # current fold state
v.kinds                            # registered kinds
```

### Store
```python
# Protocol: append, since, close
store = EventStore()               # in-memory
store = FileStore(path, ser, de)   # JSONL-backed
store.append(event)                # append event
store.since(cursor)                # events from logical index
store.close()                      # release resources
```

### Stream
```python
stream = Stream[Fact]()
tap = stream.tap(consumer, filter=fn, transform=fn)
await stream.emit(event)   # fan-out to all taps
stream.detach(tap)          # safe mid-emit
```

### Projection
```python
# Two modes: fold callable or subclass override
proj = Projection(initial={}, fold=shape.apply)
await proj.consume(event)   # fold single event, bump version
proj.advance(store)          # catch up from cursor position
proj.state                   # current folded state
proj.version                 # bumped only on identity change (is not)
```

### EventStore
```python
store = EventStore(path=Path("log.jsonl"), serialize=fn, deserialize=fn)
store.append(event)          # append + persist
store.since(cursor)          # events from logical index
store.evict_below(n)         # free memory, invalidate old cursors
```

## Invariants

- Tick is frozen. Name identifies which loop produced it. Payload type is unconstrained.
- Vertex routes facts by kind to registered fold engines. Unregistered kinds are silently ignored (but stored if a Store is attached).
- Store protocol: append, since, close. Two implementations: EventStore (memory), FileStore (JSONL).
- Stream snapshots tap list during emit — safe to detach mid-iteration.
- Projection.version only bumps when `new_state is not self._state` (identity check).
- EventStore tracks logical offset for eviction-safe cursors.
- Tailer only processes complete lines (trailing `\n`). Incomplete lines wait.
- All consumers implement `async consume(event) -> None`.

## Pipeline Role

```
Fact (kind, payload)
  │
  ▼
Vertex ──────────────────────────────────────
  ├─ register(kind, initial, fold)   # setup
  ├─ receive(kind, payload)          # route + fold
  ├─ tick(name, ts) → Tick           # boundary snapshot
  └─ optional Store (append on receive)

Stream[Fact] ──┬──→ Store (persist)
               ├──→ Projection(fold=shape.apply) ──→ state ──→ Lens
               └──→ tap (external consumers)

At temporal boundary:
  Vertex.tick() ──→ Tick[state] ──→ Stream[Tick] ──→ downstream
```

## Source Layout

```
src/ticks/
  tick.py          # Tick[T] — name + ts + payload
  vertex.py        # Vertex — kind routing + fold engines + tick emission
  stream.py        # Stream, Tap, Consumer protocol
  projection.py    # Projection[S, T]
  store.py         # Store protocol + EventStore[T]
  file_store.py    # FileStore[T]
  file_writer.py   # FileWriter[T]
  tailer.py        # Tailer[T]
  forward.py       # Forward[T, U]
  source.py        # Source, ClosableSource protocols
tests/
  test_tick.py          # Tick atom tests
  test_vertex.py        # Vertex tests
  test_store.py         # Store protocol + FileStore tests
  test_behavior.py      # Edge cases and error paths
  test_integration.py   # Full pipeline paths
```
