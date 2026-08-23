# Post-simplify re-review — codex sol LOW — slice D quality pass

## 1. Anchor
Branch slice/D-simplify, tip 085f3fac. Diff: git diff feat/arrival-libs...085f3fac
(exclude SIMPLIFY-REPORT.md). This is a QUALITY pass over already-converged
code — 4-angle review composed by the arbiter, applied by one opus agent. A
quality pass that touches code reopens the review obligation; in a prior arc
the simplify pass introduced the arc's only regression. That is what you are
hunting: regressions INTRODUCED by refactoring.

## 2. What changed (7 rulings, 5 commits)
- S-1 _stamp_coordinate_axis helper (4 sites collapsed).
- S-2 FACT/TICK_COLUMN_INDEX maps (3 derivation sites collapsed).
- S-3 per-connection coordinate-schema verification cache.
- S-4 BEHAVIOR-ADJACENT: Projection cursor role split — events_folded counter
  added; cursor now assigned only from store returns; the tuple-increment
  branches DELETED (they fabricated coordinates — latent bug); vertex.py
  boundary reads events_folded; NotImplementedError guard removed with its pin
  replaced by a mixed-usage regression test (mutation-proven by the apply
  agent).
- S-5 since/since_raw/since_with_cursor/replay_cursor/ticks_since collapsed
  onto _cursor_bounds + _rows_since(table) (fifth copy found in ticks_since —
  deviation, arbiter-endorsed). since_raw kept (live vertex.py caller).
- S-6 CLI verify prose templated (mode-conditional vocabulary, meaning pinned
  by WP-4 tests).
- S-7 _read_absorption_state ordering helper (PRAGMA check factored, 2 calls).

## 3. Review focus
S-3: can the cache go stale in a way the old re-verification caught (rebuild
on the SAME connection, cross-connection writers)? S-4: every .cursor consumer
audited? events_folded vs cursor divergence on the advance() path? S-5: exact
row-shaping equivalence for all five wrappers (LIMIT/streaming semantics —
replay_cursor claims it still streams; verify no materialization crept in).
Suites are green (engine 1894+1skip incl. the new S-4 test, all others at
baseline) — spot-verify only.

## 4. Verdict format
Findings SOL-SIMP-NN; overall PASS/FAIL. One response.
