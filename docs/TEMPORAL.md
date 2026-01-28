# TEMPORAL: Boundaries and Nesting

This document explains how loops mark time. Read LOOPS.md first — it establishes the core architecture. This document zooms in on the temporal mechanism: boundaries, ticks, and nesting.

---

## The Problem: When Does a Cycle Complete?

A loop folds facts into state. State accumulates. But accumulation without punctuation is noise. At some point, the folded state becomes meaningful enough to act on — to snapshot, to emit, to pass forward.

That "some point" is a **boundary**.

The question isn't "how much time has passed?" but "what just happened that gives meaning to everything before it?" Boundaries fire on domain semantics, not clocks.

---

## Boundaries: Semantic Time

A boundary is a declaration: *this kind of fact completes a cycle*.

```python
Boundary(kind="deploy.done", reset=True)
```

Two fields:
- **kind**: which fact kind triggers the boundary
- **reset**: whether to clear state after the boundary fires

The boundary kind is typically different from the folded kind. Health facts accumulate, but `health.close` triggers the snapshot. Deploy facts accumulate stages, but `deploy.done` marks completion.

This is semantic time. The boundary fires when the domain says so:

| Domain | Accumulation | Boundary trigger |
|--------|--------------|------------------|
| Container health | status observations | `health.close` (external signal) |
| Deploy pipeline | stage transitions | `deploy.done` (stage reached "done") |
| Audit scan | scanned counts | `audit.complete` (scan finished) |
| User session | interactions | `session.end` (logout or timeout) |

No timers. No polling intervals. The data carries its own punctuation.

---

## How Boundaries Fire

A Shape declares a boundary. The composition layer reads it and wires the Vertex:

```python
# Shape declares the contract
health_shape = Shape(
    name="health",
    boundary=Boundary("health.close", reset=True),
    ...
)

# Composition layer wires the Vertex from the Shape
vertex.register(
    "health",                      # kind to fold
    health_shape.initial_state(),  # starting state
    health_fold,                   # fold function
    boundary="health.close",       # kind that triggers boundary
    reset=True,                    # reset after tick
)
```

When the boundary kind arrives:

1. **Fold completes first** (if boundary kind == fold kind)
2. **State snapshots** into a Tick
3. **Reset** (if configured) — state returns to initial
4. **Tick returns** from `receive()` — caller routes it forward

```python
# Normal fact — fold, no tick
vertex.receive("health", {"container": "nginx", "status": "running"})
# returns None

# Boundary fact — fold (if applicable), then tick
tick = vertex.receive("health.close", {})
# returns Tick(name="health", ts=..., payload={...}, origin="vm-1")
```

The boundary fact can carry payload (folded before snapshot) or be empty (pure signal). The mechanism is the same.

---

## The Output: Tick

When a boundary fires, the output is a Tick:

```
Tick[T]
 ├─ name: str       # which fold produced this (matches the fold kind)
 ├─ ts: datetime    # when the boundary fired
 ├─ payload: T      # frozen snapshot of folded state
 └─ origin: str     # which Vertex produced this tick
```

A Tick is a **frozen snapshot at a semantic moment**. It's not "state at time T" — it's "state when this cycle completed."

The payload is whatever the fold produced. Health might be `{count: 12, last: "redis", status: "running"}`. Deploy might be `{target: "api-v2.3", stage: "done", step: 5}`. The Shape determines the structure.

---

## Reset vs. Carry

The boundary's `reset` field controls what happens to state after the tick:

**Reset (reset=True)**: State returns to initial after the boundary. Each cycle starts fresh. Use for windowed observations where history doesn't carry forward.

```python
# Health: each window is independent
Boundary("health.close", reset=True)
# cycle 1: count=12 → tick → state resets to {count: 0}
# cycle 2: count=8  → tick → state resets to {count: 0}
```

**Carry (reset=False)**: State persists across boundaries. The tick captures a snapshot, but accumulation continues. Use for running totals or audit trails.

