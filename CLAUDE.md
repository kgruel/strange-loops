# CLAUDE.md

Guidance for Claude Code working with the loops monorepo.

## The Model

See `LOOPS.md` for the fundamental model. The system is loops.

**The truths:**
- Time is fundamental. The past happened.
- The observer is first-class. Facts exist because a Peer observed.
- Everything is loops. The end connects to the beginning.

**The atoms:**

| Atom | Structure | Question |
|------|-----------|----------|
| Fact | kind + ts + payload | *what happened* |
| Peer | name + horizon + potential | *who observed* |
| Tick | name + ts + payload + origin | *when a cycle completed* |
| Spec | facets + folds + boundary | *how state accumulates* |
| Vertex | routes + folds + ticks | *where loops meet* |

Cell is a surface primitive (terminal), not a loop atom.

## Build & Test

```bash
uv sync                                                    # install all
uv run --package peers pytest libs/peers/tests             # test one lib
uv run --package cells pytest libs/cells/tests/test_span.py  # single file
```

## Structure

```
libs/
  peers/    Identity: name + horizon + potential
  facts/    Observation: kind + ts + payload
  ticks/    Temporal: Tick, Vertex, Store, Stream, Projection
  specs/    Contract: Facet, Fold, Boundary, Spec
  cells/    Surface: Cell, Block, Buffer, Lens, Surface

experiments/   Integration layer — wires libs together
docs/          Deep dives (VERTEX.md, TEMPORAL.md, PERSISTENCE.md, PEERS.md)
```

Each lib has its own `CLAUDE.md` (API, invariants) and `HANDOFF.md` (changelog).

## Data Flow

```
Peer observes ──→ Fact(kind, ts, payload)
                        │
                        ▼
                    Vertex ── routes by kind ── Fold (Spec.apply)
                        │                           │
                        │                      state accumulates
                        │                           │
                        │                      boundary? ──→ Tick
                        │                                      │
                        └── Surface ←── Lens ←── state         │
                              │                                │
                              └── emit ──→ new Fact ───────────┘
```

Facts go in, Ticks come out. Ticks from one loop enter another as atomic input.
Same primitive at every level. Loops nest.

## Key Patterns

- Libs are independent — no cross-lib imports. Composition in experiments.
- Immutable by default — frozen dataclasses, pure functions
- Spec is the contract — describes structure and fold operations
- `Projection(initial, fold=spec.apply)` — no bridge class needed
- Vertex is sync — async bridge lives at composition point

## Conventions

**Kind namespacing:** Infrastructure facts prefixed by origin (`ui.key`, `ui.action`).
Domain facts stay bare (`"health"`, `"deploy"`).

**Kind → Spec naming:** Name Spec after the Fact kind it folds. Legibility, not dispatch.

## References

| Doc | Focus |
|-----|-------|
| `LOOPS.md` | The fundamental model — truths, atoms, topology |
| `HANDOFF.md` | Session continuity — next steps, open threads |
| `LOG.md` | Session history — what happened when |
| `docs/VERTEX.md` | Intersection point — routing, folding, branching |
| `docs/TEMPORAL.md` | Boundaries and nesting — how loops mark time |
| `docs/PERSISTENCE.md` | Durable state — how loops remember |
| `docs/PEERS.md` | Identity — who observes |
