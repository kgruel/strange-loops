# VERTEX: The Intersection Point

A Vertex is where loops meet. Facts arrive, get routed by kind to fold engines,
and state emerges. At a boundary, the accumulated state becomes a Tick — a
frozen snapshot that can enter the next loop as atomic input.

This document expands on the data flow described in the project CLAUDE.md.

---

## What a Vertex Is

Stream was plumbing pretending to be architecture. Vertex is the correction.

The rename carried a conceptual shift: from "a stream you tap into" to "an
intersection where cycles meet." Graph theory vocabulary won — loops are cycles,
vertices are where cycles meet. An intersection is a *place*, not a pipe.

A Vertex does three things:

1. **Routes** — dispatches facts by kind to registered fold engines
2. **Folds** — accumulates state via `Shape.apply` or custom fold functions
3. **Ticks** — produces frozen snapshots at temporal boundaries

The `Stream` class still exists as runtime infrastructure. But when you
think about architecture, think Vertex.

---

## Routing by Kind

Every Fact has a `kind` — an open string that determines where it goes.

```
Fact(kind="health", ts=..., payload={...})
  │
  ▼
Vertex
  ├─ "health" → health fold engine
  ├─ "deploy" → deploy fold engine
  ├─ "audit"  → audit fold engine
  └─ (unregistered kinds pass through to Store, don't fold)
```

Routing is explicit registration, not schema inference:

```python
vertex = Vertex("my-loop")
vertex.register("health", initial={}, fold=health_fold)
vertex.register("deploy", initial={}, fold=deploy_fold)
```

Shape convention: name your Shape after the primary Fact kind it folds. A Shape
called `"health"` folds Facts with `kind="health"`. This is legibility, not
dispatch — routing remains explicit in your wiring code.

Kind namespacing: infrastructure facts auto-emitted by a lib are prefixed by
origin (`ui.key`, `ui.action`). Domain facts stay bare (`"health"`, `"deploy"`).
The rule: if a lib emits it automatically, it gets a prefix. If you define it,
you name it.

---

## Fold Engines

Each registered kind gets a fold engine — a Projection that accumulates state.

```python
# Shape.apply as fold (when declarative folds fit)
vertex.register("audit", audit_shape.initial_state(), audit_shape.apply)

# Hand-written fold (when you need custom logic)
def health_fold(state: dict, payload: dict) -> dict:
    return {
        "count": state.get("count", 0) + 1,
        "last": payload.get("container", "?"),
        "status": payload.get("status", "?"),
    }
vertex.register("health", {}, health_fold)
```

Folds are pure `dict → dict`. No side effects, no async, no cross-lib imports.
The fold function receives current state and incoming payload, returns new state.
Immutable by default — create a new dict, don't mutate.

### Fold-before-boundary

When a fact arrives that both folds *and* triggers a boundary (same kind for
both), the fold completes first. You get the updated state in the Tick, not
the pre-fold state. This is a deliberate design choice documented in the
ticks library invariants.

---

## Branching: One Fact, Multiple Paths

A single fact can route to multiple vertices. The composition point decides.

```
Fact(kind="deploy", ...)
  │
  ├──→ VM Vertex (folds locally)
  │
  └──→ Audit Vertex (logs for compliance)
```

This isn't magic — it's explicit wiring at the integration layer:

```python
async def consume(fact):
    vm_vertex.receive(fact.kind, fact.payload)
    audit_vertex.receive(fact.kind, fact.payload)  # same fact, different path
```

The Vertex doesn't know about other vertices. Branching is topology, not
configuration. Wire it in your composition code.

---

## Merging: Multiple Sources, One Vertex

Multiple sources can feed a single vertex. This is how hierarchy emerges.

```
vm-1 ──tick──┐
             ├──→ Region Vertex (collects VM ticks)
vm-2 ──tick──┘
```

The region vertex doesn't care where ticks came from — it registers a fold
for whatever arrives. In `experiments/fleet.py`:

