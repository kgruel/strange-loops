# Cross-family review brief — cli-honesty-wave, round 4 (post-simplify)

r3 called CONVERGED. A 4-angle simplify pass then applied 11 arbitrated
quality items (12 commits). Any pass that touches code reopens the review
obligation — and in a prior arc the simplify pass introduced the arc's ONLY
regression. This round reviews the simplify delta.

## 1. Anchor
- Repo: /Users/kaygee/Code/loops — branch `cli-honesty-wave`
- Simplify delta (primary target): `git diff 90082250...HEAD` (12 commits +
  merge 3873e853). Wave context: `git diff 17ffde6c...HEAD`.
- Apply report: docs/scratch/cli-honesty-wave/simplify-apply-report.md
- Baseline before delta: 2509 passed / 1 xfailed; now 2513 (4 new tests).

## 2. What the delta claims (verify, don't trust)
1. Refusal-message unification (cli/refusals.py + read-router table): three
   in-view refusal wordings byte-unchanged; router copy re-worded onto the
   unified sentence; router per-route reasons now shared across --at/--diff,
   --review, --status. CHECK: each refusal still carries its full info
   content (flag, context, both drop options); every refusal still exits
   nonzero on stderr; no route lost its guard in the table conversion —
   enumerate the (flag × route) matrix empirically.
2. cite view single-Invocation; missing_root_message single source (text
   unchanged at all five sites — diff the strings); ls _validate_kind helper
   (check ordering invariant intact: kind-before-key, live-undeclared kinds
   pass row-count then hit key backstop — sol r1 S2-F1's reproductions).
3. emit cite-gate cleanup: partition loop, dead getattr removal, unclamped
   subtraction. CHECK your r2/r3 reproductions still refuse identically —
   this gate fell twice; it gets the full battery again.
4. orient hot-path: newest reconcile-* now derived from the thread FOLD
   (one fetch) instead of a raw fact scan; claim is render byte-identity.
   CHECK the fold-vs-facts equivalence argument's edge: a reconcile-* thread
   name whose LATEST fact has ts older than a superseded one (re-emit
   history), and a store with zero threads.
5. census signature/short-circuit; completers factory (verify tab-completion
   candidates unchanged for cite first slot, ls, read); test dedup
   (parametrize/fixtures — verify no assertion was weakened, count-neutral).
6. read <typo> now gives did-you-mean (content parity with ls, byte parity
   disclaimed — Reporter collapses newlines). CHECK bare `loops read`
   no-vertex case keeps the init message, and exit codes unchanged.
7. New ratchet test test_key_predicate_parity.py: 15×20 matrix, one
   documented excluded corner (falsy non-string key under custom key_field).
   ASSESS: is the exclusion honestly documented as unreachable, and does the
   matrix cover the comma-OR shapes the census actually feeds?

## 3. Verdict format
Findings as [R4-F<n>] severity — claim — evidence. Explicitly state whether
each of the 7 claim-groups above VERIFIED or FAILED. Overall: CONVERGED /
NOT CONVERGED.
