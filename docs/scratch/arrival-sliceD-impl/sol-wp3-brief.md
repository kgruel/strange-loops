# WP-3 pass check — codex sol LOW — slice D, D2 (seal re-base) + W2-1 cursor ruling

## 1. Anchor
Branch slice/D-wp3, tip 6dc12f15. Diff: git diff feat/arrival-libs...6dc12f15 (exclude
WP3-REPORT.md, WP3-FIX-REPORT.md). Implementer: gemini flash-high. Gate: opus,
2 rounds, PASS (GATE-WP3-REPORT.md on slice/D-wp3-gate).

## 2. Design contract (ratified)
design-proposal.md §D2 + decision:design/sliceD-w2-1-cursor-axis-ruling.
NON-NEGOTIABLE: signed bytes untouched — _tick_envelope/_fact_row_hash/
commitment hashes byte-identical (gate byte-verified all five); window_start/
fact_cursor remain fact ids. Cursors re-keyed to (arrival_ordinal, arrival_seq)
PAIRS (naive ordinal-only drops mid-batch rows — gate-proven trap); additive
since_with_cursor API; rowid allowed ONLY as row address (UPDATE WHERE rowid).
G-D2-5 is ruled a residue LOCATOR (scope narrowed); G-D2-4 behavioral gate owns
the axis verdict (gate proved it catches oid-spelled regressions at 3+ sites).

## 3. Unverified-fixes enumeration
Arbiter-applied: NONE this package. All commits gate-verified across 2 rounds
(8f800ccf impl, 6dc12f15 fix round — oid mutation re-run independently by gate,
incl. an unrehearsed second site).

## 4. Do-not-re-report
- Backward seal verifiability: gate built a sealed fixture on the OLD code and
  verified under new — exercised across real versions.
- W3-3 cursor-type unification deferred to the simplify pass (typed guard +
  pin in place). Known.
- test_tick_chain displacement test now mutates coordinates, not rowid — gate
  judged necessary-not-weakening (old mutation vacuous post-re-key).

## 5. Review focus at LOW effort
What a two-round gate could still structurally miss: a seal-path consumer
OUTSIDE sqlite_store.py still assuming rowid windows (grep jsonl_store, libs/
store, apps for window/rowid assumptions); the "" => (-1,0) sentinel's
interaction with genesis ordinal 0 (off-by-one at the window's closed/open
boundary?); since_with_cursor's pair cursor vs the empty-store/start-of-store
sentinel; any docstring the diff falsifies.

## 6. Verdict format
Findings SOL-WP3-NN (severity, file:line, claim, evidence); overall PASS/FAIL.
One response.
