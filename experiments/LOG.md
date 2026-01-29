# Experiment Log

Insights from building. Each entry captures what emerged — patterns that
weren't planned but fell out of the primitives when composed.

## Open threads

Carry forward across sessions. Resolve or refine as experiments answer them.

- ~~**Temporal boundaries + interaction**~~: Resolved. review.py: the peer's
  acks accumulate until all containers are acked, the composition layer sends
  a sentinel, boundary fires, Tick produced, state resets. The boundary is
  something you *cause*. Temporal structure from participation.
- ~~**Multiple simultaneous peers**~~: Resolved. simultaneous_peers.py: shared
  focus breaks with concurrent peers (last-write-wins). Solution: per-peer
  focus (`focus.{peer}`). Observer state belongs to observer.
- **Meta-as-loop**: Peer switching is currently meta (outside the loop). When
  does meta-state need to enter a loop? Signal: when it needs to be shared,
  persisted, or folded.
- ~~**Store persistence**~~: Resolved. review.py logs facts/ticks to JSONL,
  replays on startup to reconstruct state. Persistence is a composition-layer
  property, not a primitive change.
- ~~**Lens as first-class concept**~~: Explored. review_lens.py: Lens = zoom +
  scope. Pairs with Projection (write-side vs read-side). Leaving conceptual —
  placement TBD.
- ~~**Network boundary**~~: Resolved. network_boundary_extended.py explores all
  four open questions. Pattern: network concerns become facts that fold. Policy
  is composition-layer. The primitives don't change.

---

## Session: observe.py — closing the feedback loop

### What was built

`observe.py`: user interactions and external observations enter the same
Vertex through the same `receive()`. Three peers (operator, monitor, debug).
Debug panel slides in with full `vertex.receive()` trace, horizon-gated.

### What emerged

**Debug data flows through the loop, not alongside it.**

Traditional debug logging is a parallel channel — `console.log`, log levels,
separate tools. In the loop model, the data is already flowing through the
vertex. `_wrap_receive()` at the composition layer (5 lines, no lib changes)
instruments the entire event stream. No debug framework, no log levels, no
separate channel.

*Correction (review.py session)*: the original insight said debug is a horizon
concern. It's not — it's a **lens** concern. Horizon gates what data domains
you can see (containers, kinds). A debug panel controls rendering depth — how
you view the data that's already visible to you. Any peer can toggle debug;
it's a presentation mode, not an access boundary. The None=unrestricted Peer
model made this category error visible: if the root peer sees everything,
gating debug through horizon is incoherent.

**Meta-actions have a clean boundary.**

`j/k/enter` go through the bridge to `vertex.receive()` — they're in the loop.
`tab/d/q` mutate observer configuration directly — they're meta.

Test is binary: does it go through `receive()`?

The meta-level is the observation apparatus, not the thing being observed.
Which peer is active, whether debug is open, terminal size — these configure
how you observe the loop, not what the loop contains.

The model doesn't prevent meta from becoming a loop (peer switching could be
Facts in a meta-vertex). But it doesn't require it. The boundary is a
composition-layer choice. Signal for promotion: when meta-state needs to be
shared, persisted, or folded across observers.

**The composition layer is thin because there's one abstraction.**

~50 lines of wiring. One interface (`receive(kind, payload)`), one gate
(`if kind not in potential: return`), one registration pattern
(`for shape, fold in SHAPES: v.register(...)`).

One data path: Fact -> Vertex -> Fold -> State -> Render. Not a graph. The
composition layer doesn't manage complexity because the architecture doesn't
create complexity. The glue is a for loop and an if statement.

Inverse of frameworks where glue is the hard part (DI, event buses, middleware).
Here complexity lives in the primitives (fold logic, render, peer constraints),
not in the wiring.

**All three are the same insight.** The loop is the only abstraction. Debug
isn't separate because the loop already has the data. Meta is cleanly outside
because the loop has a sharp boundary. Composition is thin because there's
one thing to compose.

