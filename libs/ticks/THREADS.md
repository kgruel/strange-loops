# THREADS — ticks

## Tick class
Design done: `Tick = ts + payload`, frozen dataclass, Generic[T].
Implementation subtask (`implement/tick-atom`) is in flight. After
merge, the atom table in CLAUDE.md matches reality.

## Stream[Tick] downstream
Once Tick exists, experiment with Projection emitting Tick[dict] into
a downstream Stream[Tick] for further projection or persistence. This
validates composability — e.g., daily rollups from hourly ticks, weekly
summaries from daily ticks.

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
