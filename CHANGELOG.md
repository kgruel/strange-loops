# Changelog

## 2026-05-17

### Read: trace dissolves into read --diff [--refs N]

The `trace` verb shipped 2026-05-16 retires this session — its
capabilities absorbed entirely into `read`. Five-phase landing per
decision `design/trace-dissolves-into-read-with-unified-refs`. Trace
hadn't shipped externally, so this is a clean cut with no deprecation.

- **`--refs [N]` unified** (A1) — bare `--refs` walks depth 1 and
  decorates inbound/outbound edges; `--refs N` walks N hops. Replaces the
  pre-existing render-side `--refs` toggle (which filtered to ref-having
  items only — that behavior is retired; orphans now render unchanged).
  Single semantic, fetch-side walk + render-side decoration.
- **Walk semantics in `fetch_fold`** (A2) — new `atoms.WalkedItem` lives
  parallel to primary sections in `FoldState.walked` (back-compat
  default = empty tuple). Walked items carry `via_anchor` and `depth` so
  the lens renders the lineage chain. Cycle-protected, cross-kind
  capable. Lens renders walked items under a `## REFS (N)` section with
  `┄ via → kind/anchor-key` markers attributing every walked row to its
  parent — resolves `friction:trace-refs-no-visual-marker`.
- **Positional `kind/key` on `read`** (B) — `sl read project
  decision/design/foo` parses as the equivalent of `--kind decision
  --key design/foo`. Disambiguates against file-path vertices via
  `_looks_like_vertex_path()` heuristic (absolute, `./`-relative, or
  `.vertex` suffix → path; otherwise slash means entity). The B
  implementation caught a 21-test cascade on first attempt where file
  paths were misclassified as entities — fixed and locked with new
  `TestLooksLikeVertexPath` regression tests.
- **`--diff` routing** (C) — `sl read project kind/key --diff` renders
  the entity's cumulative field-deltas (status: open → partial, refs:
  +added -removed). Routes through `fetch_trace` + `trace_view` with
  `_diff=True` — the lens code stayed; only the verb wrapper went away.
  Under `--diff --refs N`, the diff accumulator partitions per entity.
- **`trace` verb deleted** (D) — removed `_run_trace` (171 LOC) and
  `lenses/trace_index.py` entirely. Removed from `_VERBS`, `_VERTEX_OPS`,
  verb-first dispatch, vertex-op dispatch, and main help. `lenses/trace.py`
  (the diff renderer) kept — read invokes it directly.
- **`arcs-block.py` hook updated** — `sl trace project thread/X --diff
  --plain` → `sl read project thread/X --diff --plain`. One-line swap as
  predicted in the dissolution-test report.

The friction list cleared along the way: `default-read-flow-too-limiting`
(read is now the primary access verb with full ergonomic coverage),
`trace-refs-no-visual-marker` (graph-render with via-markers),
`refs-flag-unification-and-propagation` (both render-side and fetch-side
collapsed into one `--refs [N]` semantic).

Regression bar: 14 new tests added across `TestExtractRefsDepth`,
`TestRunFoldRefsBothPaths`, `TestLooksLikeVertexPath`, and
`TestFetchFoldRefsWalk`. The asymmetric-pair pattern from yesterday's
exercising-catches-coherence-gaps growing edge fired three times during
landing: once on `_is_static_plain` checking already-stripped rest
(caught immediately), once on file-path-as-entity misclassification
(caught by 21 cascading test failures), and once on `--diff` needing an
entity (caught at design time). All locked with regression tests.

Net diff: +442 / -283 lines on the trace dissolution itself; one new
atom (`WalkedItem`); one deleted lens (`trace_index.py`); zero new CLI
verbs (one removed).

## 2026-05-16

### Substrate: ULID id generation restored

- **`engine._gen_id()` → `str(ULID())`** — restores time-sortable
  (lexicographic order matches generation time) and within-millisecond
  monotonic id generation via `python-ulid` (pure Python, no C extension,
  ~2.3μs per id). The prior `uuid.uuid4()` implementation produced random
  ids — `ORDER BY id` was meaningless, breaking cross-store interleaving
  and any downstream consumer that assumed id-as-chronological-key. Single-
  store ordering survived only because `since()`, `replay_cursor`, and
  `facts_by_kind` all sort by `rowid` (captured as observation
  `architecture/rowid-is-load-bearing-for-single-store-ordering`).
- **Schema cleanup** — dropped vestigial `DEFAULT (ulid())` from engine and
  store schemas. All INSERTs supply id explicitly (engine via `_gen_id()`,
  store via `SELECT * FROM src.facts` through `ATTACH DATABASE`) so the
  SQL-callable `ulid()` function is no longer needed.
- **`sqlite-ulid` dep removed** — from `libs/engine`, `libs/store`, and
  top-level `pyproject.toml`. 15 transitive packages purged. python-ulid
  was already a top-level dep (used by `libs/sign` for JTI generation).
- **Regression bar added** — engine `TestIdGenerationContract` (3 tests:
  ULID format, within-store id-order matches emission order, cross-store
  id-order interleaves chronologically). Store `TestMergeViaProductionEmitPath`
  (3 tests exercising merge through `SqliteStore.append()` rather than
  via test fixtures that previously bypassed the production id path —
  the structural gap that hid the prior regression).
