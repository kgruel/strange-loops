# HANDOFF

Session continuity for the monorepo. Per-library details live in each lib's
own HANDOFF.md.

## The Model

See `LOOPS.md` for the fundamental model. See `VOCABULARY.md` for definitions.

**Three atoms:** Fact, Spec, Tick

**Two libraries:**
- **data** — what data looks like, how to get it (Fact, Spec, Source, Parse, Fold)
- **vertex** — how it runs, when boundaries fire (Vertex, Loop, Store, Grant)

**One DSL:** dsl — `.loop` and `.vertex` file parser, compiles to data/vertex types

**One surface:** cells — terminal UI, separate concern

## Libraries

| Library | Focus |
|---------|-------|
| **data** | Observation + Contract + Ingress: Fact, Spec, Source, Parse, Fold |
| **vertex** | Runtime + Identity: Tick, Vertex, Loop, Store, Peer, Grant |
| **dsl** | DSL parser: .loop/.vertex files → AST → runtime types |
| **cells** | Terminal UI: Cell, Block, Buffer, Surface |

## Documentation

| Doc | Purpose |
|-----|---------|
| `LOOPS.md` | The fundamental model — truths, atoms, data flow |
| `VOCABULARY.md` | Canonical definitions — concepts vs types, verbs |
| `CLAUDE.md` | Build commands, structure, conventions |
| `LOG.md` | Session history — what happened when |
| `docs/VERTEX.md` | Routing, folding, branching |
| `docs/TEMPORAL.md` | Boundaries and nesting |
| `docs/PERSISTENCE.md` | Durable state, replay |
| `docs/CADENCE.md` | Cadence/Source split — when vs what |

## Experiments

Integration layer (`experiments/`). Each wires the libraries together to
prove a specific aspect of the model.

| Experiment | Proves |
|---|---|
| `fleet.py` | Temporal nesting — Facts fold, Ticks cascade |
| `boundary.py` | Data-driven boundaries — data fires boundary, not clock |
| `observe.py` | Feedback loop closes — user interactions are Facts |
| `review.py` | Persistence — facts/ticks to JSONL, replay on startup |
| `summary.py` | Tick-as-input — ticks become facts to next loop |
| `cascade.py` | Live composition — Stream connects vertices |
| `sources/heartbeat.py` | Source → Vertex → Fold → liveness query |
| `sources/system_health.py` | Real machine data — df + ps through loop |
| `sources/system_health_spec.py` | Declarative Specs with folds |
| `sources/system_health_parse.py` | Parse vocabulary in Source |
| `sources/alert_automation.py` | Full pipeline with Store persistence |
| `cells_vertex.py` | Cells-Vertex integration — full feedback loop closes |
| `temporal/tick_since.py` | Fidelity traversal — Tick.since + Store.between() |
| `fidelity_lens.py` | Zoom-to-fidelity — Lens renders ticks at varying depth |

## Current Focus: Cadence/Source Split

See `docs/CADENCE.md` for full design. Key insight: Source has two concerns that
should be separate.

| Concept | Answers | Examples |
|---------|---------|----------|
| **Cadence** | When to observe | `every 10s`, `on: minute`, `on: deploy.complete` |
| **Source** | What to observe | command, API, stream, nothing (pure timer) |

**Timer as fact.** A timer is a loop with cadence but no source — it emits
time-shaped facts. Other loops trigger `on:` those facts. The clock is just
another data source.

**Runtime simplification.** Sources don't manage their own timers. One fact
stream, uniform receive → route → fold. Event-driven and time-driven use the
same mechanism.

### Open Questions (Cadence/Source)

1. **Sugar vs explicit** — Should `every: 10s` auto-create a timer, or require
   explicit timer loop? Trade-off: convenience vs visibility.

2. **Multiple triggers** — Can a source have `on: [minute, deploy.complete]`?
   What's the semantics — OR (either triggers) or AND (both required)?

3. **Feedback loops** — A → B → A is possible. Bug or feature? Control systems
   are real. Detection/prevention is tooling, not model.

