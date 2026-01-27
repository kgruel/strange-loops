# Architecture

Five atoms. No atom imports another. They compose at vertices.

## Atoms

| Atom | Structure | Question | Role |
|------|-----------|----------|------|
| **Peer** | name + horizon + potential | *who* | Who's in the loop. Horizon and potential are semantic constraints — temporal, depth, scope — not structural references. Delegation narrows both. |
| **Fact** | kind + ts + payload | *what* | What happened. An immutable observation. Facts go **in**. |
| **Tick** | name + ts + payload | *when* | When the loop completed a cycle. A frozen snapshot of folded state at a boundary. Ticks come **out**. |
| **Shape** | facets + folds + boundary + apply | *how* | How facts become state, and when a cycle completes. The contract at every boundary. Pure. |
| **Cell** | char + style | *why* | The expression layer. Where the loop touches human reality. First surface. |

## Topology

A **vertex** is where loops meet. Facts arrive at a vertex. The vertex
routes them to fold engines. Fold engines accumulate state through
shapes. When a boundary fires, the fold produces a Tick. The Tick
propagates to connected vertices. State projects through a lens to
cells. Cells emit facts back to vertices.

```
Vertex(name)
  A named point where loops meet. Standalone — does not import Peer.
  Discovers peers through facts (peer.join, peer.grant, peer.revoke).
  Authorization is event-sourced at the vertex level.

  Properties (runtime, not atom fields):
    store:    persistence backing (or ephemeral)
    exposed:  connectable by external peers
    location: where it runs (in-process, server, network)
```

A vertex learns about peers the same way it learns about everything
else — by folding facts. A peer joining a vertex is just a fact. A
peer's capabilities are just facts. The vertex's access rules are
just a shape.

### Peer semantics

Horizon and potential are semantic, not structural. A peer does not
hold a list of vertices. A vertex interprets peer semantics through
its access shape.

Horizon (what you can see):
- **Temporal**: "7 days back"
- **Depth**: "N hops from this vertex"
- **Scope**: "team:backend" or "project:homelab"
- **Full**: strong peer, no constraints

Potential (what you can do):
- **Emit**: what fact kinds you can produce
- **Delegate**: can you create child peers
- **Execute**: can you trigger side effects
- **Full**: strong peer, no constraints

Stance (direct, guided, delegated, automated, observing) is emergent
from the delegation hierarchy. The identity is the stance.

## Primitives

### peers — identity and capability

```
Peer(name, horizon, potential)
  delegate(child_name) -> Peer with narrower horizon + potential
```

### facts — observations

```
Fact(kind, ts, payload)
  Fact.of(kind, payload) -> stamps ts, returns frozen Fact
```

Everything enters the system as a Fact: raw observations, UI
interactions, lifecycle events, capability grants. Immutable,
append-only.

### shapes — contracts and transformation rules

```
Shape(name, about, input_facets, state_facets, folds, boundary)
  Facet(name, kind, optional)     what data looks like
  Fold(op, target, props)         how facts transform state
  Boundary(kind, reset)           when a cycle completes
  apply(state, payload) -> state  execute folds, pure
  initial_state() -> dict         zero-value from state_facets
```

Boundary declares which fact kind completes the cycle, and whether
state resets or carries across boundaries. A shape with no boundary
folds continuously — no cycle, no Tick produced.

### ticks — the respiratory system

```
Tick(name, ts, payload)           a loop's output at a boundary
```

