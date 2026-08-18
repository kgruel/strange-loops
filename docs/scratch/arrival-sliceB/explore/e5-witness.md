Working directory: /private/tmp/claude-501/wt-sliceB-explore (git worktree, branch explore/arrival-sliceB). Every shell command MUST be prefixed with: cd /private/tmp/claude-501/wt-sliceB-explore && 
First run: cd /private/tmp/claude-501/wt-sliceB-explore && git branch --show-current — if it is not explore/arrival-sliceB, STOP and report; do not proceed.
EXECUTE YOURSELF — DO NOT DELEGATE. You are read-only in intent: do not edit, create, or delete any file in the worktree.
Deliver ALL findings in one response; do not stop to ask questions.
Answer ONLY locatable questions: every claim carries file:line. Report locations, never verdicts or recommendations. If something does not exist, say 'not found' with the searches you ran.

TASK: Witness-position lifecycle (locations only, no judgments):
1. Where are witness positions / seal positions / chain-head coordinates that reference index rowids or jsonl offsets CREATED — file:line. Look for 'witness', 'seal', 'position', 'rowid' in libs/engine/src/engine/ (esp. jsonl_store.py, sqlite_store.py, canonical_audit.py) and libs/store/.
2. Where are they STORED (table/column or fact payload field) — file:line.
3. Where are they READ or VALIDATED later — file:line.
4. Quote libs/engine/src/engine/jsonl_store.py lines 920-945 verbatim with line numbers (the rowid chain-commitment region).
