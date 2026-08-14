# Sol review brief — libs-handoff-wave, round 6 retry (SCOPED convergence check)

Note: the first r6 run was interrupted by a tooling-side content filter; this
retry rephrases the same verification request in plain QA terms.

## 1. Anchor & scope

- Repo: this checkout, branch `libs-handoff-wave`.
- Since r5: ONE commit — ee652ba6 (merged), answering SOL-R5-01 only.
- SCOPED ROUND: your r5 verdict already verified everything else. Re-verify
  ONLY the R5-01 fix, then make the convergence call.

## 2. The fix under review (ee652ba6, lang/vertex_mutation.py)

An escape-aware left-to-right scan extends the provable-domain refusal:
refuses (a) the zero-hash raw opener r-quote (position-aware: r before an
OPENING quote refuses; r before a CLOSING quote — real corpus content like
"system-monitor" — stays allowed), (b) a literal newline inside a quoted
string, (c) an unterminated string at EOF. Soundness rationale: the substring
set already refused everything that could confuse the quote tracking, and the
scan refuses at the first construct it cannot prove safe. Multi-hash refusals
stay pinned.

## 3. Verification requests (QA correctness testing of input validation)

1. Re-run your two r5 test documents (r-quote opener; newline-in-string) —
   all three mutation verbs must now refuse with a typed error.
2. Boundary-condition testing of the position-aware allowance: author KDL
   documents where an r-before-closing-quote appears together with unusual
   but parser-accepted string syntax, and check whether the scan's
   classification of any LATER string opener becomes incorrect. The soundness
   rationale predicts it cannot; test that prediction.
3. Coverage check: any other parser-accepted string spelling outside the
   refused set (multi-line raw forms, escape sequences, unusual quote
   characters if the parser accepts them) for which a mutation verb completes
   while a physical sibling declaration count changes. That is the defect
   class under test — mutation must either preserve all siblings or refuse.
4. Verdict: SOL-R6-NN findings if any; then CONVERGED / NOT CONVERGED for the
   wave (R5-01 resolved + nothing new at blocker/major severity).
