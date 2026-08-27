# Codex review brief — slice D design proposal r2 (re-verify, sol LOW)

Repo: this checkout, branch `feat/arrival-libs` @ b5628350. **Review-only: do
not modify any file.** Target: `docs/scratch/arrival-sliceD/design-proposal.md`
(now r2). You reviewed r1 (your findings: docs/scratch/arrival-sliceD/
codex-design-r1-stdout.log, DP-r1-01..10, verdict NOT-RATIFIABLE-AS-WRITTEN).
The document was revised in place against all ten findings; the closing
"DP-r1 disposition table" maps each finding to its disposition.

This is a NARROW RE-VERIFY round plus a fresh-eyes sweep of the redesigned
sections only:

1. Per finding DP-r1-01..10: does the r2 revision actually dissolve it?
   Verdict PASS / FAIL per finding, with file:line evidence from source where
   the revision makes a source claim (primary-source them — the proposal's
   citations are claims, not authority).
2. Revision holes: the redesigned machinery (mode-aware D0 migration +
   coordinate_axis marker + legacy allocator; the ArrivalLog.anchor verb;
   the rewound L1 check; the rebuilt D4 arm 1 over post-dedup rows +
   fact_commitment_hash + source key registry; WitnessAxisMismatch;
   multiset jsonl audit; the expanded gate list) is NEW design — attack it
   the way you attacked r1. New findings as DP-r2-NN.
3. Do not re-report: the eight open questions the document flags for Kyle
   (report only if a recommendation is factually wrong); settled slice 0+A-C
   rulings; anything you already reported that the disposition table marks
   as ruled-to-Kyle rather than redesigned — judge only whether the routing
   is honest.

Verdict: per-DP-r1 PASS/FAIL table, new DP-r2 findings, per-decision
SOUND / UNSOUND / SOUND-WITH-CHANGES, overall RATIFIABLE /
NOT-RATIFIABLE-AS-WRITTEN. Deliver everything in one response.
