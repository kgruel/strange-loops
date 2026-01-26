# Projections

## The Problem

Computed values re-derive state from scratch on every evaluation. For event-sourced state that accumulates over time, this means O(n) re-scan of the entire event log at frame rate. With thousands of events, this becomes a bottleneck.

```python
# O(all events) every time any signal changes
self.process_logs = Computed(lambda: self._compute_process_logs())

def _compute_process_logs(self):
    self.store.version()  # depend on version signal
    logs = {}
    for event in self.store.events:  # scan ALL events every frame
        if event.kind == "log":
            logs.setdefault(event.pid, []).append(event)
    return logs
```

## The Solution

A **Projection** is an incremental fold over an EventStore. It maintains a cursor and only processes new events since the last advance. Cost per frame: O(new events) rather than O(all events).

A Projection is NOT a Computed — it's honest about being mutable state. It holds a `.state` Signal that other reactivity can depend on.

## Data Flow

```
event arrives → store.version bumps → render effect marks dirty
                                        ↓
frame tick → advance all projections → projection reads store.since(cursor)
                                        ↓
             apply(state, event) per new event → .state.set(result)
                                        ↓
                              render() reads .state
```

## API Reference

### `Projection` base class

```python
from framework import Projection

class MyProjection(Projection[StateType, EventType]):
    def __init__(self):
        super().__init__(initial_state)

    def apply(self, state: StateType, event: EventType) -> StateType:
        """Process one event, return new state."""
        # ... accumulate into state ...
        return state
```

**Fields:**
- `.state: Signal[S]` — the accumulated state, readable as a reactive Signal
- `.cursor: int` — logical index into the EventStore (how far we've consumed)

**Methods:**
- `apply(state, event) -> state` — override in subclass. Called once per new event.
- `advance(store)` — processes `store.since(cursor)`, calls `apply` for each, updates `.state` once at the end. Default implementation; subclasses only override `apply()`.

### `store.since(cursor)`

```python
events = store.since(n)  # returns store.events[n:] (logical indices)
```

Returns events from logical index `n` onward. Raises `IndexError` if `n` is below the eviction watermark (events have been evicted and are no longer available).

### `store.evict_below(n)`

```python
store.evict_below(n)  # removes events below logical index n
```

Evicts events below logical index `n`. After eviction, `since()` still works with cursors >= `n`. Internal offset tracking ensures logical indices remain stable.

### `register_projection(projection, store=None)`

```python
class MyApp(BaseApp):
    def __init__(self, store, console):
        super().__init__(console)
        self.my_proj = MyProjection()
        self.register_projection(self.my_proj, store)
```

Registers a projection to be advanced each frame tick. The `store` argument sets the EventStore used for all projections (only needed on the first call).

### `enable_retention(store=None)`

```python
self.enable_retention()  # after registering projections
```

Enables automatic retention. Each frame tick after advancing projections, computes `min(p.cursor for p in projections)` as the low watermark and calls `store.evict_below(watermark)`.

## How Retention Works

1. Each Projection tracks its own `cursor` — how far it has consumed.
2. After all projections advance, BaseApp computes the **watermark**: `min(cursor)` across all registered projections.
3. Events below the watermark are safe to evict — all projections have already processed them.
4. `store.evict_below(watermark)` removes those events from memory.
5. The store maintains an internal `_offset` so that logical indices (cursors) remain valid.

Retention is opt-in. Without `enable_retention()`, events accumulate indefinitely.

## When to Use Projection vs Computed

| Use case | Primitive | Why |
|----------|-----------|-----|
| Accumulation over events (counts, logs, state machines) | **Projection** | O(new) per frame, not O(all) |
| Pure derivation from current signals | **Computed** | No event history needed, lazy eval is fine |
| Filtering/sorting a list | **Computed** | Derives from current state, not accumulated |
| Running totals, time-series aggregation | **Projection** | Classic fold pattern |

**Rule of thumb:** If your computation iterates `store.events`, it's a Projection candidate. If it reads other Signals/Computeds and transforms their current values, keep it as Computed.
