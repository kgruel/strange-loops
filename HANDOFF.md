# HANDOFF

Session continuity for the monorepo. Per-library details live in each lib's
own HANDOFF.md.

## The Model

See `LOOPS.md` for the fundamental model. The system is loops.

## Library Handoffs

| Library | Handoff | Focus |
|---------|---------|-------|
| **peers** | `libs/peers/HANDOFF.md` | Identity + constraints |
| **facts** | `libs/facts/HANDOFF.md` | Observation atom |
| **ticks** | `libs/ticks/HANDOFF.md` | Temporal infrastructure |
| **shapes** | `libs/shapes/HANDOFF.md` | Data contracts + fold rules |
| **cells** | `libs/cells/HANDOFF.md` | Terminal UI |

## Documentation

| Doc | Purpose |
|-----|---------|
| `LOOPS.md` | The fundamental model — truths, atoms, topology |
| `CLAUDE.md` | Build commands, structure, conventions |
| `LOG.md` | Session history — what happened when |
| `docs/VERTEX.md` | Intersection point — routing, folding, branching |
| `docs/TEMPORAL.md` | Boundaries and nesting — how loops mark time |
| `docs/PERSISTENCE.md` | Durable state — how loops remember |
| `docs/PEERS.md` | Identity — who observes |
| `ARCHITECTURE.md` | System overview (pre-LOOPS.md, may need alignment) |
| `ARCHITECTURE-JOURNEY.md` | How we got here |

## Experiments

Integration layer (`experiments/`). Each wires the libraries together to
prove a specific aspect of the model.

| Experiment | Proves |
|---|---|
| `fleet.py` | Temporal nesting — Facts fold, Ticks cascade, same primitive at every level |
| `boundary.py` | Data-driven boundaries — data fires the temporal boundary, not an external clock |
| `observe.py` | Feedback loop closes — user interactions are Facts through the same Vertex |
| `review.py` | Peer actions trigger boundaries — your last ack completes the cycle, state resets |

Experiment insights accumulate in `experiments/LOG.md`.

## Next Steps

1. **Vocabulary refactor** — Plan exists as subtask. Review alignment between
   current code and LOOPS.md model. Potential renames: "Store" terminology,
   observe.py update for None=unrestricted Peer model.

2. **Persistence experiment** — Wire FileStore into review.py or new experiment.
   Test: facts survive restart, replay reconstructs state, tick storage emits
   "stored" facts.

3. **observe.py update** — Uses old grant-based Peer pattern. Needs update for
   None=unrestricted model.

## Open Threads

Carry forward across sessions. Resolve or refine as experiments answer them.

- **Naming tension: Peer** — "Peer" implies equality but delegation is
  hierarchical. Alternative: "Identity." Deferred — model works, name can evolve.

- **Naming tension: Tick** — "Tick" implies clock time but boundaries are
  semantic. Current framing: "tick" = arbitrary unit, cycle completed. Deferred.

- **Lens as first-class** — Debug panel is a lens (rendering depth), not a
  horizon (data access). What other lenses exist? Is Lens a primitive or
  composition-layer pattern?

- **Simultaneous peers** — Focus is shared (one vertex, one focus engine).
  When does this break?

- **Store persistence experiment** — No experiment touches Store durability yet.
  What changes when state survives across sessions?

## Resolved

Resolved questions kept for context. See `LOG.md` for full history.

1. ~~Vertex as code~~ — `Vertex` class in `ticks/vertex.py`
2. ~~Store interface~~ — `Store` protocol: append, since, close
3. ~~Kind-based routing~~ — Explicit registration via `Vertex.register()`
4. ~~Tick-to-Fact conversion~~ — Dissolved. Same primitive at every level.
5. ~~Boundary triggering~~ — Implemented. `receive()` returns `Tick | None`.
6. ~~Peer horizon/potential~~ — `None` = unrestricted. Delegation narrows.
7. ~~Sink/Store/Witness~~ — All dissolved into existing atoms.
