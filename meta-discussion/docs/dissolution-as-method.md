# Dissolution as Design Method

The most distinctive pattern across these projects. Before building X, ask:
can X be expressed as a property or composition of what already exists?

## The Pattern

```
Proposed concept  →  Dissolution test  →  Yes: configure existing primitives
                                      →  No: new primitive (rare, justified)
```

This isn't just "don't over-engineer." It's an active design method — you
*try* to dissolve every new concept and only accept it as real when dissolution
fails.

## The Scorecard (loops)

| Concept | Dissolved Into | Why |
|---------|---------------|-----|
| Peer (as atom) | observer field + Grant policy | Identity is a string on Fact, policy is runtime |
| Vertex (as atom) | engine (runtime library) | Vertex is execution, not data |
| Sink | Fold state | Loops have no terminals |
| Store (as atom) | Vertex capability | Persistence is a runtime property |
| Witness | Observer + Vertex | A witness is just an observer whose job is to emit |
| Tap | Vertex | Emission from storage is vertex behavior |
| Memory | Boundary-less fold | Silent accumulation is a fold that never ticks |
| Fidelity | Lens + Zoom | Progressive commitment is what lenses already do |
| Live vs Stored | Refresh loop | SQLite concurrent readers make store the boundary |
| Debug as horizon | Debug as lens | It's a rendering mode, not a data domain |
| Tick-into-Fact | False distinction | Same primitive at every level |

Eleven dissolutions. Three atoms remain.

## Where Dissolution Applies Beyond Data Modeling

### Testing

"Do we need a mock framework?" → Dissolution: factories build real objects.
Mocks dissolved into controlled construction.

"Do we need golden tests?" → Depends. If output is visual (painted TUI), yes —
golden tests capture rendering. If output is structured data, no — assertion on
the data is sufficient. Golden tests dissolve when the output has a natural
equality check.

### Tooling

"Do we need a build system?" → Dissolution: `./dev` dispatcher + shell scripts.
Build systems dissolve when the task graph is linear (arch → lint → test).

"Do we need tach?" → Partially dissolves. Cross-lib boundaries are already
enforced by packaging. Tach adds value for intra-lib boundaries and static
detection. It doesn't dissolve completely.

"Do we need a CI/CD tool?" → For loops (local dev), dissolves into `./dev check`.
For gruel.network (deployed infra), doesn't dissolve — real deployment needs
real CI.

### Architecture

"Do we need a session type?" → Dissolution test in progress. Current `loops
session` uses a vertex + store. Named sessions might just be named vertices with
named stores. If session = vertex + store + name, it dissolves. If sessions need
cross-session queries or nesting that vertices don't support, it's a new concept.

### Process

"Do we need sprint planning?" → Dissolution: session continuity (LOG.md +
HANDOFF.md + session facts). The sine wave doesn't fit sprints. It fits
sessions with named threads that carry forward.

## The Risk

Dissolution can become an excuse to never build anything new. The test has two
outcomes, and the "no, this is genuinely new" outcome is valid. Fact, Spec, and
Tick survived dissolution — they're real atoms, not compositions. The discipline
is applying the test honestly, not always answering "dissolves."

## Relationship to Other Patterns

- **Factories over mocks**: mocks dissolve into controlled real objects
- **Integration over simulation**: simulated dependencies dissolve into real ones
  (at manageable cost)
- **Patterns over point solutions**: point solutions dissolve into instances of
  general patterns
- **Experiment → graduation**: experiments that dissolve into existing code don't
  graduate — they were explorations that confirmed existing primitives suffice
