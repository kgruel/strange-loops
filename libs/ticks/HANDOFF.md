# ticks — Handoff

## 2026-01-27
Major refactor: Tick name + Vertex + Store abstraction.

**(A) Tick.name** — Added `name: str` as the first field on `Tick`.
Identifies which loop produced the tick. All existing tests updated.

**(B) Store abstraction** — Added `Store` protocol (append, since, close).
Renamed `EventStore.add()` → `append()` to match. Created `FileStore`
wrapping FileWriter + Tailer behavior behind the Store interface.

**(C) Vertex** — Where loops meet. Kind-based routing: register a fold
per kind, receive facts dispatched by kind, fire temporal boundary to
produce a Tick. Optional Store backing (appends on receive). Projection
is the internal fold engine — callers register folds, not Projections.

93 tests across 5 test files.

## 2026-01-26
Tick atom: `Tick(ts: datetime, payload: T)`, frozen, generic.
Projection fold callable: `Projection(initial, fold=fn)` eliminates
ShapeProjection bridge class. 61 tests across 3 test files.

Added `py.typed` marker. Removed dead pytest config (`pythonpath`, empty
`addopts`).

## Open
- **Stream[Tick] downstream**: Validate composability (daily rollups from hourly ticks).
- **Vertex boundary triggers**: Currently manual (`tick()` call). Could add time-based, count-based, or event-based auto-triggering.
- **Vertex async receive**: `receive()` is synchronous. If Stream integration is needed, add `async consume()` adapter.
