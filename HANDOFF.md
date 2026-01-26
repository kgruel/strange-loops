# HANDOFF

Last session: 2026-01-26

## What happened

Full review of all five libraries for vocabulary consistency before
rebuilding the pipeline experiment from scratch. Three atoms
implemented/refactored, one design tension resolved, one clean break.

### Resolved

**Tick atom** — Cherry-picked from `implement/tick-atom` branch
(branch had collateral HANDOFF/THREADS deletions from diverged
subtask). `Tick(ts: datetime, payload: T)`, frozen, generic. 15 tests.
The ticks package now has its actual atom.

**Shape.apply()** — Fold execution moved from experiments into shapes.
New `engine.py` with fold closures (latest, count, sum, collect,
upsert) built from Fold descriptors. `Shape.apply(state, payload)`
is pure dict→dict, no cross-lib imports. Shape is now self-contained:
declare + execute. 17 new tests.

**Projection fold callable** — `Projection(initial, fold=fn)` accepts
an optional callable. Subclass pattern preserved for backwards compat.
This eliminates the ShapeProjection bridge class — composition at the
call site: `Projection(initial=shape.initial_state(), fold=shape.apply)`.
5 new tests.

**Fact atom (clean break)** — Event→Fact rename executed as a full
redesign, not just a rename. Stripped all CLI output framework: Event,
Result, Emitter, ListEmitter, NullEmitter, JsonEmitter, PlainEmitter,
docs/. 6,081 lines removed.

Fact is the observation atom: `Fact(kind: str, ts: datetime, payload: T)`.
- kind is an open string — no enum, no constrained set. Routing key.
- Structure comes from Shape, not from kind.
- Factory: `Fact.of("heartbeat", service="api", latency=42)`
- Serialization: `to_dict()` / `from_dict()` for JSONL persistence
- Dict payloads wrapped in MappingProxyType for immutability
- `is_kind(*kinds)` predicate for filtering

Design rationale: Facts go in, Ticks come out. Fact is an intentional
observation (raw, from the world). Tick is a derived snapshot (cooked,
at a boundary). Same envelope pattern, different semantics. Fact has
`kind` which Tick doesn't — observations always have a category.

### Updated

- CLAUDE.md: atoms table, data flow diagram, core libraries table,
  key patterns — all updated for Fact/Shape.apply/Projection fold.
- All five THREADS.md files updated with resolved threads and
  vocabulary corrections (Event→Fact).

**Pipeline experiment reset** — Deleted old `experiments/apps/pipeline.py`
and `experiments/tests/test_pipeline.py` (used Event, ShapeProjection
bridge class, old vocabulary). Built new `experiments/tests/test_atoms.py`
— 14 tests validating the full pipeline atomically, stage by stage:

1. Fact creation (direct, factory, is_kind)
2. Stream[Fact] carries and fans out
3. Shape defines contract with initial_state
4. Shape.apply folds payloads into state (single, accumulate, immutability)
5. Projection(fold=...) wires Stream → Shape.apply
6. Tick snapshots state, Tick flows through downstream Stream[Tick]

The bridge between Fact and Shape is a 3-line function:
```python
def _make_fold(shape):
    def fold(state, fact):
        return shape.apply(state, dict(fact.payload))
    return fold
```
Projection receives Facts, Shape.apply receives dicts. The extraction
happens at the composition point — no class, no import tangle.

## Next session

Continue building up the pipeline experiment. The atoms validate —
next layers to add:

- **Lens → Cells**: Render projected state through shape_lens into
  terminal output. Validates the shapes→cells bridge.
- **Persistence**: Stream[Fact] → FileWriter → Tailer → replay.
  Validates the facts→ticks persistence path.
- **Live app**: Surface wiring all five libs end-to-end.
  The old pipeline.py rebuilt with the new atoms and no bridge classes.

The old experiments/ still has apps (homelab, demo, logs, etc.) and
framework/ code that uses the old Event import — these will break.
Clean up or port as needed when those experiments are revisited.

## Open threads

### facts
- **Kind conventions**: Open string by design. Review conventions as
  usage patterns emerge from pipeline rebuild.

### shapes
- **KDL parser**: Defer until declarative path matures.
- **Validation/coercion on Shape**: Defer until apply() is in use and
  we see where validation fits (likely boundary concern, before apply).

### ticks
- **Stream[Tick] downstream**: Validate composability once pipeline
  is rebuilt (daily rollups from hourly ticks).
- **Tick emission from Projection**: Boundary trigger mechanism not
  designed — time-based, count-based, or event-driven.
- **EventStore naming**: Still called EventStore, should be Store.

### peers
- **Scope semantics**: Strings in see/do/ask are uninterpreted. Need
  real usage to ground them.
- **Needs/capabilities**: Defer until patterns emerge.
- **Stance convenience**: Low priority utility function.
- **Pipeline bridging**: Topological, not structural.

### cells
- **Feedback loop**: User actions → Facts on the stream. Not implemented.
- **ShapeLens extensions**: Tree lens, chart lens. Future.
- **Zoom propagation**: Global vs independent vs relative. Not decided.

### Emerging patterns

- **Fact→Shape bridge**: Every Projection that folds Facts through a
  Shape needs a thin extraction function. This is 3 lines today. If
  it keeps recurring, it may become a utility. Watch for this.
- **"Personal semantic Kafka"**: The project framing that emerged —
  same plumbing and concepts as Kafka (streams, projections, stores),
  reimagined for personal context without enterprise cruft.

## Commits this session

```
2125bcb Replace old pipeline experiment with atomic pipeline tests
61fbc73 Update CLAUDE.md, HANDOFF.md, and THREADS.md for session vocabulary changes
49ea6a0 Replace Event with Fact atom, strip CLI framework from facts library
9738280 Add Shape.apply() fold engine and Projection fold callable
b8d5879 Add Tick atom to ticks library: frozen dataclass ts + payload
```
