# HANDOFF

Last session: 2026-01-26

## What happened

Alignment review of the prism monorepo against the vision in CLAUDE.md.
Five issues found, three resolved, two advanced.

### Resolved

**Shapes vocabulary** — `Field`/`Form` renamed to `Facet`/`Shape`.
Package stays `shapes`. Geometric metaphor domain (origami: a Shape
is the result of Folds applied to flat material, Facets are the
measurable faces). `Fold.props` immutability fixed with
`MappingProxyType`. Merged to main.

**Tick concept** — Tick is not the input to the stream, it's the
output of Projection. A frozen snapshot at a temporal boundary.
`Tick = ts + payload`, generic, opt-in. Events go in, Ticks come
out. If you don't need temporal windowing, you get live state
instead. Same fold, same Shape, different output mode. Subtask
`implement/tick-atom` is drafted and planning.

**Peer participation** — Stance (direct/guided/delegated/automated/
observing) dissolves into the delegation hierarchy. Root peer acts
directly, child peers act on behalf with restricted scope. The
identity IS the stance. No new type needed. Possibly a convenience
labeller later.

### Updated

CLAUDE.md now has: metaphor column on atoms table, revised data flow
diagram with stream taps and peer feedback loop, Tick definition,
Peer participation section.

THREADS.md seeded in all five libraries with open design questions
from this and prior sessions. Convention: keep these updated as
threads open/close.

## In flight

- `implement/tick-atom` subtask — worker drafting plan. Small scope:
  one frozen dataclass, tests, export. Review and merge.

## Open threads

### peers

- **Scope semantics**: see/do/ask are frozensets of strings. What do
  those strings concretely mean when they cascade through the
  pipeline? e.g., `see={"metrics"}` — does that filter which Events
  you receive? Which Shapes you can read? Which Lenses render for
  you?
- **Needs and capabilities**: Different from permissions. Needs = what
  a peer requires to function (Must/Should/May gradient). Capabilities
  = what a peer can offer. These compose with scope. Defer until
  patterns emerge from real usage.
- **Stance convenience**: A utility that reads the delegation
  hierarchy and labels the participation level. Not a type, possibly
  a function: `stance(peer) -> str`.

### facts

- **Vocabulary rename**: Prior session planned Event -> Fact,
  Result -> Verdict. Code in prism still uses Event/Result. Decision
  needed: do we still want this rename? Event has earned its place
  in the codebase — the pipeline reads naturally with "Event". But
  "Fact" was the original grounded vocabulary choice.
- **API refinement**: The original discussion noted facts needs
  vocabulary and API work. Specifics not yet scoped.

### ticks

- **Tick class**: Design done, implementation in flight. After merge,
  the pipeline wiring in experiments should demonstrate Tick as the
  output of ShapeProjection at temporal boundaries.
- **Stream[Tick] downstream**: Once Tick exists, experiment with
  Projection emitting `Tick[dict]` into a downstream `Stream[Tick]`
  for further projection/persistence. This validates the "ticks of
  ticks" composability (e.g., daily rollups from hourly ticks).

### shapes

- **Shape.apply()**: CLAUDE.md mentions `Shape (facets + folds + apply)`
  but no `apply` method exists on Shape. Fold application currently
  lives in `ShapeProjection` in experiments. Decision: does Shape get
  an `apply(state, event) -> state` method, or does application stay
  in the experiments bridge?

### cells

- **Feedback loop**: Cells emitting facts back into ticks (UI
  observability). Discussed in prior sessions, not implemented.
- **ShapeLens extensions**: Tree lens, chart lens, other conventions
  beyond the current dict->table, list->list-view defaults.

### cross-cutting

- **Per-lib THREADS.md**: Seeded across all five libraries. Each
  THREADS.md captures open design questions, unresolved vocabulary
  decisions, and deferred work for that library. Convention: update
  THREADS.md as threads open/close during sessions.

  ```
  libs/peers/THREADS.md  — scope semantics, needs/capabilities, stance, pipeline bridging
  libs/facts/THREADS.md  — Event vs Fact rename, API refinement, Emitter protocol
  libs/ticks/THREADS.md  — Tick class, Stream[Tick] downstream, emission boundaries, Store naming
  libs/shapes/THREADS.md — Shape.apply(), KDL parser, validation/coercion methods
  libs/cells/THREADS.md  — feedback loop, ShapeLens extensions, zoom propagation, CLI->TUI continuum
  ```

## Commits this session

```
007a67d Update CLAUDE.md with data flow, metaphor domains, Tick/Peer concepts
85c072b Update CLAUDE.md with atoms vocabulary and data flow diagram
```

Plus squash-merged from subtask:
```
Refactor shapes vocabulary: Field->Facet, Form->Shape, fix Fold.props immutability
```
