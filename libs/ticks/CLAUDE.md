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
 ├─ payload: T      # frozen snapshot (folded state, batch, or single value)
 └─ origin: str     # which vertex produced this tick
```

## Public API

| Export | Kind | Purpose |
|--------|------|---------|
| `Tick` | frozen dataclass, Generic[T] | temporal snapshot: name + ts + payload |
| `Vertex` | class | where loops meet: kind routing + fold engines + boundary auto-tick + manual tick |
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
v = Vertex("my-vertex", store=my_store)  # name + optional Store backing
v.register("metric", 0, fold_fn)         # register fold for a kind
v.register("metric", 0, fold_fn,         # with boundary triggering:
    boundary="end-of-day",                #   which kind triggers boundary
    reset=True)                           #   reset engine to initial after tick
v.receive(fact)                           # route fact to fold engine → Tick | None
v.receive(fact, grant)                    # with optional Grant for potential gating
tick = v.tick("my-loop", now)             # manual boundary → Tick (all engines)
fact = v.to_fact(tick)                    # convert Tick to Fact (vertex as observer)
v.state("metric")                         # current fold state
v.kinds                                   # registered kinds
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
proj.reset(new_state)        # reset state, bump version, cursor unchanged
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
- Vertex boundary: one boundary kind per engine, unique across all engines. `receive()` returns `Tick | None`. Fold-before-boundary: if boundary kind == fold kind, fold completes first. Auto-tick name = fold kind, payload = single engine state.
- Vertex is sync by design. The async bridge (extracting kind/payload, routing boundary Ticks to a Stream) lives at the composition point, not inside Vertex.
- Store protocol: append, since, close. Two implementations: EventStore (memory), FileStore (JSONL).
- Stream snapshots tap list during emit — safe to detach mid-iteration.
- Projection.version only bumps when `new_state is not self._state` (identity check).
- Projection.reset() bumps version unconditionally. Cursor unchanged.
- EventStore tracks logical offset for eviction-safe cursors.
- Tailer only processes complete lines (trailing `\n`). Incomplete lines wait.
- All consumers implement `async consume(event) -> None`.

## Pipeline Role

```
Fact (kind, payload, observer)
  │
  ▼
Vertex ──────────────────────────────────────────────────
  ├─ register(kind, initial, fold)              # setup
  ├─ register(kind, ..., boundary=, reset=)     # with auto-tick
  ├─ receive(fact) → Tick | None                # route + fold + boundary
  ├─ receive(fact, grant) → Tick | None         # with potential gating
  ├─ tick(name, ts) → Tick                      # manual snapshot (all engines)
  ├─ to_fact(tick) → Fact                       # convert tick to fact (vertex as observer)
  └─ optional Store (append on receive)

Two boundary modes:
  Auto:   receive(boundary_fact) → Tick        # single engine, optional reset
  Manual: tick(name, ts) → Tick                # all engines, no reset

Tick-to-Fact forwarding (at composition point):
  tick = vertex_a.receive(fact)
  if tick is not None:
      tick_fact = vertex_a.to_fact(tick)       # vertex-a becomes observer
      vertex_b.receive(tick_fact)               # forward to next vertex
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
