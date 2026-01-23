# Reactive Contracts

Where standard signals advice stops and where this framework picks up.

## The Standard Model

Any signals tutorial teaches these rules:

1. **Signals** hold mutable state
2. **Computeds** derive from Signals (pure, no side effects)
3. **Effects** run side effects when dependencies change
4. **Temporal concerns** (debounce, throttle) live outside the graph

This works when signal updates are user-paced (clicks, keystrokes, form input). The implicit assumption: _the graph evaluates fast enough that you can afford to re-derive everything on every change._

## Where It Breaks

Event-sourced UIs ingest streams—hundreds or thousands of events per second. The naive pattern:

```python
store_events = Signal([])  # or version Signal
view = Computed(lambda: derive_view(store_events()))
render_effect = Effect(lambda: display.update(view()))
```

Three problems emerge at scale:

| Problem | Root cause | Symptom |
|---------|-----------|---------|
| **Per-event rendering** | Effect fires on every Signal change, evaluates Computed, calls render | UI locks up at high event rates |
| **O(n) re-scan** | Computed re-derives from full event list each evaluation | CPU grows linearly with store size |
| **Unbounded memory** | Append-only store, no eviction | OOM on long-running tools |

The standard fix ("just debounce the input signal") doesn't work here—you can't debounce event ingestion without losing data.

## This Framework's Contracts

### Contract 1: Effects establish dependencies, not workload

The render Effect reads Signals to register as a dependency listener. It does **not** evaluate Computeds or call render. It only sets a dirty flag.

```python
# BaseApp._do_render (Effect body)
def _do_render(self) -> None:
    self._running()          # read Signal → register dependency
    self._mode()             # read Signal → register dependency
    self.store.version()     # read Signal → register dependency
    self._render_dirty = True  # the ONLY side effect
```

This Effect may fire thousands of times per second at high event rates. That's fine—it's just setting a boolean.

### Contract 2: Computeds evaluate at frame rate, not event rate

The main loop checks the dirty flag at ~20fps. Only then does it call `render()`, which reads Computeds. Computeds evaluate lazily on first read after invalidation.

```python
# BaseApp.run (main loop)
while self.running:
    if self._render_dirty:
        self._render_dirty = False
        live.update(self.render())  # Computeds evaluate HERE
    await asyncio.sleep(0.05)       # ~20fps
```

At 80k events/sec, the Effect fires 4000x per frame. Computeds still evaluate once per frame. The render budget is constant regardless of event rate.

### Contract 3: `_render_dependencies()` reads only Signals

Subclasses override `_render_dependencies()` to declare what triggers re-render. Reading a Computed here would force it to evaluate at event rate, defeating the debounce.

```python
# CORRECT
def _render_dependencies(self) -> None:
    self.store.version()     # Signal — just registers dependency
    self._log_filter()       # Signal — just registers dependency

# WRONG — forces per-event Computed evaluation
def _render_dependencies(self) -> None:
    self.filtered_events()   # Computed — evaluates immediately!
```

### Contract 4: Computeds are pure

No mutation, no I/O, no appending to external state. A Computed body is a function from (current signals) → value.

```python
# CORRECT
filtered = Computed(lambda: [e for e in store.events if matches(e, filter())])

# WRONG — mutates external state
_seen = set()
deduped = Computed(lambda: [e for e in store.events if e.id not in _seen and not _seen.add(e.id)])
```

If you need stateful derivation (e.g., deduplication, running averages), that state belongs in a Signal updated by the ingestion path, or in a future Projection/Fold primitive (see below).

### Contract 5: Batch multi-Signal mutations

When a single user action updates multiple Signals, wrap in `batch()` so the graph reacts once:

```python
from reaktiv import batch

# One Effect fire, one potential re-render
with batch():
    self._mode.set(Mode.VIEW)
    self._input_buffer.set("")
    self._filter.set(FilterQuery.parse(raw))
```

Without batch: 3 Effect fires → 3 dirty-flag sets (harmless but wasteful at the Effect level, and semantically incorrect—intermediate states are visible to any Computed that evaluates between them).

## What's Not Solved Yet

### Incremental projections (M2)

Every Computed currently re-scans the full event list. At ~500k events this breaks the frame budget. The fix is a Fold/Projection primitive:

```python
# Future API shape
class RateCounter(Projection[dict[str, int]]):
    initial = {}
    def apply(self, event: Event) -> None:
        self.state[event.source] = self.state.get(event.source, 0) + 1
```

Processes only new events since last frame. Computed cost becomes O(new_events_per_frame) instead of O(total_events).

### Windowed retention (M2)

Can't evict old events while Computeds need the full list. Incremental projections unblock eviction—once all consumers process incrementally, the store can drop events older than a threshold.

### LinkedSignal

A Signal whose initial/reset value is derived from another Signal. Useful for "derived-but-settable" state (e.g., a filter that defaults to the most recent source but can be overridden by the user). Not yet a formal primitive; currently hand-rolled in examples.

## Decision Guide

| I need to... | Use |
|-------------|-----|
| Hold mutable UI state (mode, filter text, selection) | Signal |
| Derive a view from signals + event list | Computed (evaluated in render) |
| Trigger re-render when state changes | `_render_dependencies()` reading Signals |
| Run I/O when state changes (tee to file, persist) | Effect (separate from render) |
| Update multiple signals atomically | `batch()` |
| Track rate/count/running average | Signal updated by ingestion (today) / Projection (M2) |