### Patterns confirmed

| Pattern | Evidence |
|---------|----------|
| Vertex as sole integration point | External timer, user keypress, infrastructure event — all `receive()` |
| Fold origin-blindness | Health fold doesn't know if the fact came from a timer or a test |
| Peer constrains the loop | potential gates emission, horizon gates rendering — two fields |
| Shape drives wiring | Composition reads shape.name, shape.initial_state() — no interpretation |
| Infrastructure vs domain = wiring, not type | Same `receive()`, different call sites |

### Prior experiments (context)

**fleet.py**: Three-level vertex hierarchy. Facts fold into state, state
snapshots into Ticks, Ticks cascade. Proves temporal nesting — same primitive
at every level.

**boundary.py**: Data fires boundaries, not external clocks. Three boundary
semantics (reset, self-complete, carry) from the same mechanism. Proves
boundaries are a property of the data, not the infrastructure.

---

## Session: review.py — peer actions trigger boundaries

### What was built

`review.py`: two loops through one vertex, different boundary drivers.
Health ticks at timer cadence (passive, external). Review ticks when the
peer acks all containers (active, peer-driven). The composition layer checks
after each ack: "all containers acked?" → sends `review.complete` sentinel →
boundary fires → Tick → ack state resets → next cycle.

Also: Peer model changed to `None = unrestricted`. `frozenset[str] | None`
where `None` means the peer has no constraints on that dimension. Constraints
emerge through `delegate()`, not through upfront `grant()`.

### What emerged

**The boundary is something you cause.**

In boundary.py, boundaries fire from data — external events trigger sentinels.
In review.py, the peer's own actions accumulate until they trigger the boundary.
The last ack completes the cycle. The state resets. You start the next cycle.

Two loops share one vertex with different drivers: one external (health timer),
one participatory (your acks). The vertex doesn't distinguish. Same `receive()`,
same fold, same boundary mechanism. Whether a timer or a human caused it is a
composition-layer fact, invisible to the fold.

**None = unrestricted exposed a category error.**

With explicit grants (`Peer("kyle")` + `grant(horizon=CONTAINERS, potential=...)`),
the root peer's capabilities must be enumerated upfront. This works but creates
a subtle conflation: "debug" was a string in the horizon set alongside "nginx"
and "redis." They looked the same but meant different things — one is a data
domain, the other is a rendering mode.

With `None = unrestricted`, the root peer sees everything. There's no set to
sneak "debug" into. The question "how do I gate the debug panel?" forces you
to find the right mechanism, which isn't horizon at all — it's a lens.

Played out both models across 5 scenarios:
1. Simple hierarchy: identical delegates, only root differs
2. New kind appears: None works automatically, explicit requires update
3. Cross-boundary: None roams, explicit is vertex-specific
4. Deep delegation: identical from level 1 down
5. Forgot to restrict: None fails open (unbounded), explicit fails bounded

The cost of None is that forgetting to restrict a delegate gives full access.
But explicit doesn't prevent the bug — it just makes it slightly less wrong.
The real fix in both models is the same: specify the restrictions.

**Debug is a lens, not a horizon.**

Horizon gates data domains — which containers, which kinds. Debug gates
rendering depth — fold versions, event trace, raw state. Different categories.
The 'd' key is a lens toggle, not an access control.

