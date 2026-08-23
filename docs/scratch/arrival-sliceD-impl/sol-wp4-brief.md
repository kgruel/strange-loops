# WP-4 pass check — codex sol LOW — slice D, D3 (audit re-base), final package

## 1. Anchor
Branch slice/D-wp4, tip c3b8dcd4. Diff: git diff feat/arrival-libs...c3b8dcd4 (exclude
WP4-REPORT.md, WP4-FIX-REPORT.md). Implementer: flash-high. Gate: opus, 2
rounds, PASS (GATE-WP4-REPORT.md on slice/D-wp4-gate).

## 2. Design contract (ratified)
design-proposal.md §D3 + rulings (dispatch arm = ruled D-Q2 exception; preflight
= exactly one docstring sentence, gate byte-verified). Invariants:
- L1 bounded: exact record-verification totals (healthy=1 anchor read, K
  behind=1+K, anchor-failed=1 NO walk, deep=N) — gate proved the quantity seam
  covers every primitive (the two bypasses are O(1) by construction).
- Scope-the-claim: every Check is a location claim; no clean/intact/safe; no
  invented magnitudes (W4-1's behind_by=201 on a current index — fixed, gate
  re-verified).
- Dissolved residue gone: _check_offset, _suffix_unindexed, _last_line,
  beyond_offset.
- ArrivalLog.anchor = existing _anchor_for surfaced, no new validation.
- Deep audit: digest MULTISETS (duplicate lines detected).

## 3. Unverified-fixes enumeration
Arbiter-applied: NONE. All commits gate-verified (2 rounds; gate authored the
W4-1 reproduction and re-ran it post-fix).

## 4. Do-not-re-report
- Branch 1 (mark=None) walking everything: designed cost, ruled.
- verify_authorship separate verb; chain-to-genesis is --deep's claim only.
- W5-2 tick-authorship scope (arm 2 territory).

## 5. Review focus at LOW effort
Cross-package seams a file-scoped gate misses: callers of the OLD audit API
(anything importing beyond_offset/_check_offset symbols — grep repo-wide incl.
apps + libs/sdk); the dispatch arm's interaction with the D-Q2 audit surface
(does the CLI path handle the new Check shape end-to-end — lens/rendering
consumers of Check fields?); consumed_edge vs the WP-2 witness anchor semantics
(same anchor verb, consistent None handling?); any docstring the diff falsifies.

## 6. Verdict format
Findings SOL-WP4-NN (severity, file:line, claim, evidence); overall PASS/FAIL.
One response.
