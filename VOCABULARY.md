# VOCABULARY

Canonical definitions for the loops system. One page, no ambiguity.

---

## The Bet

**The cycle is the unit of computation.**

---

## The Frame

Decide what to pay attention to, how to think about it, and when to conclude.
Each conclusion informs the next cycle. You set the rhythm.

A **loop** is one complete cycle: observe, accumulate, conclude. Loops run
continuously — your context streams in as observations, accumulates according
to rules you declared, and produces conclusions on your schedule. Those
conclusions re-enter the stream as new observations. The loop closes.

---

## Atoms

Three immutable data types. Everything else is composition or runtime.

| Atom | Structure | Question | Enforces |
|------|-----------|----------|----------|
| **Fact** | kind + ts + payload + observer + origin | What happened? Who saw it? Where from? | Observer is intrinsic. Origin traces derivation provenance — empty for external observations, non-empty for derived facts from tick-to-fact bridging. |
| **Spec** | fields + folds + boundary | How does state accumulate? | Contract is frozen at declaration. Folds, boundaries, and schedule are fixed before observations arrive. |
| **Tick** | name + ts + payload + origin | What did a period become? | Output only through fold→boundary→emit. You cannot fabricate a conclusion without accumulation. A Tick is a loop's exhale. |

**Why three and not two?** Fact and Tick are structurally similar (both carry
timestamp + payload + an identity field). But collapsing them erases the
loop. Facts flow IN — raw observations. Ticks flow OUT — accumulated
conclusions. That directionality is what makes a loop a loop. Without Tick as
a distinct type, you have event sourcing, not loops. (Tried merging them
Jan 27, reversed it — the distinction is the architectural differentiator.)

