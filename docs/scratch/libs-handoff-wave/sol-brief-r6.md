# Sol review brief — libs-handoff-wave, round 6 (SCOPED convergence check)

## 1. Anchor & scope

- Repo: this checkout, branch `libs-handoff-wave`.
- Since r5: ONE commit — ee652ba6 (merged), answering SOL-R5-01 only.
- SCOPED ROUND: your r5 verdict verified everything else (R4-02/03/04 +
  ceremony full-row honesty sound; all r1–r3 standing). Re-verify ONLY the
  R5-01 fix, then make the convergence call. Do not re-open verified
  dispositions; a full re-sweep is not requested.

## 2. The fix under review (ee652ba6, lang/vertex_mutation.py)

Claim: one escape-aware left-to-right scan added to the provable-domain
refusal — refuses (a) zero-hash raw opener r" (position-aware: r before an
OPENING quote refuses; r before a CLOSING quote — real corpus content like
"system-monitor" — stays allowed), (b) literal newline inside a quoted
string, (c) unterminated string at EOF. Soundness argument: the pre-existing
substring set (#", "#, """) refuses every construct that could poison the
quote tracking first, and the scan refuses AT the first unprovable — the
tracker is never trusted past one. Multi-hash 1–8 refusals stay pinned.

## 3. What to do

1. Re-run your two r5 repros (r" opener; literal-newline string) — all three
   verbs must refuse typed.
2. Probe the position-aware allowance: construct inputs where an r-before-
   closing-quote coexists with hostile syntax — can the allowance be leveraged
   so the tracker mis-classifies a later opener? The soundness argument says
   no (first-unprovable halt); try to break it.
3. Any OTHER parser-accepted string spelling outside the refused set (multi-
   line raw forms, escape tricks, BOM/unicode quotes if the parser accepts
   them) that still permits silent sibling loss.
4. Verdict: SOL-R6-NN findings if any; then CONVERGED / NOT CONVERGED for the
   wave (R5-01 resolved + nothing new at blocker/major).
