# VOCABULARY

Canonical definitions for the loops system. One page, no ambiguity.

---

## The One-Liner

**Facts enter Loops. Loops reduce Facts through Specs and emit Ticks at Spec boundaries. Vertices route Ticks to other Loops.**

---

## Atoms

Atoms are immutable, independent, and compose only at integration points.

| Atom | Structure | Question | Meaning |
|------|-----------|----------|---------|
| **Peer** | name + horizon + potential | *who* | Identity with scoped perception and capability. Delegation narrows. |
| **Fact** | kind + ts + payload | *what* | Immutable observation. Everything enters as a Fact. Append-only. |
| **Spec** | schemas + reducer + boundary | *how* | Loop contract. Declares input/state shape, reduction, and boundary semantics. |
| **Tick** | name + ts + payload | *when* | Boundary artifact. Frozen snapshot of folded state. Derived, not observed. |
| **Cell** | char + style | *(render)* | Atomic unit of output. Base of surfaces. |

---

## Runtime Concepts

Not atoms — the minimal execution layer where atoms meet.

### Loop

A running process that:
1. Receives **Facts**
2. Reduces them through a **Spec.reducer**
3. Checks **Spec.boundary**
4. Emits a **Tick** when boundary fires
5. Applies reset/carry policy, continues

Loops don't share state. They exchange immutable artifacts.

### Vertex

Loop plumbing — where loops meet. Provides:
- **Ingress**: accept Facts and Ticks
- **Routing**: direct inputs to loops by kind
- **Store**: optional persistence
- **Replay**: re-enter stored history
- **Connection**: bridge across process/network boundaries

A vertex doesn't interpret meaning. It guarantees delivery and ordering.

### Surface

Interactive renderer that closes the loop:
- **Render**: state → Cells (via Blocks, Buffers)
- **Input**: keyboard/mouse → Facts (`ui.key`, `ui.click`)

State goes out as cells. Interactions come back as facts.

---

## Allowed Verbs

| Concept | Verbs |
|---------|-------|
| Peer | delegate, restrict |
| Fact | observe, append |
| Spec | declare, reduce, test |
| Tick | emit, route, store |
| Loop | receive, reduce, emit |
| Vertex | route, store, replay, connect |
| Surface | render, emit |
| Cell | paint |

---

## Composition Rules

1. **No shared mutable state** — Loops intersect only by exchanging immutable artifacts.

2. **Tick-to-Fact bridging** — A Tick routed to another loop becomes input (a Fact kind the receiving loop understands).

3. **Dirty close is normal** — If a loop doesn't hit its boundary (crash, disconnect), history still exists. Boundaries can be inferred by replay.

4. **Persistence is a property** — Any loop can be durable. Storage attaches at the vertex, not inside the spec.

---

## Minimal Example

One loop, one vertex, heartbeat facts:

```
Vertex receives Fact("heartbeat", ts, {})
  → Loop folds via Spec.reducer
  → Spec.boundary fires (every N beats)
  → Loop emits Tick("heartbeat", ts, {count: N})
  → Vertex stores/forwards the tick
```

That's the smallest live system: a loop that runs and periodically emits ticks.

---

## Mapping to Code

| Vocabulary | Current Code | Library |
|------------|--------------|---------|
| Peer | `Peer` | peers |
| Fact | `Fact` | facts |
| Spec | `Spec` | specs |
| Tick | `Tick` | ticks |
| Cell | `Cell` | cells |
| Loop | fold engine in `Vertex` | ticks |
| Vertex | `Vertex` | ticks |
| Surface | `Surface` | cells |

Vocabulary and code now use the same names.

---

## Examples at Scale

**Heartbeat**: Single loop, time-based boundary. Emits tick every N seconds.

**UI Session**: Loop folds keystrokes and clicks. Boundary on "session end" (quit, timeout). Tick captures session summary.

**CI Run**: Loop folds build events (start, test, deploy). Boundary on "pipeline complete". Tick captures pass/fail, duration, artifacts.

**Review Cycle**: Loop folds acks. Boundary when all items acked. Tick captures who acked what. Resets for next cycle.

Same atoms, same verbs, different scales.