This dissolves the debug peer entirely. Two peers, not three:
- kyle: unrestricted (root)
- kyle/monitor: restricted potential (can navigate, can't ack)

Any peer can toggle the debug lens. The debug panel is a presentation mode.

Generalizes: the `-q/-v/-vv` pattern from VERBOSITY.md is the same concept.
Quiet/normal/verbose/debug are rendering depths. They don't change what data
you have access to — they change how much of it you see.

### Patterns confirmed

| Pattern | Evidence |
|---------|----------|
| Boundary is peer-agnostic | Same mechanism for timer-driven and action-driven boundaries |
| Composition decides sentinels | Bridge checks "all acked?" and sends sentinel — semantic decision at wiring point |
| None = unrestricted simplifies root | No enumeration, automatically works with new kinds and across vertices |
| Delegation is the constraint mechanism | restrict/delegate narrow from unrestricted; grant expands explicit sets |
| Horizon ≠ lens | Horizon = data access, lens = rendering depth. Different mechanisms. |

---

## Session: review_lens.py — Lens as primitive

### What was built

`review_lens.py`: copy of review.py with Lens added as a first-class primitive.
Lens = zoom (detail level) + scope (visible kinds). Lens changes are facts that
flow through the vertex and persist.

### What emerged

**Lens pairs with Projection.**

```
Projection: Facts → state    (reduce over time, write-side)
Lens:       state → view     (reduce for display, read-side)
```

Both are projections in the mathematical sense — many-to-fewer. Projection
accumulates, Lens filters/zooms. The full pipeline:

```
Facts → Projection(fold) → state → Lens(zoom, scope) → view → Surface
```

**Lens is orthogonal to Peer.**

| Primitive | Question | Dimension |
|-----------|----------|-----------|
| Peer.horizon | What CAN you see? | Access |
| Peer.potential | What CAN you emit? | Capability |
| Lens.scope | What DO you see? | Presentation |
| Lens.zoom | How much detail? | Depth |

Horizon gates data existence. Lens gates data display. Different concerns.

**Lens per peer works.**

Each peer can have a default lens. kyle (operator) gets zoom=2/scope=all.
monitor gets zoom=1/scope=domain (no infrastructure noise). Switching peers
applies their default lens — but any peer can adjust their own lens.

### Patterns confirmed

| Pattern | Evidence |
|---------|----------|
| Lens changes are facts | `emit("lens", zoom=2)` flows through vertex |
| Scope filters presentation | Trace panel only shows kinds in lens.scope |
| Zoom controls depth | Container list shows name-only (z0), +status (z1), +ack info (z2) |
| Lens + Peer orthogonal | Per-peer defaults, independent adjustment |

---

## Session: loop_explicit.py — Loop as explicit runtime

### What was built

`loop_explicit.py`: same as review.py but using explicit Loop class. Loop wraps
Projection with boundary semantics: name, projection, boundary_kind, reset.
Vertex gains `register_loop()` alongside legacy `register()`.

### What emerged

**Loop is execution, Vertex is plumbing.**

Before: Vertex contained `_FoldEngine` internally, mixed routing and folding.
After: Loop owns fold + boundary + tick emission. Vertex just routes.

```python
Loop:
  receive(payload) → fold into projection
  fire(ts, origin) → emit Tick, optionally reset

Vertex:
  register_loop(loop)
  receive(kind, payload) → route to loop, check boundary, return Tick|None
```

**Separation enables isolated testing.**

Test Loop: give it payloads, check state, fire boundary, verify Tick.
Test Vertex: register Loops, route facts, verify boundary coordination.
No need to test both together for basic behaviors.

### Patterns confirmed

| Pattern | Evidence |
|---------|----------|
| Loop is a coherent unit | name + projection + boundary = complete fold cycle |
| Vertex becomes routing | Routes facts, coordinates boundaries, attaches Store |
| Backward compatible | Legacy `register()` still works alongside `register_loop()` |

---

## Session: simultaneous_peers.py — when shared focus breaks

### What was built

`simultaneous_peers.py`: three peers (kyle, alice, bob) navigate concurrently
via asyncio. Single shared focus state creates race condition — last write wins,
cursor jumps chaotically.

### What emerged

**Observer state belongs to the observer.**

Focus isn't "the cursor" — it's "this peer's cursor." With shared focus:
- kyle moves to index 2
- alice moves to index 4 (overwrites kyle)
- kyle sees index 4, confused

With per-peer focus (`focus.kyle`, `focus.alice`):
- Each peer has their own state
- No conflicts
- Rendering layer decides which to display

**This generalizes beyond focus.**

Any state representing an observer's perspective should be peer-scoped:
- Cursor position → `focus.{peer}`
- Scroll offset → `scroll.{peer}`
- Selection → `selection.{peer}`
- Collapse state → `collapse.{peer}`

Aligns with "observer is first-class" — the observer's view is their own.

### Solutions explored

| Solution | Approach | Trade-off |
|----------|----------|-----------|
| Per-peer focus | `focus.kyle`, `focus.alice` | Clean isolation, state partitioning |
| Ownership | One peer owns focus at a time | Coordination overhead |
| Requests | `focus_request` with arbitration | Complexity, latency |
| CRDTs | Vector clocks, merge | Eventually consistent, complex |

Recommendation: per-peer focus. Matches the model.

---

## Session: network_boundary.py — vertices across processes

### What was built

`network_boundary.py`: two vertices in separate asyncio tasks (simulating
processes). Connection primitive bridges them via `asyncio.Queue[bytes]`.
Ticks serialize to JSON, cross the boundary, become facts to consumer vertex.

### What emerged

**The loop model doesn't care about process boundaries.**

```
Process A              Process B
┌─────────────┐        ┌─────────────┐
│ facts → fold│        │ fold ← tick │
│      ↓      │  JSON  │      ↓      │
│   boundary  │───────→│  (as fact)  │
│      ↓      │        │      ↓      │
│    Tick     │        │   state     │
└─────────────┘        └─────────────┘
```

Same primitives: Facts fold, boundaries fire, Ticks emit. The serialization
boundary is just another composition-layer concern.

**Connection is minimal.**

```python
@dataclass
class Connection:
    queue: asyncio.Queue[bytes]
    async def send(self, tick: Tick)
    async def receive(self) -> Tick
```

Queue simulates network. In production: socket, pipe, message broker.
The abstraction is: serialize, transport, deserialize.

**Open questions (deferred).**

- Discovery: how does B find A? (registry, announcement, subscription)
- Failure: what if connection drops? (heartbeat, reconnect)
- Ordering: what if ticks arrive out of order? (sequence numbers)
- Backpressure: what if consumer is slow? (bounded queue, drop policy)

### Patterns confirmed

| Pattern | Evidence |
|---------|----------|
| Tick serializes trivially | JSON with ISO datetime, payload already dict |
| Tick → Fact at boundary | Consumer receives tick, folds `tick.payload` as fact |
| Origin preserved | `tick.origin` carries provenance across boundary |
| Same model, different topology | Loops nest across processes like they nest within |

---

## Session: network_boundary_extended.py — network concerns as facts

### What was built

`network_boundary_extended.py`: four scenarios exploring the open questions from
network_boundary.py. Each demonstrates one concern:

1. **Discovery** — Registry pattern: producers register, consumers lookup
2. **Failure** — Heartbeat timeout: missing beats trigger failure detection
3. **Ordering** — Sequence numbers: gaps detected, becomes information for fold
4. **Backpressure** — Drop policies: oldest vs newest, drops become facts

### What emerged

**Network concerns become facts.**

Every network concern maps to a fact kind:
- `producer.registered` — discovery event
- `connection.failed` — failure event
- `sequence.gap` — ordering anomaly
- `message.dropped` — backpressure event

These aren't exceptions or error codes. They're observations that fold into state.
The consumer's fold decides what they mean. A gap might be critical (financial
transactions) or ignorable (telemetry). The fact carries the information; the
fold interprets.