- **Existing stores** — facts emitted prior to this change keep their
  original ids (no migration). Mixed-format histories are tolerated; new
  emits restore the time-sortable property going forward. A future
  migration may rewrite legacy ids if downstream consumers need uniform
  chronological-by-id semantics across the full history.

Resolves `friction:ulid-regressed-to-uuid4-in-sqlite-store`. See decision
`architecture/id-primitive-python-ulid` for rationale.

### Lens: deliberation depth (structural overfit detector)

- **`--lens deliberation`** — reads `--facts` for status-bearing kinds
  (hypothesis, thread, friction, task) and counts status transitions per
  fold key. Status entries that landed at a terminal state with one or
  fewer transitions surface as SUSPICIOUS — too clean to be real
  deliberation. Captures the "suspicious-cleanness as overfit-check"
  principle (peer-converged with alcove 2026-05-10) as a structural
  read-path feature rather than a manual noticing skill.
- **Calibration** — initially flagged `emit_count<=2` then tightened to
  `<=1` after advisor-driven re-inspection showed legitimate one-hop
  resolutions were getting false-flagged.

### Session-start: ARCS context + surface trim

- **ARCS section injected** — `.claude/hooks/arcs-block.py` (invoked by
  `session-start.sh`) renders the top 2 multi-fact open threads via
  `sl trace --diff`, capped at 30 lines per arc. First session where the
  session prompt context is composed by sl trace verb output — three-
  layer recursion: trace verb shipped this session renders the diff that
  becomes next session's context.
- **Discipline lenses co-located** — moved from `~/.config/loops/lenses/`
  to repo-local `<repo>/.loops/lenses/` (with symlinks back at originals
  for back-compat). Session-landing and reconcile lenses now version-
  controlled with the code that consumes them.
- **Surface trim** — pruned redundant sections from session-start prompt
  to make room for ARCS without inflating total context.

### Trace: kind/key lifecycle as a top-level verb

- **`sl trace <kind>/<key>`** — walks a single fold-key entity's source
  facts in ASC order (changelog-style, oldest first). Built on
  `vertex_fold(retain_facts=True)` and `FoldState.source_facts`, which
  already grouped raw facts by fold position — trace is mostly wiring,
  not new fetch infrastructure. Works both verb-first (`sl trace
  decision/design/foo`) and vertex-op (`sl project trace ...`).
- **`--refs`** — walks the outbound ref graph one hop. Each fact's `ref`
  field (`kind:key,kind:key`) names entities to pull into the trace.
  Cycle-protected via visited set keyed on `kind/key` addresses.
- **`--depth N`** — recurses N hops along the ref graph (`--refs` is
  shorthand for `--depth 1`). At depth=2 a single thread surfaces its
  full causal subgraph — design decisions, frictions, hypotheses, all
  the entities it references transitively.
- **`--diff`** — renders cumulative field-deltas instead of full
  snapshots. First fact shows `field: . → value`; subsequent facts show
  only `field: old → new` for changed scalars and `+added / -removed`
  for ref-set deltas. Under `--refs`, the diff accumulator partitions
  per entity — each entity's facts diff against its own prior, not the
  merged stream. Works because fold-merge means each emit's payload IS
  the patch it applied.
- **Empty handling** — trace has no time-window; "no lifecycle found
  for kind/key" rather than the misleading "no facts in the given time
  range" that `stream_view` would emit.
- **Combine aggregator transparency** — `_combined_read` extended with
  `return_payloads` so `retain_facts=True` flows through the combine
  branch of `vertex_fold`. From cwd, `sl trace thread/foo` walks the
  `.loops/.vertex` aggregator end-to-end without needing the explicit
  child-vertex form. The previously-planned `--all` flag dissolves —
  the aggregator IS the cross-vertex mechanism.
- **Engine bug fix in passing** — `fetch_fold` previously stripped
  `source_facts` when filtering by `--key`, making `retain_facts=True +
  key=…` a silent no-op. Regression test pinned.
- **`observation` kind declared on project vertex** — runbook lists it
  as a valid intent; vertex didn't declare it; recovered 30+ orphaned
  observations into the fold via single-line vertex change.

Resolves `friction:lineage-view-missing` (all in-scope strands) and
`friction:trace-combine-vertex-silent-empty`. 749 engine tests + 1056
loops tests pass (7 new this campaign).

### Emit Receipt + Fold Merge

- **`emit-receipt-on-write`** — every `sl emit` prints a receipt to stderr:
  success line `stored: kind/key @ <ulid>` plus WARN lines for
  kind-not-declared, fold-key-missing, and unresolved refs. Closes the
  verify-as-you-emit gap — silent-loss bugs that previously took a session
  boundary to surface are now visible in-moment. `-q/--quiet` suppresses
  the success line only; WARN/ERROR always print.
- **Vertex-declared strict** — `strict true` in a `.vertex` spec makes all
  emits refuse on validation failure (exit 2, fact not stored). No CLI
  override. `LOOPS_EMIT_STRICT=1` and `--strict` provide per-call /
  per-session opt-in for vertices that don't declare it.
