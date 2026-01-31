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
| `sources/heartbeat.py` | First sources experiment — CommandSource → Vertex → Fold → Query (liveness) |
| `sources/system_health.py` | Real machine data — df + ps through the loop, custom parsers |
| `sources/system_health_spec.py` | Spec-driven — declarative Specs with upsert/collect folds |
| `sources/system_health_parse.py` | Parse vocabulary — Skip, Split, Pick, Rename, Transform, Coerce in CommandSource |
| `sources/alert_automation.py` | Alert pattern — full pipeline: Source → Parse → Fold → Tick → Alert → back to Vertex, with Store |

Experiment insights accumulate in `experiments/LOG.md`.

## Next Steps

1. **HTTPSource + JSON parse** — Next source adapter to prove the pattern generalizes:
   - Fetch a JSON API (HN, weather, etc.)
   - JSON parse vocabulary (or parse pipeline extension)
   - Same Vertex/Fold/Store pattern, different ingress
   - Proves: "point at data, it flows in"

2. **FileSource** — Watch a file, emit facts on change:
   - Reactive ingress (not just polling)
   - Use case: maildir, log files, config changes

3. **`.loop` file format** — Configuration layer for "oh it would be nice if":
   - Minimal syntax, minimal parser
   - One file → Source + Parse + Spec + Vertex wiring
   - Deferred until HTTPSource/FileSource prove the runtime

4. **Multi-loop runner** — Orchestration for personal data system:
   - Scan `~/.loops/`, run all `.loop` files
   - Hot reload on change
   - Dashboard of active loops, recent facts

5. **input_fields validation** — Validate at registration/wiring time:
   - Check parse pipeline output matches spec.input_fields
   - One-time check, not per-fact overhead
   - Catches mismatches early

## Open Threads

Carry forward across sessions. Resolve or refine as experiments answer them.

- **Consumer logic as code** — Fold ops accumulate, but sorting/ranking for
  display is still custom code. TopN convenience fold helps but doesn't cover
  all cases. Is this the right boundary?

- **ticks/source.py cleanup** — Orphaned Source protocol in ticks conflicts with
  libs/sources. Remove it.

- **Meta-as-loop** — When does meta-state (peer switching, debug toggle) need
  to enter a loop? Signal: when it needs to be shared, persisted, or folded.

- **Store policy** — "Store everything" isn't the right default for all vertices.
  Options: no store (ephemeral), sliding window, sampling, full history.
  Store implements policy, vertex just calls append(). Pattern needs proving.

- **Tick.ts type** — Tick uses `datetime`, Fact uses `float` (epoch seconds).
  Should align to float everywhere for simpler serialization. Low priority.

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
27. ~~Sources lib~~ — libs/sources with Source protocol, CommandSource, Runner. First experiment: heartbeat liveness check.
28. ~~Minimal meaningful flow~~ — Source → Fold → Consumer. Purpose comes from consumer, not spec. Fold without consumer is mechanics without meaning.
29. ~~Parse vocabulary~~ — Split, Pick, Rename, Transform, Coerce, Skip in specs. Declarative primitives for raw → structured.
30. ~~Parse location~~ — Parse belongs in Source (CommandSource.parse parameter). Source produces structured data, Spec folds it.
31. ~~Real machine data~~ — system_health experiments prove df/ps data flows through the model correctly.
32. ~~Typed fold vocabulary~~ — Latest, Count, Sum, Collect, Upsert, TopN, Min, Max. Pure frozen dataclasses.
33. ~~Facet → Field rename~~ — Spec uses `input_fields`/`state_fields`. `Field` class. Old names kept as deprecated aliases.
34. ~~Legacy Fold removed~~ — No string-based `Fold(op=..., target=...)`. Pure typed classes. mill.py marked for update when .loop format lands.
35. ~~Alert automation pattern~~ — alert_automation.py: Source → Parse → Fold → Tick → inline consumer → Alert Fact → back to Vertex.
36. ~~Store in experiments~~ — alert_automation.py wires EventStore to Vertex. Facts persist to JSONL, survive restarts.
37. ~~Spec vocabulary consistency~~ — Typed folds aligned with parse pattern. All frozen dataclasses, IDE-friendly.
