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

## Run Guide

Quick start for recent features.

### Live Source→Vertex Pipeline

Real shell commands (`df`, `ps`) flowing through the full pipeline:

```bash
uv run python experiments/source_vertex/viz.py
```

Watch facts stream in, folds accumulate, ticks fire on boundaries.

### Nested Vertex Discovery

The DSL supports `discover:` for auto-finding child vertices:

```
# root.vertex
discover: ./infra/*.vertex
discover: ./personal/*.vertex
```

Try the nested flow example:

```bash
uv run loop compile experiments/nested_flow/root.vertex
```

Shows the full vertex tree: root discovers `infra/disk.vertex` and `infra/proc.vertex`.

### DSL CLI

```bash
uv run loop validate disk.loop      # syntax check
uv run loop run disk.loop           # execute, print facts
uv run loop compile system.vertex   # show compiled structure
uv run loop start system.vertex     # run the vertex (blocks)
```

### TUI Experiments

```bash
uv run python experiments/cadence_viz.py      # nested temporal cascade
uv run python experiments/fidelity_lens.py    # zoom-to-fidelity lens
uv run python experiments/personal_scale/main.py  # heterogeneous domains
```

### Homelab Monitoring

```bash
uv run loop start experiments/homelab/root.vertex
```

Real SSH-based monitoring (needs SSH key auth to targets). Shows nested vertices,
source errors collected and displayed via `source.error` loop.

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
| `cadence_viz.py` | Nested cascade — pulse→breath→minute with feedback loop |
| `nested_flow/viz.py` | Sibling fan-out — root→{timers,sources,infra} |
| `source_vertex/viz.py` | Live Source→Vertex wiring — real commands through Runner |
| `personal_scale/main.py` | Heterogeneous domains — disk,proc,email,calendar through root |
| `homelab/` | Real homelab monitoring — SSH sources, nested vertices, error handling |

## Current Focus: Vertex Nesting + Composition

Vertices nest. Child ticks become facts to parent. No broker — hierarchy is composition.

```
┌─ root.vertex ─────────────────────────────────────────────────┐
│   discover: ./infra/*.vertex                                  │
│   discover: ./personal/*.vertex                               │
│                                                               │
│   ┌─ infra.vertex ──┐     ┌─ personal.vertex ─┐              │
│   │  disk ─┐        │     │  email ─┐         │              │
│   │  proc ─┴► tick  │     │  cal ───┴► tick   │              │
│   └────────┬────────┘     └─────────┬─────────┘              │
│            │                        │                         │
│            └────────► root loop ◄───┘                        │
│                           │                                   │
│                      emit: root.tick ─────────────────────┐  │
└───────────────────────────────────────────────────────────│──┘
                                          (loop closes) ◄───┘
```

**Two mechanisms:**
- `discover:` — file hierarchy, natural grouping by domain
- `vertices:` — explicit list, cross-cutting concerns

### Decisions Made (Cadence/Source)

| Topic | Decision |
|-------|----------|
| `on:` single trigger | `on: minute` — pure signal, no payload access |
| `on:` multiple triggers | `on: [a, b]` — OR semantics |
| `on:` AND triggers | No — use fold + boundary instead |
| `on:` filtering | No — use intermediate loop to narrow fact kind |
| `on:` debounce/throttle | Defer — needs temporal boundary design |
| Tick naming | `emit:` is verbatim fact kind, user controls namespace |
| Tick lineage | `origin` field + fidelity traversal, not in name |
| Vertex wiring | Implicit by kind via nesting — no broker |

### In Flight

(none)

## Next Steps

1. **Wire routes: to runtime** — DSL parses `routes:` but mapper doesn't use it. Facts route by kind→loop name match only.
2. **Homelab SSH auth** — experiment ready but needs SSH key setup to connect to real hosts
3. **DSL-driven experiments** — migrate viz experiments to `.vertex` files where sensible

## Open Threads (Deferred)

- **String structure** — observer, kind, origin namespacing. Pattern hasn't
  emerged yet.

- **Consumer logic** — ranking/sorting for display is custom code. Right
  boundary?

- **Store policy** — ephemeral, sliding window, sampling. Use case will clarify.

## Resolved