**Type-level amnesia, metadata-level memory.** When a Tick crosses to another
loop, it becomes a Fact. The type system forgets it was ever a conclusion —
it's just another observation now. But provenance is preserved: the Tick's
`origin` carries through to `Fact.origin`, and the producing vertex becomes
the `observer`. The system treats all inputs uniformly while keeping
traceability. External observations have `origin=""`. Derived facts carry
the producing vertex/loop name — enabling self-feeding detection (Rule #7).

### Concepts (lowercase, no dedicated type)

| Concept | Where it lives | What it is |
|---------|----------------|------------|
| **loop** | the system's core pattern | One complete cycle: observe, accumulate, conclude. The composition of Fact + Spec + Tick. The thing the system is named after. |
| **observer** | `Fact.observer` | Who produced this observation. A string. |
| **kind** | `Fact.kind` | Routing key. What type of observation. A string. |
| **origin** | `Tick.origin`, `Fact.origin` | Which loop produced this conclusion/derived fact. A string. Empty on external observations. |
| **boundary** | `Spec.boundary` | When a cycle completes. A kind that triggers emission. |

---

## Rules

System-level invariants that emerge from atoms interacting.

1. **One-way flow** — Facts flow in, accumulate, Ticks flow out. No rollback. Failures are just more facts.

2. **Tick-to-Fact bridging** — A Tick entering another loop becomes a Fact. The origin becomes the observer. The type forgets; the metadata remembers.

3. **Observer is intrinsic** — Every Fact carries its observer. No late-binding. You always know who saw it.

4. **Policy is optional** — Grant attaches at Vertex, not Fact. Simple setups skip it.

5. **Persistence is a property** — Store attaches at Vertex. Any loop can be durable.

6. **Zoom is the depth control** — A Tick is a handle to a period. At minimal zoom: just the payload. At full zoom: all facts in the period, recursively. The lens function `(data, zoom, width) → Block` renders at any depth.

7. **Self-feeding is the fundamental risk** — When conclusions feed back as observations, the system can amplify its own output. Well-tuned specs produce refinement — each cycle sharpens. Poorly-tuned specs produce runaway self-reference. This is the difference between meditation and hallucination. Design for it.

---

## Four Libraries (2+2)

Two libraries define the core model. Two more serve the surface — how you declare loops and how you see them.

### Core Model

**atoms** — What the data looks like, how to get it, how to shape it.

| Type | Purpose |
|------|---------|
| **Fact** | The observation record |
| **Spec** | The contract (fields, folds, boundary) |
| **Source** | Ingress: run command → format → parse → facts |
| **Parse ops** | Shaping: Split, Pick, Rename, Transform, Coerce, Skip |
| **Fold ops** | Accumulation: Latest, Count, Sum, Collect, Upsert, TopN, Min, Max |

Validation lives here too — static checking that parse output matches spec input.

**engine** — How it runs, where state lives, when boundaries fire.

| Type | Purpose |
|------|---------|
| **Vertex** | Receives facts, routes by kind, manages loops |
| **Loop** | Executes Spec.apply, tracks state between boundaries |
| **Tick** | The conclusion record (boundary output) |
| **Store** | Persistence: append, query by time range, replay |
| **Grant** | Policy: horizon (can see) + potential (can emit) by observer |

### Surface Layers

**lang** — The declaration language. Compiles `.loop` and `.vertex` files down to Source + Spec + Vertex wiring. How you declare what to pay attention to without writing Python.

**cells** — The terminal surface. Renders state outward, emits input as facts.

| Type | Purpose |
|------|---------|
| **Cell** | Atomic render unit: char + style |
| **Block** | Render primitive: text + style + layout |
| **Surface** | Composition: state → cells, input → facts |
| **Zoom** | Enum controlling render depth (MINIMAL → SUMMARY → DETAILED → FULL) |
| **Lens** | `(data, zoom, width) → Block` — renders at any depth |

### The CLI

**loops** composes all four libraries into user-facing commands: `validate`, `test`, `run`, `compile`, `start`, `store`. The libraries stand alone. Loops is the interface.

---

## Examples

**Minimal:**
```
Source runs "df -h"
  → parses lines via [Split, Pick, Rename]
  → emits Fact(kind="disk", observer="disk-monitor", payload={...})

Loop receives, folds via Spec
  → state accumulates

Boundary fact arrives (kind="disk.complete")
  → Loop fires
  → Tick(name="disk", origin="my-vertex", payload={accumulated state})

Tick enters the next loop as a Fact
  → observer = "my-vertex"
  → kind = "disk.tick"
  → payload = accumulated state

Loop closes.
```

**At scale — same atoms, same rules, different rhythms:**

- **Auth failure:** 9 attempt facts → threshold crossed → Tick `{locked: true}`. No exception handling. Just accumulation.
- **Deploy:** Build ticks, test ticks, push ticks → deploy Tick. Zoom in to see each phase.
- **Board meeting:** Month of facts from various loops → meeting Tick. The month is in there.
- **Personal intelligence:** RSS feeds, HN likes, Reddit upvotes → daily Tick of what caught your attention. Yesterday's conclusions shape what you notice today.

---

## Resolved Dissolutions

Decisions that were explored, tested, and settled. Guardrails against re-litigation.

**Tick → Fact merge (Jan 27, reversed).** Tried collapsing Tick into "a Fact
with a special kind." Both parties accepted, then reversed after analysis
showed Tick is the architectural differentiator. "Tick is a loop's exhale" —
without it, you can't see the loop. Facts go in, Ticks come out. Same type
erases the directionality. Decided: three atoms.

**Fidelity as standalone concept (dissolved Feb 7).** The observation that the
same data should render at different commitment levels is real — but it's
already what lenses do when given a zoom parameter. `(data, zoom, width) →
Block` is the signature. Fidelity dissolved into lens + zoom. The concept
guided UX design, now absorbed into machinery.

**Store viewer as cells widget (dissolved Feb 7).** The store viewer is a tool,
not a widget. Queries are substance, TUI is ergonomics. Graduated to
`apps/loops/` as the `loops store` subcommand.

**Multi-store topology (not needed, Feb 7).** Single store is correct.
Tick-to-fact conversion embeds upstream provenance. One atmosphere.

**Live vs stored viewing (dissolved Feb 7).** The store (SQLite) is the boundary
between producer and consumer. A live loop writes to the store; the viewer
reads from it. The only difference is whether new rows arrive while you're
looking. No "live mode" — just a refresh loop.

---

## Revision History

- **2026-02-08:** Full revision. Restructured as Bet → Frame → Atoms →
  Rules → Libraries → Dissolutions. Elevated "loop" to first-class concept.
  Added enforcements to atoms table. Named self-feeding risk. Library
  renames: data → atoms, dsl → lang, vertex → engine. Dropped code mapping
  table and verbs table (code is the source of truth for those). Removed
  stale fidelity references. Added personal intelligence example.
- **2026-02-07:** Dissolved fidelity into lens + zoom. Flagged vocabulary
  discussion pending.
