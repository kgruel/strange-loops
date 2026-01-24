# framework — Roadmap

## Proven (working in examples today)

Patterns validated by process_manager, dashboard, and http_logger:

- Multiple event types in a single store (ProcessStarted, Crashed, Metric, etc.)
- Multiple projections over the same store (status view + metrics view)
- JSONL persistence with load-on-init replay
- Eviction (cap in-memory events, cursor-based access still works)
- Windowed rate computation (events/sec over sliding window)
- Per-projection instrumentation (advance timing, events folded, lag)
- Version Signal integration (Computed/Effect react to store changes)
- Rate multiplier for simulation (debug pane controls event generation speed)

## Possible (patterns the architecture supports)

- **Multi-store composition** — projections that read from multiple stores (join streams)
- **Windowed projections** — time-bounded state (last N seconds, not just last N events)
- **Snapshot/restore** — serialize projection state for fast startup (skip replay)
- **Filtered subscriptions** — projections declare which event types they care about, skip irrelevant advances
- **Computed projections** — derived from other projections (not just raw events)
- **Backpressure** — when events arrive faster than projections can advance, batch or drop
- **Hot reload** — change a projection's apply() and re-fold from stored events

## Missing (require new primitives)

- **Snapshotting** — serialize projection.state to disk, restore cursor position. Enables fast startup for large event histories without full replay.
- **Subscription filtering** — `Projection.accepts(event) -> bool` to skip irrelevant events in advance(). Currently all projections scan all events.
- **Time-windowed state** — projections that automatically expire old state (e.g., "requests in the last 5 minutes"). Currently requires manual eviction logic in apply().
- **Multi-store joins** — a projection that advances when *any* of N stores changes. Currently 1:1 store:projection.

## Cleanup (from decoupling refactor)

- Remove `sim.py` (move to examples/)
- Remove `ui.py` (move to examples/)
- Remove `app.py` / BaseApp (move to examples/ — it's the Rich scaffold)
- Remove `filter.py` (superseded by render TextInputState)
- Remove `selection.py` (superseded by render ListState)
- Remove `debug.py` render imports (extract view to app code, keep state)
- Remove `keyboard.py` (move to render/)
- framework/ should depend on nothing except reaktiv
