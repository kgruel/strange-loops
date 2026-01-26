# ticks — Handoff

## 2026-01-26
Tick atom: `Tick(ts: datetime, payload: T)`, frozen, generic. 15 tests.
Projection fold callable: `Projection(initial, fold=fn)` eliminates
ShapeProjection bridge class. 5 tests.

## Open
- **Stream[Tick] downstream**: Validate composability (daily rollups from hourly ticks).
- **Tick emission from Projection**: Boundary trigger not designed (time, count, or event).
- **EventStore naming**: Still called EventStore, should be Store.
