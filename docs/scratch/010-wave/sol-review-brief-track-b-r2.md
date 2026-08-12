# sol MEDIUM review — Track B round 2 (closing verification + Rule 13 contact)

Verify the fix round for your r1 report (docs/scratch/010-wave/sol-review-track-b.md).

- /Users/kaygee/Code/loops, feat/010-surfacing. Fix commits: `git diff
  92451e0...f59eed2` (989c37f Rule 13, 62af7a7 ULID seam, f59eed2 ledger
  accuracy). The later receipts commit 5012e24 is arbiter documentation —
  ignore it.
- /Users/kaygee/Code/loops-go, feat/track-b-batch. Fix commit: `git diff
  76c8378...590e70f` (regenerated tie fixture).
- Implementer's fix-round claims are relayed in the ledger + commit messages;
  verify, don't trust.

SANDBOX: writes = loops workdir + /tmp only. loops-go is READ-ONLY — perturb in
`cp -R /Users/kaygee/Code/loops-go /tmp/tb2-scratch`, `GOCACHE=/tmp/gocache`.

## Closings — verdict each CLOSED / NOT-CLOSED

1. P2 ULID: all five tie ids now valid Crockford ULIDs (validate with the
   reference `store.rebirth.is_ulid` AND a real ULID parse). Re-run your four
   ORDER BY perturbations against the regenerated fixture in the scratch copy —
   same red/green profile as your r1 table required. Confirm derived state
   (`expected`/`expected_rowid_order`) is unchanged from the r1 cut.
2. P2 tools/ hole: replant your exact evasion (`import tools._conformance` in
   libs/engine/src/engine/witness.py) — Rule 13 must go red. Revert, confirm 52
   green.
3. P3 ledger: header repo-state now scoped to the reviewed tips; Q4 framing
   contradiction resolved; the third-artifact-class prerequisite restored
   (distinct from Q1). Verdict against your r1 wording.
4. P3 claim wording: "no normative change" adopted; the accurate SPEC-diff
   description present in the ledger.

## New-rule contact — Rule 13 (one adversarial round, scoped)

This wave's convention: a new ratchet gets evasion contact. Construct against
tests/test_architecture.py Rule 13 + its 5 regression tests. Candidate angles
(pursue what's live, drop what's structurally dead): dynamic import forms
(importlib/__import__ with a 'tools' literal); a production file importing a
non-production root via `from tools import x` vs `import tools.x` vs relative
tricks; a new non-production root the derivation-by-shape would MISS (Python
files in a root the shape test excludes); whether the derivation can go
half-vacuous (e.g. roots found but file-walk silently narrowed). Honest-code
evasions only — deliberate obfuscation beyond what prior rounds counted is out
of scope. Verdict: HOLDS / EVASION-FOUND with the construction.

## New-finding audit

The implementer reports a corpus-wide ULID defect: 13/13 ids invalid across
proc.db / merge_ab.db / merge_ba.db, deliberately NOT fixed (bundled into the
parked regeneration pass; gen_store/gen_merge intentionally do not call the new
fixture_ulid seam yet, preserving byte-comparability of committed-state regen).
Spot-check the count and the deliberate-non-call claim; verdict on whether the
bundling leaves any test lying (a suite asserting validity it doesn't have).

## Output

Write docs/scratch/010-wave/sol-review-track-b-r2.md (no trailing whitespace):
per-closing verdicts, Rule 13 contact verdict with constructions, new-finding
audit, and the batch convergence verdict (CONVERGED / FIX-ROUND-NEEDED). Print
a summary. Confirm both suites green at committed state before closing. Change
nothing outside your report and /tmp.
