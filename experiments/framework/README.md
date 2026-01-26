# framework — Streaming Topology

Lightweight streaming topology for async Python apps. Event streams in, coherent derived state out via incremental projections. No external reactivity library — uses version counters for change detection.

## What it is

A streaming pipeline: you feed it events from async sources, route them through typed streams, fold them into derived state with projections. Projections advance O(new events) per frame.

```
Stream[T] (typed async broadcast)
    │
    ├─► EventStore (append-only log, optional JSONL persistence)
    │       │
    │       ▼
    │   Projection (incremental fold: apply(state, event) → state)
    │
    ├─► FileWriter (JSONL persistence)
    │
    └─► Forward (bridge to another Stream)
```

## Core primitives

### Stream[T]

Typed async broadcast. Emits to all tapped consumers.

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

store.add(ProcessStarted(pid=123))   # version increments
recent = store.since(cursor=50)      # incremental reads
store.evict_below(100)               # memory management
```

### Projection[S, T]

Incremental fold over events. Works as both a store consumer (advance) and a stream consumer (direct tap).

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

### FileWriter

JSONL persistence consumer.

### Forward

Bridge between typed streams with optional transform.

### Instrument (metrics)

Zero-cost-when-disabled observability.

```python
from framework.instrument import metrics

metrics.enable()
metrics.count("events_added")
with metrics.time("projection.advance"):
    projection.advance(store)
```

## Dependencies

- stdlib only
