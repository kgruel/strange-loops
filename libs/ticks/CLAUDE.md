# CLAUDE.md — ticks

Temporal infrastructure. Answers: **when did state change?**

## Build & Test

```bash
uv run --package ticks pytest libs/ticks/tests
```

## Atom

```
Tick[T]
 ├─ ts: datetime    # temporal boundary timestamp
 └─ payload: T      # frozen snapshot (folded state, batch, or single value)
```

## Public API

| Export | Kind | Purpose |
|--------|------|---------|
| `Tick` | frozen dataclass, Generic[T] | temporal snapshot |
| `Stream[T]` | class | async event multiplexer with fan-out |
| `Tap[T]` | dataclass | handle for consumer attachment (filter, transform) |
| `Consumer[T]` | Protocol | `async consume(event: T) -> None` |
| `Projection[S, T]` | class | incremental fold: events -> state |
| `EventStore[T]` | class | append-only log with optional JSONL persistence |
| `FileWriter[T]` | class | Consumer that appends to JSONL |
| `Tailer[T]` | class | incremental JSONL reader (inverse of FileWriter) |
| `Forward[T, U]` | class | bridges Stream[T] -> Stream[U] via transform |
| `Source[T]` | Protocol | async iterator for event producers |
| `ClosableSource[T]` | Protocol | Source with lifecycle (close) |

## Key Types

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
store.add(event)             # append + persist
store.since(cursor)          # events from logical index
store.evict_below(n)         # free memory, invalidate old cursors
```

## Invariants

- Tick is frozen. Payload type is unconstrained.
- Stream snapshots tap list during emit — safe to detach mid-iteration.
- Projection.version only bumps when `new_state is not self._state` (identity check).
- EventStore tracks logical offset for eviction-safe cursors.
- Tailer only processes complete lines (trailing `\n`). Incomplete lines wait.
- All consumers implement `async consume(event) -> None`.

## Pipeline Role

```
Fact ─→ Stream[Fact] ──┬──→ EventStore (persist)
                        ├──→ Projection(fold=shape.apply) ──→ state ──→ Lens
                        └──→ tap (external consumers)

At temporal boundary:
  Projection.state ──→ Tick[state] ──→ Stream[Tick] ──→ downstream
```

## Source Layout

```
src/ticks/
  tick.py          # Tick[T]
  stream.py        # Stream, Tap, Consumer protocol
  projection.py    # Projection[S, T]
  store.py         # EventStore[T]
  file_writer.py   # FileWriter[T]
  tailer.py        # Tailer[T]
  forward.py       # Forward[T, U]
  source.py        # Source, ClosableSource protocols
tests/
  test_tick.py          # Tick atom tests
  test_behavior.py      # Edge cases and error paths
  test_integration.py   # Full pipeline paths
```
