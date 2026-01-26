# HANDOFF

Monorepo overview. Per-library details live in each lib's own HANDOFF.md.

## Library Handoffs

| Library | Handoff | Focus |
|---------|---------|-------|
| **peers** | `libs/peers/HANDOFF.md` | Scoped identity |
| **facts** | `libs/facts/HANDOFF.md` | Observation atom |
| **ticks** | `libs/ticks/HANDOFF.md` | Temporal infrastructure |
| **shapes** | `libs/shapes/HANDOFF.md` | Data contracts + fold rules |
| **cells** | `libs/cells/HANDOFF.md` | Terminal UI |

## Cross-cutting

### 2026-01-26
Pipeline experiment reset: old pipeline.py deleted, new test_atoms.py with
14 tests validating full pipeline stage by stage. Fact->Shape bridge is a
3-line extraction function at the composition point.

Experiments archived into `experiments/archive/` (01_cells_demo,
02_spec_driven, 03_atomic_pipeline). All git mv, history preserved.

Container app (`experiments/containers.py`): first end-to-end wiring of
all five atoms. Docker polling -> Fact.of("container-health") -> Stream ->
Projection(fold=shape.apply) -> shape_lens -> Surface. Peer in the header.
Pipeline validated (all imports resolve, shape folds correctly, projection
wires). Needs Docker daemon (Colima) to run live.

### Patterns
- **Fact->Shape bridge**: Every Projection folding Facts through a Shape
  needs a thin extraction function (3 lines). Watch for recurrence.
- **Kind->Shape routing**: Fact.kind == Shape.name observed in container app.
  Not codified — watch for whether this becomes a convention or stays ad-hoc.
- **"Personal semantic Kafka"**: Same plumbing (streams, projections, stores),
  reimagined for personal context without enterprise cruft.
