# Codex review brief — slice D design proposal r4 (re-verify, sol LOW)

Repo: this checkout, branch `feat/arrival-libs` @ 2b05131e. **Review-only: do
not modify any file.** Target: `docs/scratch/arrival-sliceD/design-proposal.md`
(now r4). Prior rounds and findings: codex-design-r1/r2/r3-stdout.log in this
directory. r3 left three findings (DP-r3-01..03), all D0 migration mechanics;
r4 revised against them.

Narrow re-verify:
1. DP-r3-01..03: PASS/FAIL with evidence, primary-sourcing the revision's
   claims — the coordinate-provider signature and its four per-route supply
   stories (esp. ArrivalStore's constructor ordering vs arrival_store.py:133
   and the claim that no insert SQL runs during construction), the
   rowid-preserving copy vs the rederivation DELETE precedent
   (jsonl_store.py:944-954), the sqlite_schema trigger/index replay, and the
   new gates G-D0-7..11.
2. Fresh-eyes on ONLY the r4-changed text: new findings as DP-r4-NN.
3. Do not re-report anything that previously PASSed or is routed to Kyle.

Verdict: PASS/FAIL for DP-r3-01..03, any DP-r4 findings, per-decision
SOUND/UNSOUND/SOUND-WITH-CHANGES, overall RATIFIABLE /
NOT-RATIFIABLE-AS-WRITTEN. Deliver everything in one response.
