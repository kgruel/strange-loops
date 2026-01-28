# Experiment Log

Insights from building. Each entry captures what emerged — patterns that
weren't planned but fell out of the primitives when composed.

## Open threads

Carry forward across sessions. Resolve or refine as experiments answer them.

- ~~**Temporal boundaries + interaction**~~: Resolved. review.py: the peer's
  acks accumulate until all containers are acked, the composition layer sends
  a sentinel, boundary fires, Tick produced, state resets. The boundary is
  something you *cause*. Temporal structure from participation.
- **Multiple simultaneous peers**: Focus is shared (one vertex, one focus
  engine). If two peers existed concurrently, they'd share cursor state.
  When does this break?
- **Meta-as-loop**: Peer switching is currently meta (outside the loop). When
  does meta-state need to enter a loop? Signal: when it needs to be shared,
  persisted, or folded.
- **Store persistence**: No experiment touches Store yet. What changes when
  state survives across sessions?
- **Lens as first-class concept**: Debug panel is a lens (rendering depth),
  not a horizon (data access). What other lenses exist? Verbosity (-q/-v/-vv)
  is the CLI analogy. Does Lens need to be a primitive, or is it always a
  composition-layer choice?

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
