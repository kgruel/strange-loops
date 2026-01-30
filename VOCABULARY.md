# VOCABULARY

Canonical definitions for the loops system. One page, no ambiguity.

---

## The One-Liner

**Observers produce Facts. Facts enter Loops via Vertices. Loops fold Facts through Specs and emit Ticks at boundaries. Vertices stamp origin and route Ticks onward.**

---

## Atoms

Atoms are immutable, independent, and compose only at integration points.

| Atom | Structure | Question | Meaning |
|------|-----------|----------|---------|
| **Observer** | name | *who* | Identity. Who produced this observation. Just a name. |
| **Fact** | kind + ts + payload + observer | *what* | Immutable observation. Carries its observer intrinsically. Append-only. |
| **Spec** | facets + folds + boundary | *how* | Loop contract. Declares input/state shape, fold rules, and boundary semantics. |
| **Tick** | name + ts + payload + origin | *when* | Boundary artifact. Frozen snapshot of folded state. Origin = producing vertex. |
| **Cell** | char + style | *(render)* | Atomic unit of output. Base of surfaces. |

---

## Runtime Concepts

Not atoms — the execution layer where atoms meet.

### Loop

A running Spec. Facts in, state accumulates, Ticks out.

1. Receives **Fact** payloads
2. Folds via **Spec.apply**
3. Checks **Spec.boundary**
4. Emits **Tick** when boundary fires
5. Resets or carries state, continues

Loops are self-contained. They don't know about observers, policy, or routing — they just fold and fire.

### Vertex

Where loops meet. The observer at the intersection.

- **Receives** Facts (sees observer, kind, payload)
- **Gates** optionally via policy (Grant lookup by observer)
- **Routes** to Loops by kind
- **Stores** optionally (persistence is a property)
- **Stamps** origin on Ticks when Loops fire
- **Forwards** Ticks to next vertex (as Facts, with self as observer)

When a Tick crosses to another Vertex, it becomes a Fact. The producing Vertex is the observer.

### Grant

Optional policy. Looked up by observer name at the Vertex.

- **horizon**: what this observer can see
- **potential**: what this observer can emit

Simple setups skip it. Network/multi-tenant setups enforce it.

### Surface

Interactive renderer that closes the loop:
- **Render**: state → Cells (via Blocks, Buffers)
- **Input**: keyboard/mouse → Facts (`ui.key`, `ui.click`)

State goes out as cells. Interactions come back as facts. Surface emits Facts with its user as observer.

### Source

An adapter that produces Facts from external input. Infrastructure, not an atom.

- **Adapters**: command, feed, endpoint, file, timer, etc.
- **Interface**: `vertex.ingest(kind, payload, observer)`
- **Responsibility**: translate external events into Facts with proper observer attribution

---

## Allowed Verbs

| Concept | Verbs |
|---------|-------|
| Observer | name (identity only) |
| Fact | observe, append |
| Spec | declare, apply |
| Tick | emit, route, store |
| Loop | receive, fold, fire |
| Vertex | receive, gate, route, stamp, store, forward |
| Grant | lookup, restrict |
| Surface | render, emit |
| Source | ingest, adapt |
| Cell | paint |

---

## Composition Rules

1. **No shared mutable state** — Loops intersect only by exchanging immutable artifacts.

2. **Tick-to-Fact bridging** — A Tick routed to another Vertex becomes a Fact. The producing Vertex is the observer. The receiving Vertex sees it as any other Fact.

3. **Observer is intrinsic** — Every Fact carries its observer. No late-binding, no payload smuggling.

4. **Policy is optional** — Grant (horizon + potential) attaches at the Vertex, not the Fact. Simple setups skip it entirely.

5. **Dirty close is normal** — If a loop doesn't hit its boundary (crash, disconnect), history still exists. Boundaries can be inferred by replay.

6. **Persistence is a property** — Any loop can be durable. Storage attaches at the vertex, not inside the spec.

---

## Minimal Example

One loop, one vertex, heartbeat facts:

```
Fact("heartbeat", ts, {}, observer="timer")
  → Vertex receives
  → routes to heartbeat Loop
  → Loop folds via Spec.apply
  → Spec.boundary fires (every N beats)
  → Loop emits Tick("heartbeat", ts, {count: N})
  → Vertex stamps origin="heartbeat-vertex"
  → Vertex forwards as Fact to next vertex (observer="heartbeat-vertex")
```

That's the smallest live system: an observer, a fact, a loop, a tick.

---

## Mapping to Code

| Vocabulary | Current Code | Library | Status |
|------------|--------------|---------|--------|
| Observer | (string) | — | Fact needs `observer` field |
| Fact | `Fact` | facts | Needs `observer` field |
| Spec | `Spec` | specs | Done |
| Tick | `Tick` | ticks | Has `origin` |
| Cell | `Cell` | cells | Done |
| Loop | `Loop` | ticks | Done |
| Vertex | `Vertex` | ticks | Needs origin stamping, observer-aware receive |
| Grant | — | — | New concept (optional policy) |
| Surface | `Surface` | cells | Done |

`Peer` in peers lib becomes a convenience bundle (Observer + Grant), not a core atom.

---

## Examples at Scale

**Heartbeat**: Timer observer emits health facts. Single loop, time-based boundary. Vertex forwards ticks to monitoring.

**UI Session**: User observer (alice) emits keystrokes and clicks. Loop folds them. Boundary on "session end". Tick captures session summary.

**CI Run**: CI system observer emits build events. Loop folds (start, test, deploy). Boundary on "pipeline complete". Tick captures pass/fail.

**Review Cycle**: Multiple observers (alice, bob) emit acks. Loop folds them. Boundary when all items acked. Tick captures who acked what.

**Network**: Vertex A fires tick → becomes Fact with observer="vertex-a" → Vertex B receives, routes to its loops.

Same atoms, same verbs, different scales.
