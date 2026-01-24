# framework — Event Sourcing + Reactive Projections

Lightweight event sourcing with incremental projections for async Python apps. Multiple event streams in, coherent derived state out. ~350 lines of core.

## What it is

A context loom: you feed it raw events from multiple async sources, it weaves them into derived state through incremental folds. Projections advance O(new events) per frame — not O(all events). State is exposed as reaktiv Signals for reactive propagation.

```
Raw events (many sources)
    │
    ▼
EventStore (append-only log, optional JSONL persistence)
    │
    ▼
Projection (incremental fold: apply(state, event) → state)
    │
    ▼
Signal[S] (reactive derived state, triggers downstream)
```

## Where it sits

| Library | Model | Weight |
|---------|-------|--------|
| eventsourcing (Python) | Full ES/CQRS, database-backed | Heavy |
| RxPY | Observable streams, operators | Complex |
| reaktiv | Signal/Computed/Effect primitives | Minimal |
| **this** | EventStore + Projection on reaktiv | Minimal+incremental |

You reach for this when:
- Multiple async event streams need combining into coherent state
- Derived state should update incrementally (not full recomputation)
- You want persistence/replay for debugging (JSONL)
- You need observable state without full Rx complexity

## Core primitives

### EventStore[T]

Append-only event log. Generic over event type.

```python
store = EventStore[MyEvent](
    path=Path("events.jsonl"),       # optional persistence
    serialize=lambda e: e.to_dict(),
    deserialize=MyEvent.from_dict,
)

store.add(ProcessStarted(pid=123))   # version Signal bumps
store.add(ProcessCrashed(pid=123))

recent = store.since(cursor=50)      # incremental reads
store.evict_below(100)               # memory management
```

### Projection[S, T]

Incremental fold over an EventStore. Subclass and define `apply()`.

```python
class StatusProjection(Projection[dict[int, str], ProcessEvent]):
    def apply(self, state, event):
        if isinstance(event, ProcessStarted):
            return {**state, event.pid: "running"}
        if isinstance(event, ProcessCrashed):
            return {**state, event.pid: "crashed"}
        return state

status = StatusProjection(initial={})
status.advance(store)                # processes only new events
current = status.state()             # dict[int, str]
```

### Instrument (metrics)

Zero-cost-when-disabled observability.

```python
from framework.instrument import metrics

metrics.enable()
metrics.count("events_added")
with metrics.time("projection.advance"):
    projection.advance(store)
metrics.gauge("store_size", len(store.events))

rate = metrics.rate("events_added", window_sec=5.0)  # windowed rate
snap = metrics.snapshot()                             # all metrics
```

## Dependencies

- `reaktiv` (Signal/Computed/Effect)
- stdlib only for everything else

## Renderer-agnostic

Framework exposes Signals. Any renderer can consume them:
- **render engine** — RenderApp reads `projection.state()` in its render loop
- **Rich** — Effect triggers `Live.update()` when state changes
- **Plain text** — print state on each change

The examples/ directory demonstrates both Rich-based and render-based consumption.
