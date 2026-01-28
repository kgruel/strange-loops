# Experiment Log

Insights from building. Each entry captures what emerged — patterns that
weren't planned but fell out of the primitives when composed.

## Open threads

Carry forward across sessions. Resolve or refine as experiments answer them.

- **Temporal boundaries + interaction**: What happens when the Peer's actions
  trigger a boundary? Does the observer experience the tick? (observe.py has
  continuous fold — no ticks yet)
- **Multiple simultaneous peers**: Focus is shared (one vertex, one focus
  engine). If two peers existed concurrently, they'd share cursor state.
  When does this break?
- **Meta-as-loop**: Peer switching and debug toggle are currently meta (outside
  the loop). When does meta-state need to enter a loop? Signal: when it needs
  to be shared, persisted, or folded.
- **Store persistence**: No experiment touches Store yet. What changes when
  state survives across sessions?

---

## Session: observe.py — closing the feedback loop

### What was built

`observe.py`: user interactions and external observations enter the same
Vertex through the same `receive()`. Three peers (operator, monitor, debug).
Debug panel slides in with full `vertex.receive()` trace, horizon-gated.

### What emerged

**Debug is horizon, not infrastructure.**

Traditional debug logging is a parallel channel — `console.log`, log levels,
separate tools. In the loop model, the data is already flowing through the
vertex. Debug isn't "capture more data" — it's "who can see what's already
there?" That's horizon.

`_wrap_receive()` at the composition layer (5 lines, no lib changes)
instruments the entire event stream. The debug peer has `"debug"` in horizon.
Render checks one flag. No debug framework, no log levels, no separate channel.

Generalizes: any cross-cutting concern that's really about visibility — audit
trails, monitoring, access logs — is a horizon configuration. The data is
already flowing. You configure a peer who can see it.

The `grant(delegate(...), horizon={"debug"})` construction: delegation narrowed
potential (can't ack), grant added visibility. The debug peer sees more but
does less. Correct shape for a system observer — expanded view, restricted
action. Fell out of two function calls.

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
