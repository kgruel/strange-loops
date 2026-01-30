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
| **sources** | `libs/sources/HANDOFF.md` | Ingress adapters |
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
| `network_boundary_extended.py` | Network concerns as facts — discovery, failure, ordering, backpressure |
| `peer_focus.py` | Per-peer observer state — `focus.{peer}` pattern, no conflicts |
| `lens_code.py` | Lens placement analysis — core Lens (ticks) vs render Lens (cells) |
| `peer_aware_vertex.py` | Full model — Vertex.receive(Fact, Peer), gating, observer-state ownership |
| `peer_surface.py` | Cells integration — peer-aware Vertex wired to Surface, gating visible in TUI |

Experiment insights accumulate in `experiments/LOG.md`.

## Next Steps

1. **First sources experiment** — Use new sources lib to prove the flow:
   CommandSource → Runner → Vertex → Ticks. Real external data.

2. **Custom Spec DSL** — Explore building a custom spec file format. Analysis
   in `.subtask/tasks/explore--custom-spec-dsl/ANALYSIS.md` covers:
   - Proposed syntax (HCL-inspired block structure)
   - Parser options (Lark recommended)
   - Key question: Is declarative spec definition worth the investment?

3. **Update existing experiments** — Migrate remaining experiments to use
   `Vertex.receive(fact, observer)` signature for consistency.

## Open Threads

Carry forward across sessions. Resolve or refine as experiments answer them.

- **Spec DSL decision** — Custom DSL vs YAML. Analysis done, need to decide
  if 2-3 week investment is worth the cleaner file format.

- **Meta-as-loop** — When does meta-state (peer switching, debug toggle) need
  to enter a loop? Signal: when it needs to be shared, persisted, or folded.

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
15. ~~Peer-aware pipeline~~ — Vertex.receive(Fact, Peer). Gating at integration point. Observer is first-class.
16. ~~Lens placement~~ — Core Lens (zoom + scope) in ticks. Render lenses stay in cells.
17. ~~Per-peer focus~~ — `{kind}.{peer}` pattern. Observer state belongs to observer. Ownership enforced at receive.
18. ~~Network concerns~~ — Discovery, failure, ordering, backpressure all become facts that fold. Policy is composition-layer.
19. ~~Cells integration~~ — peer_surface.py: Surface.emit() → Fact → Vertex.receive(fact, peer). Gating visible in TUI debug panel.
20. ~~Observer model~~ — Fact.observer required. Grant is optional policy. Vertex.to_fact() bridges boundaries.
21. ~~Persistence~~ — replay(vertex, store) for event sourcing. Facts are truth, state is derived.
22. ~~Network transport~~ — experiments/transport/ with vertex_server.py and vertex_client.py. Real TCP.
23. ~~Flowable layouts~~ — join_responsive() for adaptive horizontal/vertical composition.
24. ~~Experiments organized~~ — Grouped by concept: observer/, temporal/, network/, presentation/.
25. ~~Fidelity rename~~ — Verbosity → Fidelity for CLI→TUI spectrum. Fidelity = presentation richness.
26. ~~Source concept~~ — Sources are adapters at the ingress boundary. Not atoms. Interface: vertex.ingest(kind, payload, observer).
