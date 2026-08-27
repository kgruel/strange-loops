Working directory: /private/tmp/claude-501/wt-sliceB-explore (git worktree, branch explore/arrival-sliceB). Every shell command MUST be prefixed with: cd /private/tmp/claude-501/wt-sliceB-explore && 
First run: cd /private/tmp/claude-501/wt-sliceB-explore && git branch --show-current — if it is not explore/arrival-sliceB, STOP and report; do not proceed.
EXECUTE YOURSELF — DO NOT DELEGATE. You are read-only in intent: do not edit, create, or delete any file in the worktree.
Deliver ALL findings in one response; do not stop to ask questions.
Answer ONLY locatable questions: every claim carries file:line. Report locations, never verdicts or recommendations. If something does not exist, say 'not found' with the searches you ran.

TASK: The arrival substrate built in slices 0/A:
1. Enumerate the ArrivalStore (or arrival module) public surface: every public method/function with file:line and one-line signature. Look for files with 'arrival' in the name under libs/engine/src/engine/.
2. Where does append stamp marks / reconciled heads (append_marked, following=, CAS arms) — file:line.
3. The ceremony write path: locate the fsync of the arrival log and the sqlite COMMIT in ceremony persistence, in order — file:line each.
4. Locate: (a) a comment about a codec decoded-dict entry point / triple JSON round-trip on the rebuild path; (b) _log_size and _has_rows definitions and callers — file:line each.
5. Which modules import the arrival module — file:line.