**Policy is composition-layer.**

The primitives don't change. The wiring chooses:
- Discovery: registry vs announcement vs subscription
- Failure: timeout duration, reconnect strategy
- Ordering: wait for replay vs proceed vs fail
- Backpressure: block vs drop-oldest vs drop-newest

Same `receive()`, same `fold()`, same `boundary()`. Different composition
produces different behavior. This matches the pattern from review.py: semantic
decisions live at wiring points.

**Network is just another boundary.**

Process boundary, network boundary, function boundary — same pattern:
1. State exits one context (serialize)
2. State crosses boundary (transport)
3. State enters new context (deserialize → fact)

The tick doesn't know it crossed a network. The receiving vertex doesn't know
the tick came from another process. The topology is composition-layer; the
primitives are topology-agnostic.

**Failure is observable, not exceptional.**

Traditional model: connection drops → exception → retry logic → error handling.
Loop model: connection drops → `connection.failed` fact → folds into state →
boundary might fire → downstream sees the failure as data.

The failure becomes part of the observed history. You can query it, fold it,
trigger boundaries from it. Reconnect is just another fact (`connection.established`)
entering the vertex.

### Patterns confirmed

| Pattern | Evidence |
|---------|----------|
| Network concerns are facts | Registration, failure, gaps, drops all map to kinds |
| Policy at composition layer | Same primitives, different wiring → different behavior |
| Boundary-agnostic primitives | Vertex doesn't know fact came from network |
| Failure as data | `connection.failed` folds like any other fact |
| Observability by default | Every network event is already observable |