67. ~~Homelab error handling~~ — `source.error` loop collects SSH failures. Discovered that
    `routes:` config isn't wired to runtime; workaround is naming loops to match fact kinds.

66. ~~Fix CLI discover/sources confusion~~ — `cmd_start` was using `discover:` (for vertices)
    to glob sources, then parsing `.vertex` files as `.loop` files. Fixed: `discover:` handled
    by `compile_vertex_recursive`, `sources:` handled separately with glob expansion.

65. ~~DSL: Allow @ in source strings~~ — Lexer now accepts `@` in identifiers. Enables
    `ssh user@host` syntax. Shell-safe: `@` only special with `$` prefix.

64. ~~DSL: Count-based boundaries~~ — `boundary: after 10` (one-shot), `boundary: every 50`
    (repeating). Parsed as identifier values to avoid conflict with `every:` config key.
    Full implementation across AST, parser, mapper, Loop, Vertex. +362 lines.

63. ~~DSL: Avg and Window folds~~ — `avg field` for running average, `window N field` for
    sliding buffer. Hidden state (sum/count) managed internally. +399 lines, 12 new tests.

62. ~~Experiment: Homelab monitoring~~ — `experiments/homelab/` with 12 DSL files. Local
    monitoring works, SSH sources need auth. Discovered gaps: no JSONPath, routes not wired.

61. ~~DSL: discover: for nested vertices~~ — `discover:` glob patterns for `.vertex` files.
    Filters properly, handles self-reference, deduplicates with explicit `vertices:`.
    Updated nested_flow experiment to demonstrate. 7 new tests.

60. ~~Experiment: Source→Vertex wiring~~ — `experiments/source_vertex/viz.py` shows full
    pipeline: real commands (df, ps) → parse → Fact → Runner → Vertex → Tick. Live TUI.

59. ~~Experiment: Personal scale~~ — `experiments/personal_scale/` with heterogeneous
    domains (disk, proc, email, calendar) through infra/personal vertices to root. TUI.

58. ~~Fold expressiveness research~~ — Analyzed 37 custom folds. 35% already expressible,
    14% need primitives (`Avg`, `Window`), 51% genuinely need Python. Recommendation:
    add `Avg` + `Window`, keep Python escape hatch for complex cases.

57. ~~CLI refactor: materialize_vertex~~ — `loop start` now uses `compile_vertex_recursive` +
    `materialize_vertex`. Supports nested vertices via `vertices:` and `discover:`. Reports
    nested vertices on startup. 134 DSL tests pass.

56. ~~DSL Mapper: materialize_vertex~~ — `materialize_vertex(compiled, fold_overrides=...)`
    instantiates runtime Vertex tree from CompiledVertex. Supports custom fold functions
    for domain logic the declarative folds can't express. Refactored cadence_viz.py to
    use nested vertex tree (`minute → breath → pulse`). 134 DSL tests, 213 vertex tests.

55. ~~Runtime: Vertex nesting~~ — Vertex.add_child(), accepts(kind), tick-to-fact
    conversion. Child ticks become facts to parent. Loopback prevention. 213 tests.

54. ~~DSL Mapper: on:, timers, vertices:~~ — Source.trigger field for on: kinds.
    Pure timer sources (command=None). CompiledVertex with recursive children.
    CircularVertexError for cycle detection. 129 DSL + 245 data tests.

53. ~~DSL: vertices: syntax~~ — Add `vertices:` to VertexFile for explicit child
    vertex paths. `discover:` handles both `.loop` and `.vertex` by extension.
    Renamed `parse_sources_list` → `parse_path_list`. 120 tests.

52. ~~DSL: on: trigger syntax~~ — Add `on:` for triggered sources. Single trigger
    `on: minute`, OR triggers `on: [a, b]`. Pure timer loops (no source, just
    `every:`). Mutual exclusivity validation. `Trigger` type in AST. 115 tests.

51. ~~Doc audit~~ — 6 archived, 2 removed, 8 revised. Shape→Spec, 5→3 atoms.
    PEERS.md rewritten as IDENTITY.md. New accurate root README.

50. ~~Cadence visualization~~ — Animated TUI proving Cadence/Source split.
    Pulse→Breath→Minute hierarchy with feedback loop. Two-column layout.
    `experiments/cadence_viz.py`.

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