- **Fold-merge default** — `_make_upsert` flipped from replace to merge
  semantics. Re-emit with subset payload preserves prior fields. Dissolves
  the patch-emit friction entirely: `sl emit project friction name=foo
  status=resolved` works as a partial patch with no new subcommand.
  Touches every fold-by kind across the codebase — load-bearing semantic
  change. Trade-off: cannot unset a field by omission (use explicit
  clear sentinel).
- **`observation` kind** added to meta vertex. Runbook updated with the
  `friction-emits-in-moment` principle.

## 2026-05-15

### Read-path access primitives

- **`--key <prefix>`** on `loops read` — kind-aware fold-key filter, prefix
  matching (case-insensitive). Works with or without `--kind` (cross-kind
  filters every section by its own declared `key_field`). Full key matches
  exactly its own item (degenerate prefix case).
- **`--kind kind/key` embedded syntax** now does prefix matching too
  (back-compat: equality is the degenerate prefix case — existing exact-match
  usages unchanged).
- **`call_lens_fetch`** in `lens_resolver` — inspects lens fetch signature;
  passes only kwargs the lens declares. Symmetric to `call_lens` on render
  side. Real `TypeError` from lens body propagates instead of being swallowed.

## 2026-03-22

### Autoresearch: Test Coverage Campaign (#001)

218 autonomous experiments across 4 libraries. Monorepo coverage: 75.4% → 98.5%.

| Package | Before | After | Miss |
|---------|--------|-------|------|
| loops | 60.3% | 100.0% | 0 |
| atoms | 92.1% | 99.1% | 8 |
| engine | 87.1% | 95.1% | 129 |
| lang | 90.2% | 99.5% | 6 |
| store | 99.6% | 99.6% | 1 |

- 2,432 tests, 25,236 test LOC, 4.3s total runtime
- 44 dead code lines removed from source (9 files)
- Test infrastructure: `VertexTopologyBuilder`, shared fixtures, `builders.py`
- `autoresearch.sh` timing/coverage separation (1.7x instrumentation overhead fix)
- Campaign archive: `docs/autoresearch/`

### CLI Architecture

- **Extract commands from main.py** — `main.py` 3,469 → 1,411 lines. `emit`, `init`, `sync`,
  `devtools`, `resolve` extracted to `commands/`. CLI error hierarchy added.
- **Session startup rebuild** — `session_start` lens + ticks listing for hook context.

## 2026-03-19

### Fold Lens Redesign

- **Namespace grouping** — items grouped by `kind/namespace` prefix, sorted by salience.
- **Salience windowing** — high-touch items (n > 1) and connected items (refs) surface first.
- **FoldPalette** — semantic color roles instead of hardcoded styles.
- **Block composition** — lens builds `Block` tree instead of string concatenation.

### Visibility Layers

- **`--refs`** — filter to connected items, show edge badges (→N), ref graph tree.
- **`--facts`** — inline source facts from fold replay, filter to sections with compression history.
- **`--ticks`** — tick dashboard with compression bars, density sparkline, boundary info.
- **Metadata badge** — `[×N ←N recency]` as consistent indicator pattern across layers.

### FoldItem Extensions

- **`n` (observation count)** — how many facts compressed into each keyed entry. Surfaced as ×N.
- **`refs` (outbound references)** — accumulated from `ref=` payload values. Comma-separated emit syntax.
- **Unfolded kinds** — surface what the store has but the vertex doesn't declare.

## 2026-03-15

### Performance

- **Fast read path** — bypass CLI framework for `--static --plain` fold reads.
- **Lazy imports** — `cmd_emit` import cost 88ms → 3.5ms (95% reduction).
- **SQL batching** — `_combined_read` single query, `vertex_fold` removes ORDER BY.
- **Deferred imports** — Tick, StoreReader, argparse, painted deferred until needed.
- **painted fast paths** — ASCII and width-1 Unicode fast paths in `row_visible_text`.

### Infrastructure

- **Workspace topology** — root `.vertex` aggregation + local vertex resolution.
- **Named combine entries** — `as=` alias for child vertex access in combine blocks.
- **Worktree-safe run clauses** — boundary `run` commands work in isolated worktrees.
- **Layer boundary enforcement** — store must not access projection internals (static analysis tests).

## 2026-03-01

### painted Extraction

- **Standalone repo** — painted extracted to git submodule, published to PyPI.
- **GitHub Actions** — publish workflow for PyPI trusted publisher.

## 2026-02-25

### CLI & Rendering

- **Store lens** — facts-first fidelity levels, palette, content gist.
- **Interactive TUI** — `store -i` explorer, `dashboard -i` live refresh.
- **Session tracking** — `session.vertex` for project-level session facts.
- **strange-loops** — zoom-aware lenses for all 6 display commands.
- **Progressive CLAUDE.md** — level-based agent discovery for each lib/app.

### Sources & Ingestion

- **Telegram + Discord archivers** — polling-based message ingestion.
- **Runner fairness** — `yield_every` prevents burst source starvation.
