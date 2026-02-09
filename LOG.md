# LOG

Session history for the monorepo. What happened when. Per-experiment insights
live in `experiments/LOG.md`.

---

## 2026-02-08 — Vocabulary revision + library renames

**The session.** Four-agent team (siftd + muser + cold-reader + lead) for
vocabulary alignment. Started with stale VOCABULARY.md entries, ended with a
full restructure and three library renames.

**Key outcomes:**

1. **New one-liner:** "The cycle is the unit of computation." Replaced the
   mechanism-first description ("Facts flow into Vertices...") with the
   system's bet about the world. Cold reader (zero-context Opus agent)
   produced this — asked "what bet does loops make?" and the mechanism
   descriptions stopped mattering.

2. **Document restructured as zoom progression:** Bet → Frame → Atoms → Rules
   → Libraries → Examples → Dissolutions. Mirrors the system's own zoom levels
   (MINIMAL/SUMMARY/DETAILED). The document eats its own dogfood.

3. **"loop" elevated to first-class concept.** The system was named after
   something its vocabulary didn't define. A loop is one complete cycle:
   observe, accumulate, conclude. The composition of Fact + Spec + Tick.

4. **Atoms now carry enforcements.** Each atom states what it IS, what it
   PREVENTS, and why it's separate. The Tick→Fact merge was confirmed as
   resolved (Jan 27 decision, not an open question).