4. **Backpressure** — If trigger fires faster than source executes, queue or
   drop? Probably queue with bounds, but needs design.

### In Flight

- **chore/doc-audit** — Inventorying all docs for aggressive cleanup
- **exp/cadence-viz** — Animated TUI showing timer cascade at max fidelity

## Next Steps

1. **Resolve Cadence/Source questions** — work through the open questions above
2. **Implement cadence experiment** — prove the pattern with visualization
3. **Update DSL** — add `on:` syntax, separate cadence from source
4. **Composition** — tick-as-fact mechanics, vertex → vertex wiring

## Open Threads (Deferred)

- **String structure** — observer, kind, origin namespacing. Pattern hasn't
  emerged yet.

- **Consumer logic** — ranking/sorting for display is custom code. Right
  boundary?

- **Store policy** — ephemeral, sliding window, sampling. Use case will clarify.

## Resolved

49. ~~Fidelity-aware Lens~~ — Zoom maps to fidelity. Build pipeline domain with
    nested phase ticks. zoom=0 minimal, zoom=1 summary, zoom=2+ expands nested
    ticks, zoom=4 fetches contributing facts via Store.between(). Interactive
    mode with +/- navigation. `experiments/fidelity_lens.py`.

48. ~~Cells-Vertex integration~~ — Counter with undo experiment. Keypresses become
    Facts, Vertex folds, Ticks render to Blocks. Full feedback loop closes.
    `experiments/cells_vertex.py`.

47. ~~Tick.since fidelity traversal~~ — Tick now has `since: datetime | None` for
    period start. Store has `between(start, end)` for time-range queries. Loop
    tracks period start, produces ticks with `since`. Given a tick, retrieve the
    facts that produced it via `store.between(tick.since, tick.ts)`. 26 new tests.
    `experiments/temporal/tick_since.py` proves re-fold verification.

46. ~~DSL experiment~~ — End-to-end test of .loop/.vertex workflow. Created
    `experiments/monitors/` with disk.loop, proc.loop, system.vertex. Fixed Source
    to emit `{kind}.complete` facts for boundary triggering. Fixed fold engines
    (Collect, Upsert) to convert MappingProxyType payloads to dict. CLI `loop start`
    works: discovers sources, streams facts through folds, emits ticks on boundaries.

45. ~~DSL implementation~~ — Custom syntax (not YAML). `.loop` for sources with parse
    pipelines, `.vertex` for wiring with folds and boundaries. Lexer, parser,
    validator (shape inference), mapper (AST → runtime types), CLI (`loop validate`,
    `test`, `run`, `compile`, `start`). 104 tests. `libs/dsl/`.

43. ~~DSL design research~~ — Custom syntax over YAML for expressiveness. Parse pipeline
    notation (`skip`, `split`, `pick -> names`), fold combinators (`by`, `+1`, `latest`).
    Design at `.subtask/tasks/impl--loop-dsl/PLAN.md`

38. ~~Sources refactor~~ — CommandSource → Source. Added format (lines|json|blob).
    interval → every. Shell as universal adapter.

39. ~~Model consolidation~~ — 5 atoms → 3 (Fact, Spec, Tick). 6 libs → 2 + cells.
    Peer dissolved to observer field + Grant policy. Vertex is runtime not atom.

40. ~~Concept vs type~~ — observer, kind, origin, boundary, fidelity are concepts
    (strings/fields). Fact, Spec, Tick are atoms (types). Distinction in VOCABULARY.md.

41. ~~Tick as period handle~~ — Tick isn't just a summary, it's a handle to a
    semantic period. Fidelity = traversal depth. Hierarchy emerges from
    ticks-as-facts flowing into other loops.

42. ~~One-way flow truth~~ — Added fourth truth: "Everything flows one direction."
    Failures, conditionals, nested spans are all just more facts.

44. ~~Library consolidation~~ — 6 libs → 3: `data` (facts + specs + sources),
    `vertex` (ticks + peers), `cells` (unchanged). Clean break, no deprecation
    aliases. All imports updated to new paths.

See `LOG.md` for older resolved items and full session history.
