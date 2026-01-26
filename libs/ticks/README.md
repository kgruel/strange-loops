# ticks

Personal-scale event infrastructure. Kafka concepts at file scale.

## Atom

```
Tick[T]
 ├─ ts: datetime     # when the temporal boundary fell
 └─ payload: T       # the frozen snapshot
```

Append-only logs, offset-tracking consumers, materialized views — without brokers. The file IS the broker.

```
Typed event → Stream → FileWriter → JSONL file
                ↓
            Projection (fold) → derived state
                ↓
             Tailer → replay from any offset
```

## Usage

```python
from datetime import datetime, timezone
from ticks import Tick, Stream, Projection, EventStore, FileWriter, Tailer, Forward

# Tick — frozen temporal snapshot
tick: Tick[dict] = Tick(
    ts=datetime.now(timezone.utc),
    payload={"count": 5, "total": 100},
)

# Stream — typed async fan-out
stream: Stream[MyEvent] = Stream()
stream.tap(consumer)                    # attach
stream.tap(consumer, filter=is_error)   # filtered
stream.tap(consumer, transform=enrich)  # transformed
await stream.emit(event)                # broadcast

# EventStore — append-only event log
store = EventStore[MyEvent](
    path=Path("events.jsonl"),
    serialize=lambda e: e.to_dict(),
    deserialize=MyEvent.from_dict,
)

# Projection — incremental fold over events
proj = StatusProjection(initial={})
stream.tap(proj)           # direct from stream
proj.advance(store)        # pull from store
```

## API

| Export | Purpose |
|--------|---------|
| `Tick` | ts + payload (temporal snapshot atom) |
| `Stream` | Typed async fan-out with tap/emit |
| `EventStore` | Append-only event log with version counter |
| `Projection` | Incremental fold over events |
| `FileWriter` | JSONL persistence consumer |
| `Tailer` | Byte-offset tracking reader |
| `Forward` | Bridge between typed streams with transform |
