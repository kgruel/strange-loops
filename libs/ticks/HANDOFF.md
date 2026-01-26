# ticks — Handoff

## 2026-01-26
Tick atom: `Tick(ts: datetime, payload: T)`, frozen, generic.
Projection fold callable: `Projection(initial, fold=fn)` eliminates
ShapeProjection bridge class. 61 tests across 3 test files.

Added `py.typed` marker. Removed dead pytest config (`pythonpath`, empty
`addopts`).

## Open
- **Stream[Tick] downstream**: Validate composability (daily rollups from hourly ticks).
- **Tick emission from Projection**: Boundary trigger not designed (time, count, or event).
- **EventStore naming**: Still called EventStore, should be Store.
