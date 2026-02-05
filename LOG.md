# LOG

Session history for the monorepo. What happened when. Per-experiment insights
live in `experiments/LOG.md`.

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
