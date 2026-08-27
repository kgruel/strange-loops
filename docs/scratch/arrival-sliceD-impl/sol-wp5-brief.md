# WP-5 pass check — codex sol LOW — slice D, D4 arm 1 (admission verification)

## 1. Anchor
Branch slice/D-wp5, tip f435328a. Diff: git diff feat/arrival-libs...f435328a
(exclude WP5-REPORT.md). Implementer: Claude opus. Gate: Claude opus, PASS
(GATE-WP5-REPORT.md on slice/D-wp5-gate) — you are the FIRST cross-family eyes
on this package; weight that.

## 2. Design contract (ratified)
design-proposal.md §D4 + rulings: arm 1 IN, opt-in; legacy source => explicit
no-claim, never refusal. Invariants:
- key_registry: structural walk of ALL records; envelope verification ONLY for
  genesis (self-certifying) + KEY_INTRODUCTION_KIND (with previously-valid-key
  authorization); ordinary envelopes NEVER verified; introduction ordinals
  recorded; slice-A validity clause verbatim (valid at N iff introduced < N, or
  genesis self-certifying).
- merge: verifies POST-DEDUP ADMITTED fact rows only, carried signature against
  fact_commitment_hash (content-only), key valid for the row's observer at the
  row's source position; refusal appends NOTHING; unsigned rows admitted
  era-aware; default path (param unsupplied) byte-identical.
- NON-NEGOTIABLE: claim scope is source self-consistency, not target trust.
- W5-2 (gate observation, conformant): tick rows are NOT verified — §D4 scopes
  arm 1 to fact rows. Do not re-report; arm 2 territory.

## 3. Unverified-fixes enumeration
ARBITER-APPLIED (verify first — no independent gate): f435328a derives the
admitted-row column indices from FACT_CONTENT_COLUMNS (gate finding W5-1,
recurrence of ruled F-4). NOTE: the arbiter's first draft of this fix passed
row[id] where fact_commitment_hash takes (kind, ts, observer, origin, payload)
— caught pre-commit against the function signature; check the committed mapping
independently.
All other commits gate-verified (gate re-ran break B2 independently).

## 4. Review focus at LOW effort
The seams a same-family gate could miss: the KeyRegistry validity semantics vs
slice A's ratified clause (off-by-one on "introduced at position < N"?); the
dedup boundary (can a row be admitted without entering the verification set —
e.g. tick-batch interleavings, id-collision paths?); transactionality of the
refusal against the retry loop in merge_store; the Verify callable's failure
semantics (exception vs False). Spot-run at most; suites are gate-verified.

## 5. Verdict format
Findings SOL-WP5-NN (severity, file:line, claim, evidence); overall PASS/FAIL.
One response.
