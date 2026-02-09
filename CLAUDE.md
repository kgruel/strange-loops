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
| Fact | kind + ts + payload + observer | *what happened* |
| Spec | fields + folds + boundary | *how state accumulates* |
| Tick | name + ts + payload + origin | *when a cycle completed* |

Three atoms. Peer dissolved to `observer` field on Fact + `Grant` policy at Vertex.
Vertex is runtime infrastructure, not an atom. Cell is a surface primitive.

## Build & Test

```bash
uv sync                                                    # install all
uv run --package atoms pytest libs/atoms/tests               # test one lib
uv run --package engine pytest libs/engine/tests           # test another
uv run --package cells pytest libs/cells/tests/test_span.py  # single file
```

## Structure

```
libs/
  atoms/    Observation + Contract + Ingress: Fact, Spec, Source
  lang/     KDL loader + validator for .loop/.vertex files
  engine/   Temporal + Identity: Tick, Vertex, Peer, Grant
  cells/    Surface: Cell, Block, Buffer, Lens, Surface

experiments/   Integration layer — wires libs together
docs/          Deep dives (VERTEX.md, TEMPORAL.md, PERSISTENCE.md, PEERS.md)
```

Each lib has its own README.md with API overview.

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

- Two libraries: `atoms` (atoms + contracts), `engine` (runtime + identity). `cells` is surface.
- `engine` depends on `atoms` (TYPE_CHECKING only). No other cross-lib imports.
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
| `docs/IDENTITY.md` | Observer and gating — who sees, who emits |
