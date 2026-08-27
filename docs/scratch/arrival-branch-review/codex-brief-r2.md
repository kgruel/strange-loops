# Arrival substrate — whole-branch review, round 2 (narrow re-verify)

You are the same cross-family reviewer as r1 (`codex-brief-r1.md`,
`codex-r1-stdout.log` in this directory). Round 1 verdict: NOT CONVERGED,
three MAJORs. The arbiter (Kyle) ruled on all three
(`decision:design/arrival-branch-r1-rulings` + same-day amendment); this
round re-verifies the fixes empirically. Full disposition table:

| ID | Ruling | Disposition |
|---|---|---|
| CX-BR-01 | The law wins | **FIXED** — commit `a95c8f2b`. Arrival merge raises `store.MergeDivergence` on id collision with different content, before anything is appended, dry_run included. Strict comparison, signature included (era-mixed carry refuses — deliberate, receipted in the class docstring). Ticks compare on the chainless base (chain columns + tick signature are store-local custody the merge strips, so a chained target tick still dedups against its chainless twin). Scope correction found in implementation: the target-wins conformance vector executes the FROZEN LEGACY SQLITE arm (its harness populates plain SqliteStores), so it was NOT replaced — its claim was scoped to that family instead (vector description, generator, property-test docstring). The sqlite arm's behavior is byte-unchanged per the KEEP fence. |
| CX-BR-02 | Go as-is | **DISPOSITIONED** — admission signature verification is `plan:arrival-libs-slice-D` ("NEW CODE"), a receipted deferral; the branch ships with that boundary deliberately part-enforced. No code change. |
| CX-BR-03 | Fix in this cut | **FIXED** — commit `45fc6fd5`. `diff_interval_report` applies `verify_position_for_store` to BOTH positions before any rowid comparison — the same guard every `at=` read selector uses. Unadopted/lineage-foreign positions raise `WitnessLineageMismatch`; a same-lineage position from another store re-resolves by fact id (behavior upgrade: cross-replica diff answers correctly). The invalid-store mutant pin re-anchored on a store vanishing post-resolution. Migration-side handling for OLD stores deferred to the migration arc by ruling. |

## Your job

1. **Re-verify CX-BR-01 empirically**: reproduce your r1 divergent-pair
   scenario against `a95c8f2b` — it must refuse with `MergeDivergence` and
   append nothing (check the target log byte-identical after the refusal).
   Also verify the identical-body pair still dedups, and that the sqlite
   legacy arm is byte-unchanged (your r1 baseline: target-wins, unchanged).
2. **Re-verify CX-BR-03 empirically**: reproduce your r1 cross-store /
   cross-lineage `diff_interval_report` call — it must raise
   `WitnessLineageMismatch`. Verify the same-lineage-copy re-resolution
   answers rather than refusing.
3. **Regression sweep of the two fix commits only** (`45fc6fd5`,
   `a95c8f2b`): anything they broke, any new seam they opened. Suites all
   green at HEAD (run corpora independently; combining engine+root tests
   collides on `tests.conftest`).
4. **Verdict**: per-finding PASS/FAIL with evidence; overall CONVERGED /
   NOT CONVERGED; one sentence for the arbiter.

Do not re-open r1 dispositions without new evidence; do not widen scope
beyond the two fix commits plus your two repros.
