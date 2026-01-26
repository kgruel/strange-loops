# HANDOFF

Per-library log of changes and open threads.

## cells

### 2026-01-26
Feedback loop: RenderApp renamed to Surface. Added Emit protocol
(`Callable[[str, dict], None]`) with three emission strata — raw input
(key), UI structure (action, resize), domain (subclass-emitted).
`Surface.handle_key()` wraps `process_key()` with action auto-emission.
No cross-lib imports; integration layer wires to Fact.of() + Stream.emit().

### Open
- **ShapeLens extensions**: Tree lens, chart lens, other convention-based renderers.
- **Zoom propagation**: Global vs independent vs relative in composed views. Undecided.
- **CLI → TUI continuum**: Verbosity spectrum (Level 0–4). Documented in demos/VERBOSITY.md.

## facts

### 2026-01-26
Clean break: Event → Fact. Stripped CLI output framework (Event, Result,
Emitter, ListEmitter, NullEmitter, JsonEmitter, PlainEmitter). 6,081 lines
removed. Fact is the observation atom: `Fact(kind: str, ts: datetime,
payload: T)`. Factory: `Fact.of("heartbeat", service="api")`. Dict payloads
wrapped in MappingProxyType. Serialization via to_dict/from_dict.

### Open
- **Kind conventions**: Open string by design. Review as usage patterns emerge.

## shapes

### 2026-01-26
Shape.apply() fold engine: `engine.py` with fold closures (latest, count,
sum, collect, upsert) built from Fold descriptors. Shape.apply(state, payload)
is pure dict→dict, no cross-lib imports. 17 tests.

First concrete shape: container-health. Upsert by container name + count
observations. Input facets: container, image, status, health. State facets:
containers (dict), count (int). Validated end-to-end with Fact and Projection.

### Open
- **KDL parser**: Defer until declarative path matures.
- **Validation/coercion**: Defer until apply() is in use — likely a boundary concern.

## ticks

### 2026-01-26
Tick atom: `Tick(ts: datetime, payload: T)`, frozen, generic. 15 tests.
Projection fold callable: `Projection(initial, fold=fn)` eliminates
ShapeProjection bridge class. 5 tests.

### Open
- **Stream[Tick] downstream**: Validate composability (daily rollups from hourly ticks).
- **Tick emission from Projection**: Boundary trigger not designed (time, count, or event).
- **EventStore naming**: Still called EventStore, should be Store.

## peers

### Open
- **Scope semantics**: Strings in see/do/ask are uninterpreted. Need real usage.
- **Needs/capabilities**: Defer until patterns emerge.
- **Pipeline bridging**: Topological, not structural.

## Cross-cutting

### 2026-01-26
Pipeline experiment reset: old pipeline.py deleted, new test_atoms.py with
14 tests validating full pipeline stage by stage. Fact→Shape bridge is a
3-line extraction function at the composition point.

Experiments archived into `experiments/archive/` (01_cells_demo,
02_spec_driven, 03_atomic_pipeline). All git mv, history preserved.

Container app (`experiments/containers.py`): first end-to-end wiring of
all five atoms. Docker polling → Fact.of("container-health") → Stream →
Projection(fold=shape.apply) → shape_lens → Surface. Peer in the header.
Pipeline validated (all imports resolve, shape folds correctly, projection
wires). Needs Docker daemon (Colima) to run live.

### Patterns
- **Fact→Shape bridge**: Every Projection folding Facts through a Shape
  needs a thin extraction function (3 lines). Watch for recurrence.
- **Kind→Shape routing**: Fact.kind == Shape.name observed in container app.
  Not codified — watch for whether this becomes a convention or stays ad-hoc.
- **"Personal semantic Kafka"**: Same plumbing (streams, projections, stores),
  reimagined for personal context without enterprise cruft.
