# ticks

Personal-scale event infrastructure. Kafka concepts at file scale.

## What it is

Append-only logs, offset-tracking consumers, materialized views — without brokers. The file IS the broker.

```
Typed event → Stream → FileWriter → JSONL file
                ↓
            Projection (fold) → derived state
                ↓
             Tailer → replay from any offset
```

## Core primitives

### Tick[T]

Frozen temporal snapshot — the atom. Wraps any payload with the timestamp of when a temporal boundary fell.

```python
from datetime import datetime, timezone
from ticks import Tick

tick: Tick[dict] = Tick(
    ts=datetime.now(timezone.utc),
    payload={"count": 5, "total": 100},
)
```

### Stream[T]

Typed async fan-out. Emits to all tapped consumers.

```python
stream: Stream[MyEvent] = Stream()
stream.tap(consumer)                    # attach
stream.tap(consumer, filter=is_error)   # filtered
stream.tap(consumer, transform=enrich)  # transformed
await stream.emit(event)                # broadcast
```

### EventStore[T]

Append-only event log with version counter.

```python
store = EventStore[MyEvent](
    path=Path("events.jsonl"),
    serialize=lambda e: e.to_dict(),
    deserialize=MyEvent.from_dict,
)

store.add(event)              # version increments
recent = store.since(cursor)  # incremental reads
store.evict_below(100)        # memory management
```

### Projection[S, T]

Incremental fold over events. O(new events) per update.

```python
class StatusProjection(Projection[dict[int, str], ProcessEvent]):
    def apply(self, state, event):
        if isinstance(event, ProcessStarted):
            return {**state, event.pid: "running"}
        return state

proj = StatusProjection(initial={})
stream.tap(proj)           # direct from stream
# or
proj.advance(store)        # pull from store
```

### FileWriter[T]

JSONL persistence consumer.

```python
writer = FileWriter(Path("events.jsonl"), serialize=lambda e: e.__dict__)
stream.tap(writer)
```

### Tailer[T]

Byte-offset tracking reader. Replay or follow.

```python
tailer = Tailer(Path("events.jsonl"), deserialize=MyEvent.from_dict)
new_events = tailer.poll()  # returns new events since last poll
tailer.reset()              # replay from beginning
```

### Forward[T, U]

Bridge between typed streams with transform.

```python
forward = Forward(target_stream, transform=lambda e: enrich(e))
source_stream.tap(forward)
```

## Dependencies

None. Stdlib only.