A Tick is not an observation (that's a Fact). A Tick is derived — the
output of folding facts through a shape over a cycle. It's the frozen
snapshot that can safely enter another loop. Immutable time is what
makes loop intersection possible.

The ticks library provides the infrastructure:

```
Vertex          where loops meet — routes facts to fold engines
Store           abstract persistence (Memory, File, Postgres, ...)
Replay          re-enter stored facts into a loop
Connection      bridge between vertices
Fold engine     runs shapes against facts, produces Ticks
Consumer        protocol for vertex participation
```

### cells — the expression layer

```
Cell(char, style)                 atomic display unit
Block                             immutable rectangle of cells
Buffer                            2D cell grid, diffable
Lens                              render function: state -> Block
Layer                             modal input handling stack
Surface                           async main loop, keyboard, resize
Emit = Callable[[str, dict], None]  feedback boundary -> facts
```

Surface is bidirectional: renders state outward, emits interactions
inward as facts. The loop closes here.

## Data Flow

```
    +------------------------------------------------------------------+
    |  You (Peer)                                                      |
    |  horizon: what you see    potential: what you can do              |
    |                                                                  |
    v                                                                  |
  Fact(kind, ts, payload)                                              |
    |                                                                  |
    v                                                                  |
  Vertex                                                               |
    |  facts arrive here                                               |
    |  routes by kind to fold engines                                  |
    |  optionally backed by Store                                      |
    |  peer access folded from capability facts                        |
    |                                                                  |
    v                                                                  |
  Fold engine (Shape.apply)                                            |
    |  accumulates state from facts                                    |
    |  checks boundary after each fold                                 |
    |                                                                  |
    +--- boundary? ---> Tick(name, ts, payload)                        |
    |                       |                                          |
    |                       +---> propagates to connected vertices     |
    |                             (other loops receive as input)       |
    |                                                                  |
    v                                                                  |
  live state ---> Lens ---> Block ---> Surface ------------------------+
                                          |
                                    emits interactions
                                    as new Facts
```

Facts arrive. Ticks propagate. Interactions emit. The loop continues.

## How Loops Connect

A Tick produced at one vertex propagates to connected vertices. The
receiving vertex folds it like any other Fact. Because Ticks are
immutable, this is safe. No coordination, no locking, no conflict.

```
  Vertex A                        Vertex B
  +----------+                    +----------+
  | arrive   |                    | arrive   |
  | fold     |                    | fold     |
  | boundary --> Tick ----------> | (as Fact)|
  |          |   frozen state     | fold     |
  |          |                    | boundary --> Tick ---> ...
  +----------+                    +----------+
```

Vertices can be:
- **Ephemeral**: in-process, no persistence. Script loops.
- **Persistent**: backed by Store. Replay on reconnect.
- **Exposed**: connectable by external peers over network.

A vertex can supply facts from a variety of Ticks — combining outputs
from multiple loops at one meeting point. A peer's horizon and
potential determine which vertices they can observe and emit to.

Same architecture at every scale:
- **Local**: vertices in-process, Store = memory or JSONL
- **Homelab**: vertices on a server, Store = SQLite
- **Team**: same server, Store = Postgres, peers connect over network
- **Peer-to-peer**: each person exposes vertices, others connect directly

## Vocabulary

### The cycle — what happens inside a loop

```
arrive  ->  fold  ->  tick
```

Facts arrive at a vertex. The shape folds them into state. At a
boundary, the fold produces a Tick.

### The topology — how loops relate

```
propagate   Ticks propagate from one vertex to connected vertices
connect     a peer connects to a vertex
expose      a vertex is made available to external peers
route       a vertex routes facts by kind to fold engines
```

### The surface — how state becomes visible

```
project     live state projects through a lens to cells
emit        interactions emit as new facts back to a vertex
```

## Conventions

### Kind namespacing

Infrastructure facts auto-emitted by a lib are prefixed by origin:
`ui.key`, `ui.action`, `ui.resize` (from cells). Domain facts stay
bare: `container-health`, `deploy`, whatever makes sense in context.

### Kind -> Shape naming

Name your Shape after the primary Fact kind it folds. A Shape called
`"container-health"` folds Facts with `kind="container-health"`.
Legibility convention, not dispatch mechanism.

### Fact -> Shape bridge

Every fold engine folding Facts through a Shape needs a thin extraction
function (~3 lines) at the composition point. This lives in the
integration layer because it touches both Fact and Shape, and the
atoms don't import each other.

### Capability-as-Fact

Peer access at a vertex is event-sourced. Grants and revocations are
facts. The vertex folds them into current access state through an
access shape. The audit trail is free.

```
Fact(kind="peer.join",    payload={name: "alice", horizon: ..., potential: ...})
Fact(kind="peer.grant",   payload={name: "alice", access: "observe"})
Fact(kind="peer.revoke",  payload={name: "bob",   access: "emit"})
```
