# THREADS — ticks

## [resolved] Tick class
Tick atom implemented: `Tick(ts: datetime, payload: T)`, frozen,
Generic[T]. Exported from ticks. Atom table in CLAUDE.md matches.

## [resolved] Projection fold callable
Projection now accepts an optional `fold` callable in __init__:
`Projection(initial, fold=fn)`. If provided, `apply()` delegates to
the callable. Subclass pattern still works. This eliminates the need
for bridge classes at composition points.

## Stream[Tick] downstream
Once the pipeline is rebuilt, experiment with Projection emitting
Tick[dict] into a downstream Stream[Tick] for further projection or
persistence. This validates composability — e.g., daily rollups from
hourly ticks, weekly summaries from daily ticks.

## Tick emission from Projection
Currently Projection maintains live state (continuously updating dict).
The Tick concept adds a second output path: at a temporal boundary,
snapshot the state into a Tick and emit it downstream. The boundary
trigger mechanism isn't designed yet — could be time-based, count-based,
or event-driven.

## EventStore naming
EventStore was renamed to Store in the rill->ticks transition but the
class in prism is still called EventStore. Minor inconsistency to clean
up.
