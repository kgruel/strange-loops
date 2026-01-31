# LOOPS

The fundamental model. Everything else references back here.

## The truths

**Time is fundamental.** The past happened. Facts are observations of what occurred.
Events have a total order. There are no concurrency concerns — you are always in
the present, observing an ordered past.

**The observer is first-class.** Facts exist because a Peer observed them.
Without observation, nothing is recorded. The act of observing is itself
observable — observations about observations are still just facts.

**Everything is loops.** Facts flow, accumulate into state, state renders,
the observer sees, the observer acts, new facts flow. The loop closes.
There are no endpoints. There are no sinks. Everything continues.

## The atoms

Five primitives. Everything else is composition.

```
Fact     what happened       kind + ts + payload
Peer     who observed        name + horizon + potential
Tick     when a cycle ended  name + ts + payload + origin
Spec     how state folds     fields + folds + boundary
Vertex   where loops meet    routes facts, manages folds, produces ticks
```

**Fact** — An intentional observation. Something happened, a peer cared enough
to record it. The `kind` is a routing key. The `ts` is when. The `payload` is
what. Facts are immutable.

**Peer** — Identity with constraints. `horizon` bounds what a peer can see.
`potential` bounds what a peer can emit. `None` means unrestricted. Constraints
emerge through delegation: `kyle` delegates to `kyle/monitor` with narrower
potential. The hierarchy encodes participation level.

**Tick** — A temporal boundary marker. When a cycle completes, the accumulated
fold state is snapshot into a Tick. The Tick is the output of one loop and
can be the input of another. `origin` identifies which vertex produced it.
Ticks are how loops nest.

**Spec** — The fold contract. Declares what fields exist (fields) and how
they accumulate (folds). `Spec.apply(state, payload) -> state` is pure.
An optional `boundary` declares which fact kind triggers a Tick.

**Vertex** — Where loops intersect. Facts arrive, get routed by `kind` to
fold engines, accumulate into state. When a boundary fires, a Tick is produced.
Multiple loops can merge at a vertex (facts from different sources).
One loop can branch at a vertex (one fact triggers multiple paths).

## The data flow

```
                 ┌──────────────┐
                 │    Source    │  adapter: command, feed, endpoint, file...
                 └──────┬───────┘
                        │ vertex.ingest(kind, payload, observer)
                        ▼
Observer ────────→ Fact(kind, ts, payload)
                         │
                         ▼
                 ┌───────────────┐
                 │    Vertex     │
                 │               │
                 │  ┌─────────┐  │     Memory: boundary-less durable fold
                 │  │ Memory  │  │     Records everything, emits nothing
                 │  └─────────┘  │     (queryable for replay)
                 │       │       │
                 │  Route by kind│
                 │   │   │   │   │
                 │   ▼   ▼   ▼   │
                 │  Fold Fold Fold│    Spec.apply() per kind
                 │   │   │   │   │
                 │   └───┴───┘   │
                 │       │       │
                 │   Boundary?   │     Configured per fold
                 │       │       │
                 └───────│───────┘
                         │
            ┌────────────┴────────────┐
            │                         │
            ▼                         ▼
    Tick(name, ts, payload)     (other branches)
            │
            ├──→ Downstream Vertex (Tick is atomic input at next level)
            │
            └──→ Persist Vertex (stores tick, emits "tick.stored" fact)
                         │
                         ▼
                 Fact("tick.stored", ts, {...})
                         │
                         └──→ loops back to any vertex
```

Source adapters convert external input to Facts. They are infrastructure, not
atoms. See [VERTEX.md](docs/VERTEX.md) for the ingest interface.

## The topology

**Loop** — A closed path. Facts enter a vertex, fold into state, state renders
through a surface, the observer sees, the observer acts, new facts enter.
The end connects to the beginning.

**Vertex** — The intersection point. Where loops meet. A vertex is the only
structural primitive in the topology.

**Branch** — At a vertex, one fact can trigger multiple paths. The fact enters
once, routes to multiple destinations (fold engines, downstream vertices,
memory). This is not duplication — it's the loop branching.

**Merge** — At a vertex, facts from multiple sources converge. A health timer
and a user keypress both arrive at the same vertex. The vertex doesn't know
or care about the source. This is loops intersecting.

**Memory** — A fold with no boundary. Accumulates all facts, never produces
a Tick. Durable if persisted, ephemeral if not. The loop's silent record.
Queryable for replay. Not a separate primitive — just a fold configuration.

## What dissolved

During model development, these concepts were introduced and then dissolved
back into the atoms:

| Concept | Dissolved into | Why |
|---------|---------------|-----|
| Sink | Fold state | Loops have no terminals. "Sink" implies an endpoint. |
| Store | Durable fold | Storage is a property of state, not a separate type. |
| Witness | Peer + Vertex | A "witness" is just a peer whose job is to observe and emit. |
| Tap | Vertex | Emission from storage is vertex behavior. |
| Memory | Boundary-less fold | Silent accumulation is just a fold that never ticks. |

The atoms are complete. New requirements don't require new primitives.

## Surfaces

A **Surface** is where the loop touches the observer. It renders state outward
and emits interactions inward as new facts.

```
Vertex.state ──→ Surface ──→ Observer sees
                    │
Observer acts ──→ Surface.emit ──→ Fact ──→ Vertex
```

**Cell** is the first surface (terminal, character grid). Other surfaces would
use different paradigms (web, API, documents) but the same contract: consume
state, render outward, emit inward.

Surfaces are not atoms. They are the boundary where loops meet reality.

## References

Deeper dives that loop back here:

| Doc | Focus |
|-----|-------|
| [VERTEX.md](docs/VERTEX.md) | The intersection point — routing, folding, branching |
| [TEMPORAL.md](docs/TEMPORAL.md) | Boundaries, ticks, nesting — how loops mark time |
| [PERSISTENCE.md](docs/PERSISTENCE.md) | Durable state, memory, replay — how loops remember |
| [PEERS.md](docs/PEERS.md) | Identity, delegation, constraints — who observes |

Each doc unpacks one aspect of the model and references back to LOOPS.md
as the ground truth.

---

*The system is loops. You are a Peer in one.*
