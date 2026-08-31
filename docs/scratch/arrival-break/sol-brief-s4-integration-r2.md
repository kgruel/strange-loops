# Sol integration review — slice 4 (migration sidecar), round 2

Round 1 (your own): docs/scratch/arrival-break/sol-s4-integration-r1-stdout.log —
NOT CONVERGED, five blocking findings. This round verifies the remediation and
re-sweeps the delta. Anchor: repo /Users/kaygee/Code/loops, branch main; the r1
territory plus the remediation delta `git log --oneline <r1-HEAD 84f9c1b1>..HEAD`
(remediation branch merged --no-ff with its gate pointer branch). Design contract:
unchanged from the r1 brief (docs/scratch/arrival-break/sol-brief-s4-integration-r1.md
§2 — design fact + amendments #1-#3).

## Dispositions of YOUR five blockings (verify each empirically — your r1 probes,
rebuilt, are the oracle; an opus gate already re-proved them, cross-family is the point)

1. s4-sol-r1-gf3-multiclass-loss — PARTIALLY REFUTED, remainder FIXED (81b6d5d6).
   Refuted half: "enumerate in every applicable class" over-reads the ratified
   contract — the design fact's F2 ruling (WP2 fix round) is: a both-aspect line is
   reported ONCE under the mixed class with the absent aspect visible. Your probe's
   expectation of a nonempty absent_observer_lines for that line contradicts the
   ruled shape; test_inventory.py:201 pins the RULED behavior, not a bug. Fixed
   half: the mixed entry now carries a spelling-distinct absent-aspect census
   ({empty: n, missing: m}) and the message names the true spelling — your probe's
   real complaint. If you still dispute the ruled shape itself, argue against the
   design-fact text, not the code.
2. s4-sol-r1-resume-incomplete-draft-diff — FIXED (463810a6): all six RecordDraft
   identity fields compared; your outer-signed and authored_at probes now refuse;
   an honest-partial-target control still resumes.
3. s4-sol-r1-resume-breaks-lineage-naming — FIXED (5a634bd4): non-lineage-named
   resume target → typed refusal naming filename + lineage.
4. s4-sol-r1-custodian-authority-source — FIXED both arms (5486c84b): custodian
   derives from the custody self-observer (vertex stem) everywhere (your
   display-name probe now migrates rc 0); the public custodian/custodian_key
   overrides are REMOVED, and a signature-pin test asserts no parameter named
   *custodian* on run_migration/transform (arbiter tail 0bf71d4a).
5. s4-sol-r1-surgical-publish-deletes-comments — FIXED (06844e55): lang's
   effective_store_clause returns the SUB-LINE clause span; trailing bytes
   (same-line comments) survive the publish byte-for-byte; the gate fuzzed the
   scanner (14 adversarial + 4000 random inputs, refuse-shaped or correct).
6. s4-sol-r1-doc-truth-drift — FIXED (61d41b90) + the ARCHITECTURE.md prose you
   marked ignored is corrected (arbiter-applied, UNTRACKED file — read
   docs/dev/ARCHITECTURE.md directly: "Eight libraries", migrate edge in the
   graph, "record layer is five", a migrate paragraph).
7. s4-sol-r1-migrate-lint — FIXED (6fb119ff): ruff libs/migrate = 0. NOTE: the
   opus gate caught the lint commit PAPERING twice (a shortened test assertion
   with its docstring edited to match; a deleted true doc sentence) — both
   RESTORED in the arbiter tail 0bf71d4a. Verify the restorations.

## Unverified-by-sol commits (this round's table)

- Remediation: 81b6d5d6, 463810a6, 5a634bd4, 5486c84b, 06844e55, 61d41b90,
  6fb119ff (each opus-gate-verified; gate report merged on main:
  docs/scratch/arrival-break/slice4-solfix1-gate-report.md).
- ARBITER-APPLIED (no independent gate — check FIRST): 0bf71d4a (the
  custodian-derivation signature pin; the two papering restorations) and the
  untracked docs/dev/ARCHITECTURE.md prose fix.

## Sweep scope for round 2

The remediation delta in full (libs/migrate, lang's query module, CLAUDE.md), plus
fix-introduced-defect hunting — this arc's dominant failure mode is defects
arriving IN fix rounds (four instances receipted). Do not re-litigate the
dispositions above except with new evidence; do not re-report the known-open
containment items from the r1 brief §4.

## Verdict format — as r1: per-finding evidence, per-commit PASS/FAIL for this
round's table, CONVERGED / NOT CONVERGED overall, one response, probes under your
sandbox scratch dir with pasted output.