### What remains open

- **Replay protocol**: When gaps detected, how does consumer request replay?
  Likely: emit `replay.request` fact to producer, producer re-sends range.
- **Registry as vertex**: Registry could be a vertex folding `register`/`unregister`
  facts. Would enable: persistence, replication, subscription to changes.
- **Multi-producer coordination**: Multiple producers to one consumer. Ordering
  across producers needs vector clocks or central sequencer.

---

## Session: ZOOM_PATTERNS.md — zoom propagation research

### What was researched

Investigated zoom propagation patterns for multi-lens applications. Four questions:
global vs independent zoom, state management, zoom-width interaction, Lens defaults.

### Conclusions

**Global zoom with per-lens overrides.**

Default to global zoom (user-controlled, same density everywhere). Allow per-lens
overrides for exceptions (health at zoom=2, metrics at zoom=0). Per-peer defaults
give role-appropriate starting points — operator gets full detail, monitor gets
summary.

**Zoom state in vertex for persistence/sharing.**

Lens changes become facts (`emit("lens", zoom=2)`) that fold into state. This
enables persistence (restart reconstructs view config) and sharing (multiple
observers see zoom changes). Local state only when purely presentation (debug
panel width).

**Zoom and width are orthogonal.**

Don't auto-reduce zoom when width is narrow. Truncate instead. User chose zoom=2,
respect it. Ellipsis signals lost information — user can adjust if needed.
Auto-reduction creates mode confusion ("why did my detail disappear?").

**Lens carries optional default_zoom metadata.**

Added `default_zoom: int = 1` to Lens dataclass. It's a hint, not enforced.
Composition layer decides: `zoom = user_zoom if user_zoom is not None else lens.default_zoom`.
Keeps Lens stateless while allowing per-lens preferences.

**Key separation: render function (library) vs view config (app).**

The experiment's per-peer Lens (`PEER_LENS: dict[str, Lens]`) is richer than the
library's Lens. The library Lens is minimal — render + metadata. The app builds
view configuration on top. Same pattern as Peer/delegate: primitives compose at
the application layer.

### Patterns confirmed

| Pattern | Evidence |
|---------|----------|
| Global zoom as default | Single `-/=` control affects all views consistently |
| Per-lens override for exceptions | Mixed-priority data needs different detail levels |
| Per-peer defaults | review_lens.py: operator zoom=2, monitor zoom=1 |
| Zoom changes as facts | `emit("lens", zoom=...)` persists and shares |
| Truncate, don't auto-reduce | Width constraint doesn't silently change zoom |
