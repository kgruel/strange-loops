Working directory: /private/tmp/claude-501/wt-sliceB-explore (git worktree, branch explore/arrival-sliceB). Every shell command MUST be prefixed with: cd /private/tmp/claude-501/wt-sliceB-explore && 
First run: cd /private/tmp/claude-501/wt-sliceB-explore && git branch --show-current — if it is not explore/arrival-sliceB, STOP and report; do not proceed.
EXECUTE YOURSELF — DO NOT DELEGATE. You are read-only in intent: do not edit, create, or delete any file in the worktree.
Deliver ALL findings in one response; do not stop to ask questions.
Answer ONLY locatable questions: every claim carries file:line. Report locations, never verdicts or recommendations. If something does not exist, say 'not found' with the searches you ran.

TASK: Enumerate merge/receive write paths:
1. Definitions of merge_store and receive_store (and helpers they call) — file:line ranges. Look in libs/store/src/store/ and libs/engine/src/engine/.
2. Every site inside those paths that writes: (a) direct sqlite index INSERT/UPDATE, (b) appends to a .jsonl file, (c) appends to the arrival log — file:line each, labeled.
3. The current content and line numbers of libs/store/src/store/merge.py around line 83 (quote ~10 lines).
4. Locate tests named test_merge_direction_sets_fold_order_by_receipt and test_merge_direction_is_deterministic — file:line, and quote each test's body.
