# sol HIGH review — 0.10.0 wave round 3 (closing verification)

/Users/kaygee/Code/loops, feat/010-surfacing. Verify the r3 fix merge
(diff: git diff 05b4247...HEAD — commits cad6211, 6523c07, c9307b2 + hygiene).
Your r2 report: docs/scratch/010-wave/sol-review-r2.md.

CLOSING ROUND. For each of the six r3 items: replay your r2 evasion (must now
be caught), then AT MOST ONE fresh evasion attempt each — this round decides
convergence, not exhaustiveness. The arbiter has ruled (090 precedent): the
loop closes when remaining evasions require deliberate indirection the
boundary census now counts, or machinery-generates-machinery hardening whose
cost exceeds the drift risk it guards.

Items: (1) vertex_fold snapshot bracket via StoreReader.snapshot() —
fold rows and edge metadata one commit; (2) Rule 12 shadowing fail-closed
(your twelve shapes); (3) boundary census countable with baseline 0;
(4) allowlist dict[path,reason] + baseline + unresolvable-only suppression;
(5) hostile sentinels (your strip/lower + sorted evasions); (6) underscore
packages + src-layout completeness rule.

Verdict per item: CLOSED / PARTIAL / NOT-CLOSED. Then an overall convergence
verdict: does the loop close at this round, or name what genuinely blocks it
(a finding must be honest-code-shaped or production-reachable — deliberate
smuggling forms the census counts do not block convergence).

Write docs/scratch/010-wave/sol-review-r3.md (no trailing whitespace — your
r2 report failed git diff --check), print summary to stdout, leave the tree
otherwise untouched, run the suites to confirm green.
