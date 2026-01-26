# framework — Roadmap

## Done

- Stream[T] typed async broadcast with fan-out, filter, transform
- EventStore with JSONL persistence, eviction, version counter
- Projection as both store-consumer (advance) and stream-consumer (tap)
- FileWriter for JSONL persistence from streams
- Forward for bridging typed streams
- Instrument (zero-cost metrics, timing, gauges, rates)
- BaseSimulator lifecycle (state machine, crash/restart, rate control)

## Cleanup completed

- Removed external reactivity dependency (version counters replace Signals)
- Removed BaseApp / Rich scaffold (superseded by render layer)
- Removed FilterHistory, SelectionTracker (superseded by render components)
- Removed DebugPane (can be rebuilt on render layer if needed)
- Removed legacy demos (superseded by apps/)

## Possible (patterns the architecture supports)

- **Windowed projections** — time-bounded state (last N seconds)
- **Snapshot/restore** — serialize projection state for fast startup
- **Filtered subscriptions** — projections declare which event types they care about
- **Backpressure** — batch or drop when events arrive faster than projections advance
- **Multi-store joins** — projection that advances when any of N stores changes
