# VOCABULARY

Canonical definitions for the loops system. One page, no ambiguity.

---

## The One-Liner

**Facts flow into Vertices. Vertices fold Facts through Specs. Boundaries emit Ticks. Ticks flow onward as Facts. The loop closes.**

---

## Concepts vs Types

Some ideas are fundamental to the model but don't need their own type. They're just strings or fields that pervade everything.

### Concepts (lowercase, no type)

| Concept | Where it lives | What it is |
|---------|----------------|------------|
| **observer** | `Fact.observer` | Who produced this observation. A string. |
| **kind** | `Fact.kind` | Routing key. What type of observation. A string. |
| **origin** | `Tick.origin` | Which vertex produced this tick. A string. |
| **boundary** | `Spec.boundary` | When a cycle completes. A kind that triggers. |
| **fidelity** | query/render time | Traversal depth into a tick's period. |

These concepts are first-class in the model but don't require dedicated types. They may grow structure later if strings aren't enough — but we'll see when we get there.

### Atoms (types, immutable data)

| Atom | Structure | Question |
|------|-----------|----------|
| **Fact** | kind + ts + payload + observer | What happened? Who saw it? |
| **Spec** | fields + folds + boundary | How does state accumulate? |
| **Tick** | name + ts + payload + origin | What did a period become? |

Three atoms. Everything else is composition or runtime.

---

## Two Libraries

### data

What data looks like, how to get it, how to shape it.

| Type | Purpose |
|------|---------|
| **Fact** | The observation record |
| **Spec** | The contract (fields, folds, boundary) |
| **Source** | Ingress: run command → format → parse → facts |
| **Parse ops** | Shaping: Split, Pick, Rename, Transform, Coerce, Skip |
| **Fold ops** | Transform: Latest, Count, Sum, Collect, Upsert, TopN, Min, Max |

Validation lives here too — static checking that parse output matches spec input.

### vertex

How it runs, where state lives, when boundaries fire.

| Type | Purpose |
|------|---------|
| **Vertex** | Receives facts, routes by kind, manages loops |
| **Loop** | Executes Spec.apply, tracks state between boundaries |
| **Store** | Persistence: append, query by time range, replay |
| **Grant** | Policy: horizon (can see) + potential (can emit) by observer |

### cells (separate)

The terminal surface. Renders state outward, emits input as facts.

| Type | Purpose |
|------|---------|
| **Cell** | Atomic render unit: char + style |
| **Surface** | Composition: state → cells, input → facts |

---

## Verbs

| Concept/Type | Verbs |
|--------------|-------|
| Fact | observe, append |
| Spec | declare, apply, validate |
| Tick | emit, traverse |
| Source | run, parse, emit |
| Vertex | receive, route, store |
| Loop | fold, fire |
| Store | append, query, replay |
| Grant | lookup, restrict |
| Surface | render, emit |

---

## Composition Rules

1. **One-way flow** — Facts flow in, accumulate, ticks flow out. No rollback. Failures are just more facts.

2. **Tick-to-Fact bridging** — A Tick routed to another Vertex becomes a Fact. The origin becomes the observer.

3. **Observer is intrinsic** — Every Fact carries its observer. No late-binding.

4. **Policy is optional** — Grant attaches at Vertex, not Fact. Simple setups skip it.

5. **Persistence is a property** — Store attaches at Vertex. Any loop can be durable.

6. **Fidelity is traversal** — A Tick is a handle to a period. Minimal fidelity: just payload. Full fidelity: all facts in the period, recursively.

---

## Minimal Example

```
Source runs "df -h"
  → parses lines via [Split, Pick, Rename]
  → emits Fact(kind="disk", observer="disk-monitor", payload={...})

Vertex receives
  → routes to Loop registered for "disk"
  → Loop calls Spec.apply(state, payload)
  → state accumulates

Boundary fact arrives (kind="disk.complete")
  → Loop fires
  → Tick(name="disk", origin="my-vertex", payload={accumulated state})

Tick flows to next Vertex as Fact
  → observer = "my-vertex"
  → kind = "disk" (or "disk.tick")
  → payload = accumulated state

Loop closes.
```

---

## Examples at Scale

**Auth failure:** 9 attempt facts, timer facts, threshold crossed → Tick `{locked: true}`. No exception handling. Just accumulation.

**Deploy:** Build loop ticks, test loop ticks, push loop ticks → deploy Tick. At full fidelity, descend into each phase.

**Board meeting:** Month of facts from various loops → meeting loop → board observes, discusses, decides → meeting Tick. The month is in there.

**Grandma's Birthday:** Year of family facts → birthday Tick `{celebrated: true}`. Full fidelity has the whole year.

Same atoms, same verbs, different scales.

---

## Mapping to Code

| Vocabulary | Code | Library |
|------------|------|---------|
| Fact | `Fact` | data (currently: facts) |
| Spec | `Spec` | data (currently: specs) |
| Tick | `Tick` | vertex (currently: ticks) |
| Source | `Source` | data (currently: sources) |
| Parse ops | `Split`, `Pick`, etc. | data (currently: specs.parse) |
| Fold ops | `Latest`, `Count`, etc. | data (currently: specs.fold) |
| Vertex | `Vertex` | vertex (currently: ticks) |
| Loop | `Loop` | vertex (currently: ticks) |
| Store | `Store` | vertex (currently: ticks) |
| Grant | `Grant` | vertex (currently: peers) |
| Cell | `Cell` | cells |
| Surface | `Surface` | cells |

Library consolidation pending: facts + specs + sources → data, ticks + peers → vertex.
