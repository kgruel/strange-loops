# ticks

The respiratory system. Personal-scale event infrastructure.

## Atom

```
Tick[T]
 ├─ name: str       # which loop produced this tick
 ├─ ts: datetime    # when the temporal boundary fell
 └─ payload: T      # the frozen snapshot
```

Append-only logs, offset-tracking consumers, materialized views — without brokers. The file IS the broker.

```
Fact (kind, payload) → Vertex → fold engines → Tick
                         │
                         └─ optional Store (persist)

Stream[Fact] → FileWriter → JSONL file
                 ↓
             Projection (fold) → derived state
                 ↓
              Tailer → replay from any offset
```

## Usage

```python
from datetime import datetime, timezone
from ticks import Tick, Vertex, EventStore, FileStore, Stream, Projection

# Tick — frozen temporal snapshot with loop identity
tick: Tick[dict] = Tick(
    name="my-loop",
    ts=datetime.now(timezone.utc),
    payload={"count": 5, "total": 100},
)

# Vertex — where loops meet
v = Vertex(store=EventStore())
v.register("metric", 0, lambda state, p: state + p["value"])
v.register("event", 0, lambda state, p: state + 1)
v.receive("metric", {"value": 10})
v.receive("event", {"type": "deploy"})
tick = v.tick("my-loop", datetime.now(timezone.utc))
# tick.payload == {"metric": 10, "event": 1}

# Store — append-only log (in-memory or file-backed)
store = EventStore()           # in-memory
store.append(event)
store.since(cursor)

# Stream — typed async fan-out
stream: Stream[MyEvent] = Stream()
stream.tap(consumer)                    # attach
stream.tap(consumer, filter=is_error)   # filtered
stream.tap(consumer, transform=enrich)  # transformed
await stream.emit(event)                # broadcast
```

## API

| Export | Purpose |
|--------|---------|
| `Tick` | name + ts + payload (temporal snapshot atom) |
| `Vertex` | Where loops meet: kind routing + fold engines + tick emission |
| `Store` | Protocol for append-only logs |
| `EventStore` | In-memory Store with optional JSONL persistence |
| `FileStore` | JSONL-backed Store |
| `Stream` | Typed async fan-out with tap/emit |
| `Projection` | Incremental fold over events |
| `FileWriter` | JSONL persistence consumer |
| `Tailer` | Byte-offset tracking reader |
| `Forward` | Bridge between typed streams with transform |