```python
# Audit: totals accumulate forever
Boundary("audit.complete", reset=False)
# cycle 1: scanned=42  → tick → state stays {scanned: 42}
# cycle 2: scanned=89  → tick → state stays {scanned: 89}
```

Same mechanism, different semantics. The boundary declaration carries the intent.

---

## Manual vs. Automatic Boundaries

Two ways to produce ticks:

**Automatic (data-driven)**: Boundary kind arrives → tick fires for that specific fold engine.

```python
tick = vertex.receive("health.close", {})  # returns Tick | None
```

**Manual (external signal)**: Explicit `tick()` call → tick fires for all fold engines at once.

```python
tick = vertex.tick("my-loop", now)  # returns Tick (all engines)
```

Manual ticks are useful when an external clock or orchestrator controls timing. Automatic ticks are useful when the data itself carries completion signals.

Both produce the same Tick structure. The difference is who decides when.

---

## Nesting: Ticks at Every Level

Here's the key insight: **a Tick from level N is input at level N+1**.

```
Level 0: VMs
    vm-1 folds health facts → boundary → Tick(origin="vm-1", ...)
    vm-2 folds health facts → boundary → Tick(origin="vm-2", ...)

Level 1: Regions
    east vertex receives vm-1 and vm-2 ticks
    east folds ticks → boundary → Tick(origin="east", ...)

Level 2: Global
    global vertex receives east and west ticks
    global folds ticks → boundary → Tick(origin="global", ...)
```

The receiving vertex doesn't know or care that its input was a Tick. It's just payload arriving at a kind. The fold function handles it like any other fact.

```python
# Level 1 fold: receives tick payload, nests it
def collect_fold(state: dict, tick_payload: dict) -> dict:
    origin = tick_payload.get("origin", "?")
    kind = tick_payload.get("kind", "?")
    nested = dict(state)
    nested.setdefault(origin, {})[kind] = tick_payload.get("data", {})
    return nested
```

Same primitive at every level. Facts go in, ticks come out. The tick from one loop is just a fact to the next loop.

---

## Concrete Example: Three-Level Fleet

From `experiments/fleet.py`:

```
vm-1 [health]            ──→ tick ──┐
                                    ├──→ east ──→ tick ──┐
vm-2 [health + deploy]   ──→ tick ──┘                    │
                                              ├──→ global ──→ tick
vm-3 [audit]             ──→ tick ──┐                    │
                                    ├──→ west ──→ tick ──┘
vm-4 [health + audit]    ──→ tick ──┘
```

Each level compresses:
- **L0**: Raw facts (container status, deploy stage, scan results) → per-VM ticks
- **L1**: VM ticks → per-region ticks (collects which VMs reported what)
- **L2**: Region ticks → global tick (full system snapshot)

The global tick payload is nested three deep: `{east: {vm-1: {health: {...}}, vm-2: {...}}, west: {...}}`. All the detail is there, but accessed through one frozen snapshot.

---

## Semantic Time vs. Clock Time

Traditional event systems tick on intervals: "every 5 seconds, snapshot." This couples the system to a clock.

Boundary-driven systems tick on meaning: "when this deploy finishes, snapshot." This couples the system to the domain.

The difference matters:
- **Clock-driven**: You might snapshot mid-deploy, capturing incoherent state
- **Boundary-driven**: You snapshot at completion, capturing coherent state

Boundaries let the domain define coherence. The infrastructure doesn't impose artificial rhythm.

---

## The Pattern

1. **Shape declares boundary** — which kind completes a cycle, whether to reset
2. **Composition wires Vertex** — reads Shape, configures fold engine
3. **Facts accumulate** — fold builds state
4. **Boundary arrives** — tick fires, state optionally resets
5. **Tick routes forward** — enters the next Vertex as input
6. **Repeat at next level** — same primitive, larger timescale

Boundaries are declarations. Ticks are snapshots. Nesting is composition. The loop marks its own time.
