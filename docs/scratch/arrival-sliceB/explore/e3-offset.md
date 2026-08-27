Working directory: /private/tmp/claude-501/wt-sliceB-explore (git worktree, branch explore/arrival-sliceB). Every shell command MUST be prefixed with: cd /private/tmp/claude-501/wt-sliceB-explore && 
First run: cd /private/tmp/claude-501/wt-sliceB-explore && git branch --show-current — if it is not explore/arrival-sliceB, STOP and report; do not proceed.
EXECUTE YOURSELF — DO NOT DELEGATE. You are read-only in intent: do not edit, create, or delete any file in the worktree.
Deliver ALL findings in one response; do not stop to ask questions.
Answer ONLY locatable questions: every claim carries file:line. Report locations, never verdicts or recommendations. If something does not exist, say 'not found' with the searches you ran.

TASK: The 'offset/count triple' custody. In libs/engine/src/engine/ and libs/store/src/store/:
1. Find where a per-store offset / count / byte-position triple is persisted (sqlite meta table, columns, or file) — file:line.
2. Every writer of those values — file:line.
3. Every reader of those values — file:line.
4. Any code comparing a stored offset/count against the .jsonl file's actual size or line count (staleness / unindexed-suffix checks) — file:line.
