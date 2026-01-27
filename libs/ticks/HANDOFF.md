# ticks — Handoff

## 2026-01-27
Major refactor: Tick name + Vertex + Store abstraction + boundary triggering.

**(A) Tick.name** — Added `name: str` as the first field on `Tick`.
Identifies which loop produced the tick. All existing tests updated.

**(B) Store abstraction** — Added `Store` protocol (append, since, close).
Renamed `EventStore.add()` → `append()` to match. Created `FileStore`
wrapping FileWriter + Tailer behavior behind the Store interface.

**(C) Vertex** — Where loops meet. Kind-based routing: register a fold
per kind, receive facts dispatched by kind, fire temporal boundary to
produce a Tick. Optional Store backing (appends on receive). Projection
is the internal fold engine — callers register folds, not Projections.

**(D) Boundary triggering on Vertex** — Per-kind auto-tick on boundary.
`register(..., boundary="end-of-day", reset=True)` declares which fact kind
triggers a boundary for that fold engine. `receive()` returns `Tick | None`:
after folding, if the incoming kind matches a boundary, snapshots that
engine's state → Tick (name = fold kind, payload = single engine state,
origin = vertex name) and optionally resets. Fold-before-boundary: if
boundary kind == fold kind, payload folds first. Manual `tick()` unchanged
(snapshots all engines, no reset). `Projection.reset()` added to support
engine reset. Primitive params only — no Boundary import from shapes.

**(E) Stream[Tick] downstream validated** — Integration tests prove:
boundary → Stream[Tick] → Projection receives Tick; two-level nested
loops (upstream facts → boundary Tick → downstream Vertex folds Ticks);
Shape.boundary descriptor wired to Vertex.register at composition point.

122 tests across 5 test files.

## 2026-01-26
Tick atom: `Tick(ts: datetime, payload: T)`, frozen, generic.
Projection fold callable: `Projection(initial, fold=fn)` eliminates
ShapeProjection bridge class. 61 tests across 3 test files.

Added `py.typed` marker. Removed dead pytest config (`pythonpath`, empty
`addopts`).

## Closed
- **Stream[Tick] downstream** — Validated. Integration tests prove boundary
  Tick → Stream → consumer, nested loops, and Shape→Vertex wiring.
- **Vertex async receive** — Closed by design. Vertex is a sync fold machine.
  `receive()` returns `Tick | None` — the return value is the output channel.
  The Consumer protocol (`async consume() -> None`) has no return channel, so
  Vertex doesn't implement it directly. The async bridge lives at the
  composition point (~5 lines) where the real decisions are: extract
  kind/payload from event type, call receive, route Tick to downstream
  Stream. Same pattern as the Fact→Shape bridge. If boilerplate accumulates
  across integrations, extract a thin convenience then.

## Open
(none)
