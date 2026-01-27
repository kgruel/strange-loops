# Architecture Journey

How the current architecture emerged. Captures the conceptual evolution
across multiple sessions so the reasoning is recoverable.

## Starting point (2026-01-26, prior session)

Five atoms, five libraries, each answering a question:

| Atom | Question | Original structure |
|------|----------|--------------------|
| Peer | who | name + scope |
| Fact | what | kind + ts + payload |
| Tick | when | ts + payload |
| Shape | how | facets + folds + apply |
| Cell | where | char + style |

The ticks library held Tick (the atom) plus infrastructure: Stream,
Projection, EventStore, FileWriter, Tailer, Forward. The Tick was a
frozen temporal snapshot — `Tick(ts: datetime, payload: T)`.

Key insight from that session: **immutable time is what makes loop
intersection possible.** Facts can't be mutated, so a loop's output
can safely enter another loop. The append-only nature of facts IS the
concurrency model.

The session also produced: Peer refactored from `scope` to `horizon +
potential`, capability-as-fact demonstrated, "stream" vocabulary
questioned, daemon/mill primitive built.

## The plumbing question (2026-01-27)

Started from HANDOFF.md open question #4: is "ticks" still the right
name? The Tick type might collapse into Fact. The library is about how
loops operate, not about "ticks" per se.

### Tick collapse attempt

Proposed: Tick is just a boundary Fact. Move it into facts. What's left
in the ticks library is pure plumbing — Stream, Projection, Store.

This led to asking: **what IS that plumbing?** Explored renaming:
- Stream → Circulate
- Projection → Fold
- EventStore → Store (abstract)
- Tailer → Replay
- Forward → Connection

### Identifying the primitives

Built up from first principles. What does the infrastructure need?

1. **Fold** — the irreducible operation. Facts in, state out.
2. **Circulate** — route facts to fold engines (fan-out).
3. **Boundary** — when a cycle completes. The missing primitive.
4. **Emit** — at boundary, snapshot state → produce output.
5. **Persist** — append facts to durable storage.
6. **Replay** — re-enter stored facts.
7. **Lifecycle** — start, run, stop.
8. **Nesting** — inner/outer loops.
9. **Connection** — loops sharing outputs.

Key dissolution: **lifecycle is just facts** (start/stop are
observations). **Nesting is just topology** (inner loop's output enters
outer loop). Both dissolved into existing atoms rather than needing new
primitives.

**Boundary moved to Shape.** Shape already defines what data looks like
and how it transforms. "When is a cycle complete?" is part of the
contract. Shape gained `Boundary(kind, reset)`.

### Where does the plumbing live?

Explored naming: flow, mill, ply, spin, loops. The collision question:
if the library is "loops," the monorepo can't also be "loops."

Explored Loop-as-atom: what if Loop replaces Tick? A Loop would be
`Loop(name, receives, emits, boundary)` — a port specification. But
boundary had moved to Shape. And receives/emits is wiring, not data.
Loop felt too thin or too overloaded.

### The intersection concept

Key reframe: **it's not a stream you tap into — it's an intersection
of loops.** An intersection is a place, not a pipe. Properties:
- Persistent or ephemeral
- Backed by whatever Store
- Exposable to external peers
- Gated by peer potential

This replaced Stream as the core concept. Stream implied A→B pipeline
flow. Intersection is where loops meet — bidirectional, multi-party.

### Vertex

From intersection to vertex. Graph theory vocabulary: loops are cycles,
vertices are where cycles meet. The vertex is where facts converge and
Ticks propagate.

Explored vertex as a sixth atom. Decided against — vertex is topology
infrastructure, not a data type like the other atoms. It lives in the
ticks library as the orchestration primitive.

### Peer-vertex relationship

Initial instinct: peer.horizon = list of vertices. Rejected — horizon
is semantic (temporal, depth, scope), not structural. A peer doesn't
know what a vertex is.

Resolution: the vertex discovers peers through facts. `peer.join`,
`peer.grant`, `peer.revoke` are facts that arrive at a vertex and get
folded into access state through an access shape. Authorization is
event-sourced. No atom imports another.

## The Tick reclamation (2026-01-27, later)

A comparative analysis (ChatGPT deep research) surveyed Loops against
event sourcing, stream processing, DES, FRP, actor model, and control
systems. Every comparison identified Tick as a key differentiator:

- Tick as semantic temporal grouping (not just a window or timestamp)
- Tick as the boundary handoff that enables loop intersection
- Tick as what makes time first-class rather than metadata
- "A tick is a loop's exhale"

The analysis made clear: collapsing Tick into Fact would make the
system look like event sourcing with extra steps. Tick IS the concept
that distinguishes this architecture. It's not infrastructure — it's
the output. The infrastructure produces Ticks.

### What we got right vs wrong

**Right:**
- Boundary belongs on Shape
- Intersection (vertex) replaces Stream
- Store is abstract, backing is pluggable
- Lifecycle is facts
- Nesting is topology
- Peer-vertex connection is through facts

**Wrong:**
- Collapsing Tick into Fact. A Fact is an observation (raw input). A
  Tick is derived output (folded state at a boundary). These are
  different: facts go in, ticks come out. The type encodes direction.

### Tick evolved

Tick gained `name` — which loop produced this Tick:

```
Tick(name, ts, payload)    # was: Tick(ts, payload)
```

The name connects the Tick to its origin. A Tick with `name="homelab"`
came from the homelab loop. When it enters another vertex, it arrives
with provenance.

## Current state

See ARCHITECTURE.md for the definitive overview.

Five atoms: Peer, Fact, Tick, Shape, Cell.
Topology concept: Vertex (where loops meet, lives in ticks library).
New on Shape: Boundary(kind, reset).
Vocabulary: arrive, fold, tick, propagate, project, emit.

### What needs building

- Shape: add Boundary type and boundary field
- Peer: formalize horizon + potential (replacing scope)
- Tick: add name field
- Ticks lib: add Vertex primitive, abstract Store, kind-based routing
- Integration: update experiments to use new primitives
- Documentation: update per-lib CLAUDE.md and HANDOFF.md files
