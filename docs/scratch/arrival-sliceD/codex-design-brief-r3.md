# Codex review brief — slice D design proposal r3 (re-verify, sol LOW)

Repo: this checkout, branch `feat/arrival-libs` @ ea0ad590. **Review-only: do
not modify any file.** Target: `docs/scratch/arrival-sliceD/design-proposal.md`
(now r3). Prior rounds: your r1 findings (codex-design-r1-stdout.log,
DP-r1-01..10) and your r2 re-verify (codex-design-r2-stdout.log — 8 PASS,
DP-r1-03/10 FAIL, new DP-r2-01..04). r3 revised the document against
DP-r2-01..04 and re-closed DP-r1-03/10.

Narrow re-verify:
1. Per finding DP-r2-01..04 plus the re-closed DP-r1-03 and DP-r1-10:
   PASS/FAIL with evidence, primary-sourcing every source claim the revision
   makes (table-rebuild DDL feasibility for these schemas, the
   ensure_coordinate_schema dispatch coverage vs the four writers named,
   the selective key_registry algorithm vs arrival.py:1585-1650, the G-D3-2
   instrumentation bounds).
2. Fresh-eyes on ONLY the r3-changed text (D0 migration mechanism, the
   upgrader, key_registry spec, gate edits): new findings as DP-r3-NN.
3. Do not re-report: the open questions routed to Kyle; everything that
   PASSed in r2.

Verdict: PASS/FAIL table for the six re-verified items, any DP-r3 findings,
per-decision SOUND/UNSOUND/SOUND-WITH-CHANGES, overall RATIFIABLE /
NOT-RATIFIABLE-AS-WRITTEN. Deliver everything in one response.
