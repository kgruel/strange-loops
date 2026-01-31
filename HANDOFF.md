# HANDOFF

Session continuity for the monorepo. Per-library details live in each lib's
own HANDOFF.md.

## The Model

See `LOOPS.md` for the fundamental model. See `VOCABULARY.md` for definitions.

**Three atoms:** Fact, Spec, Tick

**Two libraries:**
- **data** — what data looks like, how to get it (Fact, Spec, Source, Parse, Fold)
- **vertex** — how it runs, when boundaries fire (Vertex, Loop, Store, Grant)

**One surface:** cells — terminal UI, separate concern

## Libraries

| Library | Focus |
|---------|-------|
| **data** | Observation + Contract + Ingress: Fact, Spec, Source, Parse, Fold |
| **vertex** | Runtime + Identity: Tick, Vertex, Loop, Store, Peer, Grant |
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

## Next Steps

1. **.loop DSL implementation** — Design complete, ready to build:
   - Design notes: `.subtask/tasks/research--loop-dsl-design/PLAN.md`
   - Format: YAML
   - Files: `.loop` (sources) + `.vertex` (wiring)
   - Validation: parse-time shape inference

2. **Static validation** — data lib provides:
   - `infer_shape(parse_pipeline) → dict[str, type]`
   - `Spec.validate_input_shape(shape) → errors`
   - Fail fast at DSL parse time

3. **Tick.since** — Add period start timestamp for fidelity traversal:
   - `Store.facts_between(since, ts)` returns facts in period
   - Enables full-fidelity descent into tick's history

4. **DSL CLI** — Commands for working with .loop/.vertex files:
   - `loop validate`, `loop test`, `loop run`, `loop compile`

## Open Threads

- **Fidelity implementation** — Tick as handle to period is conceptual. Need
  Store.facts_between() and Tick.since to make traversal concrete.

- **String structure** — observer, kind, origin are strings. May need namespacing
  (kyle/monitor), hierarchies (disk.usage), or chaining later.

- **Consumer logic** — Fold ops accumulate, but ranking/sorting for display is
  still custom code. Right boundary?

- **Store policy** — Not every vertex needs full history. Options: ephemeral,
  sliding window, sampling. Deferred.

## Resolved

43. ~~DSL design research~~ — YAML format, .loop + .vertex files, dict-per-op parse
    syntax, parse-time validation. Design at `.subtask/tasks/research--loop-dsl-design/PLAN.md`

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