```python
region = Vertex("east")
region.register("vm-1", {}, collect_fold)
region.register("vm-2", {}, collect_fold)
```

Each VM's tick routes to its own fold engine. The region vertex merges them
by holding state for each source. When the region ticks, all VM states
snapshot together.

---

## Memory: Boundary-less Folding

Not every fold needs a boundary. A fold without a boundary is memory.

```python
vertex.register("config", initial={}, fold=config_fold)
# No boundary= parameter — this engine never auto-ticks
```

The config fold accumulates state indefinitely. You can read it via
`vertex.state("config")` at any time. It only resets if you manually reset
the underlying projection.

Use cases:
- Configuration that evolves over time
- Lookup tables built from facts
- State that needs to be queryable but not snapshotted

Memory is the complement to boundary. Some folds run forever. Some folds
exhale periodically. Same mechanism, different lifecycle.

---

## Boundaries: When State Becomes a Tick

A boundary is when accumulated state becomes a Tick — a frozen snapshot
with a name and timestamp.

Two modes:

### Auto-boundary (data-driven)

Register a boundary kind with the fold engine:

```python
vertex.register(
    "health",
    initial={},
    fold=health_fold,
    boundary="health.close",  # this kind triggers the boundary
    reset=True,               # reset to initial after tick
)
```

When a fact with `kind="health.close"` arrives, the vertex:
1. Folds the payload (if fold kind matches)
2. Snapshots the engine state into a Tick
3. Optionally resets the engine to initial state
4. Returns the Tick

Auto-boundary is declarative — the data carries the signal. The
`experiments/boundary.py` demo shows three semantics from one mechanism:
- `health.close` → reset each window
- `deploy.done` → fires only when deploy is complete
- `audit.complete` → carries state across cycles (reset=False)

### Manual boundary

Fire a boundary explicitly:

```python
tick = vertex.tick("end-of-day", now)
```

This snapshots *all* registered engines into a single Tick. No reset.
Useful for periodic snapshots driven by external clock, not data.

The `experiments/fleet.py` demo uses manual boundaries — an external loop
decides when each level ticks, not the data itself.

---

## The Three-Level Pattern

Vertices compose hierarchically. The `experiments/fleet.py` demonstrates:

```
L0: Leaf vertices (VMs)
    vm-1 [health]              → folds facts → tick
    vm-2 [health + deploy]     → folds facts → tick
    vm-3 [audit]               → folds facts → tick
    vm-4 [health + audit]      → folds facts → tick
         │
         ▼
L1: Region vertices
    east: collects vm-1, vm-2 ticks → tick
    west: collects vm-3, vm-4 ticks → tick
         │
         ▼
L2: Global vertex
    global: collects east, west ticks → tick
```

Each level:
1. Receives ticks from the level below
2. Folds them into its own state
3. Produces a tick for the level above

Same primitive at every level. A Tick is just a payload — the receiving
vertex doesn't care that it came from another vertex. Loops nest.

---

## Relationship to ticks Library

The `ticks` library provides the concrete implementation:

| Concept | Implementation |
|---------|----------------|
| Vertex | `ticks.Vertex` class |
| Fold engine | `ticks.Projection` (internal to Vertex) |
| Tick output | `ticks.Tick[T]` frozen dataclass |
| Persistence | `ticks.Store` protocol (EventStore, FileStore) |
| Fan-out | `ticks.Stream` + `ticks.Tap` |

Vertex is sync by design. The async bridge lives at the composition point:

```python
async def consume(fact):
    tick = vertex.receive(fact.kind, fact.payload)
    if tick is not None:
        await downstream.emit(tick)
```

This keeps the core logic testable and pure. Async plumbing wraps it.

---

## Summary

A Vertex is an intersection where loops meet. It routes facts by kind,
folds them into state, and produces Ticks at boundaries. Multiple facts
can branch to multiple vertices. Multiple sources can merge into one vertex.
Folds without boundaries are memory. Boundaries can be data-driven or manual.

The system is loops. Vertex is where they meet.
