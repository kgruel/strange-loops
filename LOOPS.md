# LOOPS

The fundamental model. Everything else references back here.

## The Truths

**Time is fundamental.** The past happened. Facts are observations of what occurred.
Events have a total order. You are always in the present, observing an ordered past.

**The observer is first-class.** Facts exist because someone observed them. Without
observation, nothing is recorded. The act of observing is itself observable —
observations about observations are still just facts.

**Everything is loops.** Facts flow in, accumulate into state, boundaries fire,
ticks flow out. The end connects to the beginning. There are no endpoints.

**Everything flows one direction.** Failures, conditionals, nested spans — they're
all just more facts. No special handling. No rollback. Just accumulation.

## The Atoms

Three primitives. Everything else is composition or runtime.

```
Fact    what happened           kind + ts + payload + observer
Spec    how state accumulates   fields + folds + boundary
Tick    what a period became    name + ts + payload + origin
```

**Fact** — A single observation. Something happened, someone cared enough to record
it. The `kind` is a routing key. The `ts` is when. The `payload` is what. The
`observer` is who. Facts are immutable.

**Spec** — The contract. Declares what fields exist (shape), how they accumulate
(folds), and when a cycle completes (boundary). `Spec.apply(state, payload) → state`
is pure. Parse vocabulary (Split, Pick, Rename...) shapes raw input. Fold vocabulary
(Latest, Count, Sum, Collect...) transforms state.

**Tick** — A handle to a semantic period. When a boundary fires, accumulated state
snapshots into a Tick. The `payload` is the fold result. The period is the facts
between the last boundary and this one. At full fidelity, you can traverse into
those facts — some are themselves Ticks from other loops. Depth emerges from
ticks-as-facts flowing into other loops.

## Two Libraries

### data

Everything about the data itself.

```
Fact        the observation record
Spec        the contract (fields, folds, boundary)
Source      ingress adapter (run command → parse → facts)
Parse       shaping vocabulary (Split, Pick, Rename, Transform, Coerce, Skip)
Fold        transformation vocabulary (Latest, Count, Sum, Collect, Upsert, TopN)
Validation  static shape checking (parse output vs spec input_fields)
```

One concern: **what data looks like, how to get it, how to shape it.**

### vertex

Everything about execution.

```
Vertex      receives facts, routes by kind, manages loops
Loop        executes Spec.apply, tracks state between boundaries
Store       persistence (facts and ticks survive restarts)
Peer/Grant  identity and gating policy
```

One concern: **how it runs, where state lives, when boundaries fire.**

## The Data Flow

```
External World
      │
      │  command, script, curl, whatever
      ▼
┌─────────────────────────────────────────────────────────┐
│  Source                                                 │
│    run: "df -h"                                         │
│    format: lines | json | blob                          │
│    parse: [Split, Pick, Rename, Coerce]                 │
│    kind: "disk"                                         │
│    observer: "disk-monitor"                             │
└─────────────────────────────────────────────────────────┘
      │
      │  Fact(kind, ts, payload, observer)
      ▼
┌─────────────────────────────────────────────────────────┐
│  Vertex                                                 │
│                                                         │
│    Store ─── append fact, queryable by time range       │
│      │                                                  │
│      │                                                  │
│    Route by kind                                        │
│      │                                                  │
│      ├────────────┬────────────┐                        │
│      ▼            ▼            ▼                        │
│    Loop         Loop         Loop                       │
│    Spec.apply   Spec.apply   Spec.apply                 │
│      │                                                  │
│    Boundary?                                            │
│      │                                                  │
└──────│──────────────────────────────────────────────────┘
       │
       ▼
  Tick(name, ts, payload, origin)
       │
       ├──→ Store.append(tick)
       │
       ├──→ Downstream Vertex (tick becomes fact, origin becomes observer)
       │
       └──→ Surface renders → observer sees → observer acts → new facts
                                                    │
                                                    └──→ back to Vertex
```

## Fidelity and Depth

A Tick is a handle to a semantic period.

**Minimal fidelity:** Just the payload. `{status: "success", count: 47}`

**Full fidelity:** The payload, plus every fact in the period (`Store.since(last_tick)`),
plus recursive traversal into any facts that are themselves Ticks from other loops.

Examples at different scales:

- **Auth failure:** 9 attempts, timer ticks, threshold → Tick `{locked: true}`. No
  exception handling. Just facts that accumulated to locked state.

- **Deploy:** Build tick + test tick + push tick + logs → Tick `{status: "success"}`.
  At full fidelity, descend into each phase.

- **Board meeting:** Month of project facts, incident ticks → meeting Tick. The month
  collapses into a few hours where new observers discuss and decide.

- **Grandma's Birthday:** Year of family facts → Tick `{celebrated: true}`. The year
  is in there if you want it.

The hierarchy isn't designed. It emerges from ticks-as-facts flowing into other loops.

## Surfaces

A **Surface** is where the loop touches the observer. Renders state outward,
emits interactions inward as new facts.

```
Vertex.state ──→ Surface ──→ Observer sees
                    │
Observer acts ──→ Surface.emit ──→ Fact ──→ Vertex
```

**cells** is the terminal surface — character grid, styles, layouts. Other surfaces
(web, API, documents) would use different paradigms but the same contract.

Surfaces close the loop. They are not atoms.

## What Dissolved

During model development, these concepts were introduced and then dissolved:

| Concept | Dissolved into | Why |
|---------|---------------|-----|
| Peer (as atom) | observer field + Grant policy | Identity is a string on Fact, policy is runtime |
| Vertex (as atom) | Runtime library | Vertex is execution, not data |
| Sink | Fold state | Loops have no terminals |
| Store (as atom) | Vertex capability | Persistence is a runtime property |
| Witness | Observer + Vertex | A witness is just an observer whose job is to emit |
| Memory | Boundary-less fold | Silent accumulation is just a fold that never ticks |

Three atoms remain: Fact, Spec, Tick.

## References

| Doc | Focus |
|-----|-------|
| [VERTEX.md](docs/VERTEX.md) | Routing, folding, branching |
| [TEMPORAL.md](docs/TEMPORAL.md) | Boundaries, nesting, how loops mark time |
| [PERSISTENCE.md](docs/PERSISTENCE.md) | Durable state, replay, how loops remember |

---

*The system is loops. You are an observer in one.*
