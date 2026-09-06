# C7 aggregate resolver continuation: Fable-low triage

Fable 5.1 returned **ACCEPT**, no blockers, at 2026-09-06 22:39:26 UTC.
Packet SHA-256:
`6a9782c20ad0120d9c41f13f4f8c2ecb27821fab315979d23a56c48cebb221c2`.
Root accepts the bounded resolver change. No post-review source/test edits
were needed.

One sentence in the review overstates the result: “Nothing downstream re-reads
the locator file on the Arrival path” is not true for effective aggregate
execution. `open_aggregate_read` constructs another local root plan and captures
members. The report and packet explicitly preserve those separate observations.
The new tests select an effective plain root and prove only the corrected
descriptor bridge's retention of its parsed residence across local replacement.
Acceptance does not grant a whole-operation single-parse or filesystem-transaction
guarantee. Similarly, the reviewer's description of other replacement timing
as universally benign is not an independently established broader claim.

Optional notes:

1. **Earlier storeless predicate observation:** explicitly outside this
   continuation. No further topology/planner behavior changed.
2. **Full suite after fixture refinement:** no rerun needed. Production is
   unchanged; all three refined regressions and scoped lint passed afterward.
   Full SDK 562 / architecture 101 results and their ordering remain honestly
   documented. The pre-fix in-memory probe fails all three against the final
   valid replacement fixture, establishing the regression's relevance.
3. **Unused import removal:** verified by source inspection and scoped Ruff;
   no additional action.

The substantive CLI review model is verified in retained execution status;
the frozen packet had no launch-time source drift. All findings are triaged,
and no continuation blocker remains.
