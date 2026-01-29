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
| **ticks** | `libs/ticks/HANDOFF.md` | Temporal infrastructure (includes Loop) |
| **specs** | `libs/specs/HANDOFF.md` | Data contracts + fold rules |
| **cells** | `libs/cells/HANDOFF.md` | Terminal UI |

## Documentation

| Doc | Purpose |
|-----|---------|
| `LOOPS.md` | The fundamental model — truths, atoms, topology |
| `VOCABULARY.md` | Canonical definitions — atoms, runtime concepts, allowed verbs |
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
| `review.py` | Peer actions trigger boundaries + persistence — facts/ticks to JSONL, replay on startup |
| `summary.py` | Tick-as-input — ticks from review.py become facts to summary loop |
| `cascade.py` | Live composition — two vertices connected via Stream, ticks flow in real-time |
| `loop_explicit.py` | Explicit Loop class — Loop wraps Projection, Vertex routes to Loops |
| `review_lens.py` | Lens as primitive — zoom + scope, lens per peer, orthogonal to horizon |
| `simultaneous_peers.py` | Concurrent peer conflict — shared focus breaks, per-peer focus recommended |
| `network_boundary.py` | Cross-process vertices — Ticks serialize, Connection bridges, same model works |

Experiment insights accumulate in `experiments/LOG.md`.

## Next Steps

1. **Peer-aware pipeline** — Vertex.receive() takes (kind, payload) tuples.
   Should it take Fact objects? Should Peer be passed explicitly? The pipeline
   doc (PLAN.md) identified Peer as implicit. Worth making explicit?

2. **Lens placement** — Lens (zoom + scope) pairs with Projection. Does it
   belong in ticks alongside Projection? Or stay conceptual?

3. **Per-peer focus** — simultaneous_peers.py recommends per-peer focus state.
   Implement and test.

## Open Threads

Carry forward across sessions. Resolve or refine as experiments answer them.

- **Lens as first-class** — Explored in review_lens.py. Lens = zoom + scope,
  pairs with Projection (write-side vs read-side). Leaving conceptual for now.
  Placement TBD (ticks? cells? new lib?).

- **Simultaneous peers** — Explored in simultaneous_peers.py. Shared focus
  breaks with concurrent peers. Recommendation: per-peer focus (focus.kyle,
  focus.alice). Aligns with "observer is first-class."

- **Network boundary** — Explored in network_boundary.py. Ticks serialize to
  JSON, Connection bridges via Queue, same model works. Open: discovery,
  failure handling, ordering guarantees.

- **Naming tension: Peer** — "Peer" implies equality but delegation is
  hierarchical. Alternative: "Identity." Deferred — model works, name can evolve.

- **Naming tension: Tick** — "Tick" implies clock time but boundaries are
  semantic. Current framing: "tick" = arbitrary unit, cycle completed. Deferred.

## Resolved

Resolved questions kept for context. See `LOG.md` for full history.

1. ~~Vertex as code~~ — `Vertex` class in `ticks/vertex.py`
2. ~~Store interface~~ — `Store` protocol: append, since, close
3. ~~Kind-based routing~~ — Explicit registration via `Vertex.register()`
4. ~~Tick-to-Fact conversion~~ — Dissolved. Same primitive at every level.
5. ~~Boundary triggering~~ — Implemented. `receive()` returns `Tick | None`.
6. ~~Peer horizon/potential~~ — `None` = unrestricted. Delegation narrows.
7. ~~Sink/Store/Witness~~ — All dissolved into existing atoms.
8. ~~Store persistence~~ — review.py logs facts/ticks to JSONL, replays on startup.
9. ~~Tick-as-input~~ — summary.py and cascade.py prove ticks become facts to next loop.
10. ~~Live composition~~ — cascade.py: Stream connects vertices, ticks flow in real-time.
11. ~~Vocabulary~~ — VOCABULARY.md: canonical definitions, one page, no ambiguity.
12. ~~Shape→Spec rename~~ — libs/shapes → libs/specs. Code matches vocabulary.
13. ~~Loop as explicit runtime~~ — Loop class in ticks. Vertex.register_loop(). Separation done.
14. ~~Pipeline formalization~~ — PLAN.md documents 8 stages, identifies gaps.