5. **Self-feeding risk named (Rule #7).** When conclusions feed back as
   observations, the system can amplify its own output. "Meditation vs
   hallucination." Cold reader identified this independently with zero
   context, validating it as a fundamental concern.

6. **Library renames merged:**
   - `libs/data` → `libs/atoms` (+186 -186, 82 files)
   - `libs/dsl` → `libs/lang` (+98 -98, 30 files)
   - `libs/vertex` → `libs/engine` (+197 -197, 101 files)

7. **Type-level amnesia, metadata-level memory.** Named the tick→fact
   conversion design choice: the type system forgets (a Tick becomes a Fact),
   but provenance is preserved (origin→observer).

**Agent team pattern validated:** cold reader (zero context, pattern
recognition) + muser (questions only) + siftd (historical search) +
lead (synthesis). The cold reader was the session's biggest catalyst —
produced "the cycle is the unit of computation" and identified the
self-feeding risk, both from two sentences of input.

**Post-rename audit** subtask drafted and in progress for full repo coherence sweep.

---

## 2026-02-07 — Ticks-first store explorer refactor

**The change.** Reoriented the store viewer around ticks (conclusions) instead
of presenting facts and ticks as peers. Facts are reachable through fidelity
drill, not listed alongside ticks.

- `store_reader.py` — Added `tick_timestamps(name, limit)` for sparkline data.
  Raw SQL, no payload parsing.
- `commands/store.py` — Added `_bucket_timestamps()` and `_sparkline_str()`
  sparkline helpers. Fetcher restructured: zoom >= 1 computes sparkline +
  payload_keys per tick name.
- `tui/store_app.py` — `StoreExplorerState` simplified: removed `kinds` field,
  `selected_is_tick()`, `selected_tick_name()`. Everything is a tick. Left panel
  renders rich multi-Span Lines (name + sparkline + count + freshness). `f` key
  always works. Panel width wider. Adaptive chrome: drops gaps then header as
  terminal shrinks.
- `lenses/store.py` — MINIMAL: `"3 boundaries, 36 ticks, 200 facts"` (ticks
  before facts). SUMMARY: tick table with sparkline + count + freshness +
  payload keys, facts as footer line. New `_tick_table()` renderer. FULL: fact
  payloads at zoom 2 (actual values, not repeated key names).
- Tests updated: sparkline tests, ticks-first state tests, removed stale
  kind-list tests. 48 tests pass.

**Dissolutions surfaced:**
- **Fidelity → lens + zoom.** The UX concept of progressive commitment
  (pipe to jq / scan terminal / interact) is already what lenses do with a
  zoom parameter. Same signature: `(data, zoom, width) -> Block`. No new atom.
- **Live vs stored → refresh loop.** SQLite concurrent readers mean the store
  IS the abstraction boundary. A viewer that polls the store is already a live
  viewer. No separate live mode needed.

**Loops app identity clarified:** The general-purpose CLI for the loops system,
not just DSL tooling. Libs stand alone; loops composes them.

---

## 2026-02-07 — Store viewer: `loops store`

**The change.** Read-only store inspection, properly layered.

- `engine/store_reader.py` — `StoreReader(path)`, read-only SQLite inspector.
  `PRAGMA query_only=ON`. No serialize/deserialize — pure SQL over raw columns.
  Provides `summary()`, `fact_kind_stats()`, `tick_name_stats()`, `recent_ticks()`,
  `recent_facts()`. The "Tailer" side of the Store/Tailer split.
- `loops/commands/store.py` — Data fetch layer. `resolve_store_path()` handles
  .vertex → AST → store path resolution. `make_fetcher(path, zoom)` returns
  zoom-aware fetch: aggregates at zoom 0-1, tick payloads at 2, fact payloads at 3.
- `loops/lenses/store.py` — Render layer. `store_view(data, zoom, width)` →
  Block. MINIMAL = one-liner, otherwise shape_lens.
- `loops/main.py` — Thin `cmd_store` wiring fetch → render. `store` subcommand
  with full cells fidelity args (-q/-v/--json/--plain).
- Follows hlab's three-layer pattern: command (fetch) / lens (render) / main (routing).

Architectural insight from team research: Store's verbs are append, query, replay.
The store viewer exercises the **query** verb at variable fidelity. Fidelity is
traversal depth — zoom maps to how deep you go into a tick's period. The Store IS
the fidelity mechanism. `StoreReader` is the query path; `SqliteStore` is the
append path. Different concerns, different objects.

10 new StoreReader tests. 20 existing SqliteStore tests unchanged.

---

## 2026-02-07 — Decouple DSL from runtime

**The change.** `lang` becomes pure grammar (zero deps beyond ckdl). The compiler
backend and CLI move out to where they belong.

- `dsl/mapper.py` → `engine/compiler.py` (DSL AST → runtime types)
- `dsl/program.py` → `engine/program.py` (VertexProgram, load_vertex_program)
- `dsl/cli.py` → `apps/loops/main.py` (new workspace member, entry point `loops`)
- `lang` deps: `[data, engine, cells]` → `[ckdl]`
- `hlab` drops direct dsl dependency, imports compiler symbols from engine
- Experiments split imports: grammar from dsl, compilation from engine
- Vertex internals: `register()` unified onto Loop (deleted `_FoldEngine`),
  `Tick.to_dict/from_dict`, `SqliteStore` for tick persistence, `_store_tick()`

Dependency graph: `dsl→ckdl`, `engine→data,dsl`, `apps/loops→dsl,data,engine,cells`,
`hlab→data,engine,cells`. 435 tests (dsl 84, engine 332, loops 19).

(`03d6bda`, `e000bf1`, `96361c2`)

---

## 2026-02-05 — Default rendering in DSL CLI (Step 4)

**The change.** Wired cells fidelity system into `loop start`, completing the
4-step spec-first plan.

- `add_cli_args(start_parser)` adds `-q`/`-v`/`-vv`/`--json`/`--plain`/`--static`/`--live`/`-i`
- `detect_context()` resolves zoom/mode/format from TTY state + terminal size
- `shape_lens` renders tick payloads as structured blocks at zoom level
- JSON → `json.dumps`, MINIMAL → one-liner, default → styled blocks per tick

All 4 steps of the spec-first plan now shipped. (`93cac43`)

---

## 2026-02-04 — Spec-first: parse extensions + fold override deletion

**The arc.** Multi-session plan to make the DSL expressive enough to replace
Python fold overrides. 5 of 6 hlab fold overrides were JSON extraction pretending
to be computation. Replaced them with declarative parse pipelines.

**Steps completed across sessions:**

1. **Runner unification** — `VertexProgram.run()`/`collect()` + `load_vertex_program()`
   wired into DSL CLI. One code path, not two. (`bbbca14`)
2. **Store wiring** — `.vertex store` threads through compilation to runtime. (`bbbca14`)
3. **KDL migration** (unplanned) — Replaced hand-rolled lexer/parser with ckdl.
   Orthogonal to the plan but landed mid-stream. (`b171570`)
4. **Parse extensions** — `Explode` (array fan-out with carry), `Project` (field
   mapping with nested JSON paths), `Where` (record filtering). `run_parse_many()`
   for one-to-many parse pipelines. `resolve_path()` for dot-separated JSON
   traversal. Source detects multi-fact pipelines and emits N facts per record.
5. **Loop file rewrite** — All 5 Prometheus/Radarr `.loop` files now declare full
   extraction pipelines. You can read a `.loop` file and know exactly what the
   tick payload will contain — no Python required.
6. **Fold override deletion** — Deleted `alerts_fold`, `rules_fold`, `targets_fold`,
   `movies_fold`, `quality_fold` + `ALERTS_INITIAL`, `MEDIA_AUDIT_INITIAL` (~120 lines).
   Only `health_fold` remains (computes derived metrics).
7. **Command rewiring** — `alerts.py` and `media_audit.py` no longer pass fold
   overrides. `_load_program()` is now a one-liner in both.

**The `alerts_count` edge case.** `rules.loop` projects `alerts` (a list from the
API), but `AlertRule` expects `alerts_count: int`. Bridge in consumption code:
`len(r.pop("alerts", []))`. Parse extracts structure; domain computes derived values.

**The line.** If it's "extract field X from path Y" → parse. If it's "compute Z
from accumulated state" → fold. `health_fold` is the latter. The other 5 were the
former.

**Result:** 286 data tests, 182 DSL tests. +1052/-205 across 23 files.

---

## 2026-02-03 — DSL source templates

**The feature.** Parameterized source templates. A vertex declares a parameter
table; a loop file becomes a template with `${var}` placeholders. The loop spec
(fold + boundary) is also defined once alongside the template.

**Before (4 files, 35 lines in vertex):**
```
├── stacks/infra.loop       # source: ssh deploy@192.168.1.30 "cd /opt/infra..."
├── stacks/media.loop       # source: ssh deploy@192.168.1.40 "cd /opt/media..."
├── stacks/dev.loop         # source: ssh deploy@192.168.1.41 "cd /opt/dev..."
├── stacks/minecraft.loop   # source: ssh deploy@192.168.1.42 "cd /opt/minecraft..."
└── status.vertex           # 4 sources + 4 identical loop definitions
```

**After (2 files, 25 lines in vertex):**
```
├── stacks/status.loop      # source: ssh deploy@${host} "cd /opt/${kind}..."
└── status.vertex           # 1 template source with parameter table + 1 loop spec
```

**Syntax:**
```yaml
sources:
  - template: stacks/status.loop
    with:
      - kind: infra
        host: 192.168.1.30
      - kind: media
        host: 192.168.1.40
    loop:
      fold:
        containers: collect 50
      boundary: when ${kind}.complete
```

**Implementation:**

1. **AST** — `SourceParams`, `TemplateSource` types. `VertexFile.sources` now
   `tuple[Path | TemplateSource, ...]`.

2. **Lexer** — `TEMPLATE`, `WITH`, `LOOP` tokens. Extended identifier parsing
   to handle `${var}` inline (e.g., `deploy@${host}`). Added standalone `${}`
   handling for `${kind}.complete`.

3. **Parser** — `parse_sources_block()` handles both paths and templates.
   `parse_with_block()` for parameter tables. `loops:` now optional when
   template sources provide loop specs.

4. **Mapper** — `substitute_vars()` replaces `${var}` with values.
   `instantiate_template()` creates LoopFile with substituted variables.
   `compile_sources()` returns `(sources, specs)` — sources for the runner,
   specs generated from template loop blocks.

**Result:** 180 DSL tests pass. hlab produces identical output. Next session:
iterate on render UI.

---

## 2026-01-31 — Vertex nesting + DSL completion

**Cadence/Source decisions finalized:**
- `on:` single trigger — pure signal, no payload access for now
- `on: [a, b]` — OR semantics (either triggers)
- AND triggers — no, use fold + boundary (it's a fold concern)
- Filtering — no, use intermediate loop to narrow kind
- Debounce/throttle — defer, needs temporal boundary design
- Tick naming — `emit:` is verbatim fact kind, user controls namespace
- Tick lineage — `origin` field + fidelity traversal, not encoded in name

**Vertex wiring — implicit by kind, no broker:**
- Rejected broker/pub-sub model — adds external coordination
- Vertices nest via `vertices:` or `discover:`
- Child ticks become facts to parent automatically
- Children self-describe inputs via routes + loop triggers
- Parent forwards facts to children that accept them
- Same mechanism at every level — nesting is composition

**DSL merged:**
1. `on:` trigger syntax — `on: minute`, `on: [a, b]`, pure timers
2. `vertices:` — explicit child vertex paths, mirrors `sources:`
3. `discover:` works with `.vertex` patterns (extension-based dispatch)

**Vision clarified:** Same model serves both ends:
- Systems scale: CLI-driven, high-volume, infrastructure monitoring
- Personal scale: progressive, heterogeneous life dashboard
  - homelab alerts, bills due, social reminders
  - folder hierarchy = semantic grouping
  - ticks bubble up, root = "what matters now"

**In flight:**
- runtime/vertex-nesting — Vertex children, tick-to-fact
- dsl/mapper-updates — Compile new DSL features
- experiment/nested-flow-viz — Animated visualization (deferred)

---

## 2026-01-31 — Cadence/Source split + doc cleanup

**The insight.** Source has two concerns: **what** to observe (command, API,
nothing) and **when** to observe (interval, event trigger). These should be
separate concepts.

**Cadence** = when. Can be:
- `every 10s` — simple interval
- `on: minute` — triggered by fact
- Complex loop with its own boundaries

**Source** = what. Can be:
- Shell command, API, stream
- Nothing (pure timer)

**Timer as fact.** A timer is a loop with cadence but no source — emits
time-shaped facts. Other loops trigger `on:` those facts. The clock is just
another data source. Runtime simplifies to uniform receive → route → fold.

**Backpressure discussion.** Started unpacking what happens when triggers fire
faster than sources execute. Leaning toward: no special mechanism — a busy
source emits `trigger.skipped` facts. Observable, composable, consistent with
"failures are just more facts."

**cadence_viz experiment.** Animated TUI showing the pattern:
- Pulse (1s) → Breath (5 pulses) → Minute (12 breaths)
- Feedback loop: minute variance → rate adjustment → pulse interval
- Visual: pulse dots, breath circles, health gauge, fact stream, sparkline
- Proves: timer cascade works, ticks compose, feedback is just more facts

**Doc audit.** Aggressive cleanup:
- 6 files archived (5-atom model docs, strata-specific)
- 2 files removed (stale README, PLAN)
- 8 files revised (Shape→Spec, 5→3 atoms)
- PEERS.md → IDENTITY.md (observer field + Grant model)
- New accurate root README.md

**Open questions captured:**
1. Sugar vs explicit — should `every: 10s` auto-create timer?
2. Multiple triggers — `on: [a, b]` = OR or AND?
3. Feedback loops — A → B → A allowed? (yes, detection is tooling)
4. Backpressure — source emits status facts, no special mechanism

See `docs/CADENCE.md` for the design, `experiments/cadence_viz.py` for proof.

---

## 2026-01-31 — Fidelity-aware Lens

**The experiment.** Zoom level maps to fidelity depth. Build pipeline domain
with nested phase ticks (lint, compile, test, package).

| Zoom | Fidelity |
|------|----------|
| 0 | Minimal — just `✓ build` |
| 1 | Summary — payload fields |
| 2 | Expanded — nested ticks as icons |
| 3 | Deep — nested ticks with payloads |
| 4 | Full — nested ticks + facts via Store.between() |

**Key design:** `FidelityContent` wraps `(tick, store, nested_ticks)` — keeps
Lens stateless. Content carries its own context for traversal.

**Note:** Nested ticks are simulated (pre-built) for this experiment. Real
tick-as-fact composition is the next frontier.

---

## 2026-01-31 — Tick.since + Cells-Vertex integration

**Two experiments completed in parallel:**

1. **Tick.since fidelity traversal** — Tick is now a handle to its period.
   - `Tick.since: datetime | None` captures when period started
   - `Store.between(start, end)` retrieves facts in time range
   - Loop tracks `_period_start`, produces ticks with `since`
   - Vertex simplified: Loop is single source of truth (removed duplicate tracking)
   - Experiment: incident timeline with re-fold verification

2. **Cells-Vertex integration** — Full feedback loop closes.
   - Counter with undo (j/k to dec/inc, u to undo)
   - Keypresses → emit → Fact → Vertex.receive → fold → Tick → render → Block
   - Proves: input becomes fact, fact becomes state, state renders

**Key design decisions:**
- `tick.ts` now uses boundary fact's timestamp (not wall clock) — enables replay
- Legacy `_FoldEngine` gets no fidelity tracking (`since=None`)
- Loop encapsulates its own period tracking

191 vertex tests (was 165, +26 new).

---

## 2026-01-31 — DSL experiment: end-to-end proof

**The experiment.** Created real .loop/.vertex files for system monitoring,
ran `loop start`, watched facts flow through folds into ticks. The DSL works.

**What was built:**

- `experiments/monitors/disk.loop` — parses `df -h` into structured disk facts
- `experiments/monitors/proc.loop` — parses `ps` into top-10 process facts
- `experiments/monitors/system.vertex` — wires sources with Upsert/Collect folds

**Issues discovered and fixed:**

1. **Parser comma handling** — source commands like `ps -eo pcpu,pmem` were
   being reconstructed as `pcpu , pmem`. Fixed to preserve punctuation adjacency.

2. **Completion facts** — boundaries need a signal to fire. Source now emits
   `{kind}.complete` facts after each command execution. Data-driven boundaries.

3. **MappingProxyType in folds** — Fact payloads are wrapped in MappingProxyType
   for immutability. Collect/Upsert were storing these directly, breaking deepcopy
   on subsequent folds. Fixed to convert to dict before storing.

4. **CLI output buffering** — ticks weren't visible until process exit. Added
   `flush=True` for real-time output.

**The proof:**

```
$ loop start experiments/monitors/system.vertex
Discovered: disk.loop
Discovered: proc.loop
Starting system with 2 source(s)...
[disk] {'mounts': {'/': {'pct': 24}, '/dev': {'pct': 100}, ...}, 'updated': ...}
[proc] {'procs': [{'cmd': 'claude', 'cpu': 41.7}, ...], 'updated': ...}
```

Facts flow through parse pipelines → fold into state → trigger ticks on boundaries.
The declarative DSL compiles to runtime types and executes correctly.

514 tests passing (data: 245, vertex: 165, dsl: 104).

---

## 2026-01-29 — Framework collapse: peer-aware Vertex + Lens

**The collapse.** Experiments converged, patterns validated. Moved from exploration
to framework: `Vertex.receive(fact: Fact, peer: Peer) -> Tick | None`.

**What was implemented:**

1. **Lens in ticks** — `Lens(zoom, scope)` dataclass. Pairs with Projection
   (write-side vs read-side). Factory methods: `minimal()`, `summary()`, `detail()`,
   `verbose()`. Fluent: `with_zoom()`, `with_scope()`.

2. **Peer-aware Vertex** — `receive(fact, peer)` signature. Two gates:
   - Potential check: `fact.kind` must be in `peer.potential`
   - Observer-state ownership: `focus.kyle` can only be updated by kyle

3. **Per-peer focus pattern** — `{kind}.{peer}` for observer state. Concurrent
   peers don't conflict. ObserverState/ObserverActions protocols.

4. **Network concerns as facts** — discovery, failure, ordering, backpressure
   all map to fact kinds. Policy is composition-layer. Primitives unchanged.

**Key insight:** The signature change `receive(Fact, Peer)` makes the model
explicit. Origin (recorded provenance) vs peer (live context for gating).
On live input they match. On replay they might differ.

**New experiments:**
- `peer_focus.py` — per-peer observer state, no conflicts
- `lens_code.py` — Lens placement analysis
- `network_boundary_extended.py` — four network scenarios
- `peer_aware_vertex.py` — full model demonstration

131 ticks tests passing.

---

## 2026-01-28 — Loops model crystallized + persistence exploration

Explored adding persistence to experiments. The exploration dissolved multiple
concepts back into existing atoms:

| Concept | Dissolved into | Why |
|---------|---------------|-----|
| Sink | Fold state | Loops have no terminals |
| Store | Durable fold | Storage is a property, not a type |
| Witness | Peer + Vertex | Just a peer whose job is to observe and emit |
| Tap | Vertex | Emission from storage is vertex behavior |
| Memory | Boundary-less fold | Silent accumulation is a fold that never ticks |

**Key insight:** The atoms are complete. New requirements don't require new
primitives — they're configurations of existing ones.

Created `LOOPS.md` as the fundamental model document. Four satellite docs
added: `docs/VERTEX.md`, `docs/TEMPORAL.md`, `docs/PERSISTENCE.md`, `docs/PEERS.md`.
Each unpacks one aspect and references back to LOOPS.md.

Fixed Enter key bug in keyboard.py (handle LF 0x0A same as CR 0x0D).

Open naming tensions noted but deferred:
- "Peer" implies equality but delegation is hierarchical
- "Tick" implies clock time but boundaries are semantic

---

## 2026-01-28 — Peer-driven boundaries + None=unrestricted + lens distinction

`review.py`: two loops through one vertex. Health ticks at timer cadence
(passive). Review ticks when peer acks all containers (active — composition
layer sends `review.complete` sentinel).

**Peer model change**: `horizon` and `potential` default to `None` (unrestricted)
instead of `frozenset()` (empty). Constraints emerge through `delegate()`, not
upfront enumeration.

**Debug is a lens, not a horizon.** The None model exposed a category error:
"debug" was a horizon string alongside container names, but it's a rendering
mode, not a data domain. Debug panel is now a lens toggle available to any peer.

---

## 2026-01-27 — Boundary triggering implemented

Implemented boundary triggering on Vertex. `Projection.reset()` added.
`register()` gains `boundary: str | None` and `reset: bool`. `receive()`
returns `Tick | None`. Fold-before-boundary, optional reset, boundary kind
uniqueness enforced.

Vertex is sync by design — async bridge lives at composition point.
122 ticks tests.

---

## 2026-01-27 — Feedback loop closed, experiment log established

`experiments/observe.py`: first experiment that closes the feedback loop.
User interactions (j/k/enter) are Facts through the same `vertex.receive()`
as external observations.

Emergent insights captured in `experiments/LOG.md`: debug as horizon (not
infrastructure), meta-actions outside the loop, thin composition layer.

---

## 2026-01-27 — Genesis document + strata semantic tagging

Reconstructed project origin story via strata. Synthesized into `docs/GENESIS.md`.
Applied semantic tags to 58 conversations across workspaces.

---

## 2026-01-27 — Tick-to-Fact dissolved, fleet experiment

Built `experiments/fleet.py`: three-level vertex hierarchy (4 VMs → 2 regions
→ global). Ticks are a level above Facts — temporal groupings, not peers.
The question dissolved. Same primitive at every level.

Tick gained `origin` field. Vertex gained `name` parameter.

---

## 2026-01-27 — Architecture crystallization

Replaced Stream concept with Vertex (intersection of loops). Explored and
rejected Tick-into-Fact collapse. Tick gained `name` field. Full narrative
in `ARCHITECTURE-JOURNEY.md`.

---

## 2026-01-26 — Semantic journey

Monorepo naming exploration (loops vs volta vs prism). Pivot concept
crystallized (four universal atoms + cell as first surface). Peer refactored
to horizon + potential.

---

## 2026-01-26 — Structure alignment

Project structure normalized across all five libs. Per-lib CLAUDE.md and
HANDOFF.md added. Six parallel fixes merged.
