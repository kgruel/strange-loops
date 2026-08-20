# Cut C — sol cross-family review r2 (fix verification round)

You reviewed this cut in r1 (your findings and the brief: docs/scratch/arrival-sliceC/sol-r1-stdout.log, sol-brief-r1.md — all of r1's anchor, contract, and do-not-re-report rulings still stand). Your four findings were remediated. Fixes deserve MORE adversarial attention than first-cut code: this round verifies them. Deliver ALL sections in one response; do not stop to ask questions.

## Anchor
Branch feat/arrival-libs, this checkout. The remediation diff: `git diff 22159e4c..HEAD` (5 commits + merge). Suites as in r1; all green at HEAD (atoms 515, engine 1807+1skip, sdk 324, store 152, root 110).

## Fix commits to verify (per-commit PASS/FAIL with evidence — re-run your own r1 probes and attack the fixes)
- 15d76fc0 [C-SOL-01] — non-mapping payload = missing-K non-member, via new atoms.resolve_payload_key (one definition; resolve_key_field delegates, engine _row_field consumes it). New conformance vector lens-by-key-non-mapping-payload-excluded (a33560a8); six pre-existing vectors byte-identical. ATTACK: every payload shape (str/int/float/bool/list/None/nested), every surface (resolve_key_field, ordered, _combined_read, conformance runner); hunt any remaining spelling of payload key access that bypasses resolve_payload_key.
- bd7c6abc [C-SOL-02] — resolve_ordering hoisted above the empty-members early return; refusal now declaration-shaped. The one-member rule (len==1 → single-store axis) was deliberately KEPT (ratified). sdk read_facts already declaration-shaped (no hole), now pinned. ATTACK: zero-member aggregate via combine AND via discover; default and ByKey on empty aggregates must stay byte-identical to pre-fix behavior; try to construct availability-dependence in either direction (incl. a single-store vertex whose store file is missing).
- 1442a41d [C-SOL-03] — totalize refuses NaN (after the type check, so mixed-type still wins); infinities explicitly allowed and pinned both directions. ATTACK: NaN inside mixed types; NaN via your r1 permutations; -0.0/underflow edge cases; the float-typed-only claim (string "nan").
- a1c43266 [C-SOL-04] — OrderingError class contract attribution + a shrink-only docstring ratchet (inspect.getdoc walk, allowlist of one). ATTACK: construct an evasion the ratchet misses only if it is cheap; otherwise verify the two runtime-message pins.

## Do-not-re-report additions since r1
(15) the fold-body TypeError on an INCLUDED non-mapping payload (vertex_reader.py:538) is pre-existing, independent of ordering, receipted deferred to the SDK/migration wave — the remediation deliberately pinned at the ordering layer only.

## Verdict format
Per-fix PASS/FAIL with evidence; any NEW findings (id C-SOL-05+, severity, file:line, claim, probe output); overall CONVERGED / NOT_CONVERGED. Proof-of-work as in r1: ranges read + probes run with pasted output; bare approvals are not reviews.
