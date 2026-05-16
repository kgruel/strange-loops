# Changelog

## 2026-05-16

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
