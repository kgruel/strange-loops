Working directory: /private/tmp/claude-501/wt-sliceB-explore (git worktree, branch explore/arrival-sliceB). Every shell command MUST be prefixed with: cd /private/tmp/claude-501/wt-sliceB-explore && 
First run: cd /private/tmp/claude-501/wt-sliceB-explore && git branch --show-current — if it is not explore/arrival-sliceB, STOP and report; do not proceed.
EXECUTE YOURSELF — DO NOT DELEGATE. You are read-only in intent: do not edit, create, or delete any file in the worktree.
Deliver ALL findings in one response; do not stop to ask questions.
Answer ONLY locatable questions: every claim carries file:line. Report locations, never verdicts or recommendations. If something does not exist, say 'not found' with the searches you ran.

TASK: In this Python monorepo (libs/engine/src/engine/, libs/store/src/store/), enumerate:
1. The definition of catch_up (and any _catch_up variants) and _rebuild (and rebuild/reindex variants) in the engine store layer — file:line ranges.
2. Every call site of each — file:line.
3. For each definition: what data source does it READ from to rebuild the sqlite index — the .jsonl file, the arrival log (.arrival suffix / ArrivalStore), or both? Cite the exact lines doing the read.
4. Any code path that performs INSERT into sqlite index tables during catch_up/rebuild — file:line.
