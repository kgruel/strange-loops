# STRANGE LOOPS

A system for focusing attention. The mechanism is data. The purpose is focus.

## The Truths

**Time is fundamental.** The past happened. Facts are observations of what occurred.
Events have a total order. You are always in the present, observing an ordered past.

**The observer is first-class.** Facts exist because someone observed them. Without
observation, nothing is recorded. The act of observing is itself observable —
observations about observations are still just facts.

**Everything is loops.** Observations flow in, accumulate into state, boundaries
resolve, ticks flow out. The end connects to the beginning. There are no endpoints.

**Everything flows one direction.** Failures, conditionals, nested spans — they're
all just more facts. No special handling. No rollback. Just accumulation.

A single observer in a loop is just a loop. It becomes strange when there are
collaborators — multiple observers focusing attention on the same data, through
their own lenses, whose observations feed back in and shift what each other sees.
The strangeness is collaboration.

## The Atoms

Three shapes. Everything else is composition or configuration.

```
Fact    what happened           kind + ts + payload + observer
Spec    how attention focuses   fields + folds + boundary
Tick    what a period became    name + ts + payload + origin
```

**Fact** — A single observation. Something happened, someone cared enough to record
it. The `kind` says what category of attention it belongs to. The `ts` is when. The
`payload` is what. The `observer` is who. Facts are immutable.

**Spec** — The contract for focusing. Declares what matters (fields), how it
accumulates (folds), and when the accumulation resolves into something worth
looking at (boundary). Pure function: state + observation → new state.

**Tick** — A resolved period of attention. When a boundary fires, accumulated state
snapshots into a Tick. The `payload` is what the period became. At full fidelity,
you can traverse into the contributing observations — some are themselves Ticks from
other loops. Depth emerges from ticks-as-facts flowing into other loops.

## The Properties

Four constraints. Any implementation must satisfy these.

**Immutable.** Facts don't change. Ticks are frozen. State is derived, never
stored directly — replay the facts through the folds to reconstruct it.
Correction happens by emitting new facts, not by modifying old ones.

**Append-only.** New observations accumulate. Nothing is deleted. The past
is the past.

**Unidirectional.** Facts flow in, state accumulates, ticks flow out. No
cycles in the data flow. The loop closes through the observer, not through
the mechanism.

**Observer-attributed.** Every fact carries who observed it. A deployment
observed by a human carries different weight than one observed by a cron job.
The identity is part of the observation's meaning.

## The Pattern

One pattern executes the model.

**Vertex** — Where the loop crosses itself. A vertex receives facts, routes
them by kind, accumulates state through folds, and produces ticks at boundaries.
Ticks flow out as facts into other vertices — or back into the same one.

A vertex manages one or more **loops**, each focusing on a different kind of
observation. A vertex can be durable (observations persist, state is derived by
replay) or ephemeral. A vertex can ingest (a source runs a command, parses output,
emits observations). These are capabilities, not concepts.

```
Observation
      │
      ▼
   Vertex ─── accumulates by kind ─── boundary? ─── Tick
      ▲                                                │
      │                                                ▼
      └──── observer acts ──── observer sees ──── Lens on state
```

The loop closes through the observer. An observer sees state through a **lens**
(a perspective on the vertex at some fidelity level) and acts by emitting new
facts. This is not rendering infrastructure — it is how attention flows back in.

## Fidelity and Depth

A Tick is a handle to a resolved period.

**Minimal fidelity:** Just the resolved state. `{status: "success", count: 47}`

**Full fidelity:** The resolved state, plus every contributing observation, plus
recursive traversal into any observations that are themselves Ticks from other
loops.

At different scales:

- **Auth failure:** 9 attempts, timer ticks, threshold → Tick `{locked: true}`.
  No exception handling. Just observations that accumulated to locked state.

- **Deploy:** Build tick + test tick + push tick → Tick `{status: "success"}`.
  At full fidelity, descend into each phase.

- **Board meeting:** Month of project observations, incident ticks → meeting Tick.
  The month collapses into a few hours where new observers focus and decide.

The hierarchy isn't designed. It emerges from ticks-as-facts flowing into other
loops. Depth is attention at different timescales.

## Lenses

A **lens** is how the loop sees itself. A function from vertex state to a view
at a given fidelity level.

Lenses are perspectives — the same state viewed at different depths, for
different purposes, by different observers. One observer sees the deer. Another
sees the pattern in the leaf movement. Same data, different focus. The vertex
doesn't know or care how it's being observed.

An **action** is the return path: an observation emitted back into the vertex.
Lenses focus outward. Actions feed observations inward. Together they close the
loop. Any vertex can be observed through a minimal lens (raw state). Richer
lenses — fidelity levels, styled rendering, interactive actions — are
configuration, not architecture.

## Collaboration

The strangeness is having collaborators.

Each observer carries an identity — a string that encodes their stance. A human
observing directly, an agent delegated by that human, an automated process
running on a schedule. The identity is part of every observation's meaning.

**Horizon** — what an observer can focus on. Their field of view.
**Potential** — what observations an observer can emit. Their ability to direct
others' attention.

These aren't access control. They're the shape of each observer's participation
in the loop. Delegation narrows the shape — you can give a collaborator a
focused view and a constrained voice. The observer hierarchy is naming, not
infrastructure.

Multiple observers on the same vertex, each with their own lens, each emitting
observations that shift what the others see. That's the strange loop. The system
focuses attention, and the attention reshapes the system.

## What Dissolved

Building this system has been strange. Concepts get introduced, explored, and
collapse back into what was already there. The system resists elaboration.

| Concept | Dissolved into | Why |
|---------|---------------|-----|
| Sink | Fold state | Loops have no terminals |
| Witness | Observer + Vertex | A witness is just an observer whose job is to emit |
| Memory | Boundary-less fold | Silent accumulation is just a fold that never ticks |
| Surface | Lens + Action | Not a separate layer — just perspective and observation |
| Application | Vertex config + Lenses | An app is a perspective, not a separate thing |

Three atoms remain: Fact, Spec, Tick. One pattern: the vertex. The strangeness
is that this table keeps growing but the model doesn't.

---

*A system for focusing attention across depth and breadth, at the fidelity
that matters, for the observers who are looking. The strange part is that
there's more than one of you.*
