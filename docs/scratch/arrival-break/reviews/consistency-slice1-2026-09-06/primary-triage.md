# First consistency slice — primary review triage

Status: complete. Both Fable-low reviews accepted; root accepts the bounded slice.

Fable 5.1 reviewed the frozen C3/C8a implementation at low effort on September 6,
2026 (finished 16:30:19 UTC). Its verdict was **accept**, with no blocking defect
and five low-priority findings/evidence questions. Root independently evaluates
each below. This review was static; test execution is native validation evidence.
The [raw review](first-slice-findings.md), prompt, result metadata, source hashes,
and frozen slice note are retained in this directory.

## Dispositions

1. **Accept terminology clarification.** The equal-height comparison is between
   the attested custody Head and the later custody resolution of a projection's
   Watermark. It detects disagreement between those custody answers. A watermark
   contains no hash; this does not compare projected row contents to custody or
   prove a projection-row substitution. Root clarifies the slice note. Existing
   refusal strings remain for compatibility.
2. **Defer continuation completion hardening.** The retained continuation branch
   exact-validates token H/P and enforces generation/prefix lifecycle, but its
   fresh snapshot watermark resolution does not use the new returned-coordinate
   and same-height comparison. This is explicitly outside the fresh-open slice.
   Track a bounded follow-up preserving token bounds and legitimate later
   advancement; do not describe that additional check as already implemented.
3. **Accept fresh consumer test gap.** Runtime/declaration wrong-coordinate tests
   do not substitute for a consumer regression. Add the analogous fresh-read
   refusal and closure-order assertion.
4. **Retain declaration wrapper; annotate C2 evidence work.** A lower represented
   prefix raises `ProjectionBehind` inside declaration preparation and is then
   wrapped as `DeclarationPreparationRefused` with its cause. This predates C3.
   The helper deliberately does not normalize that outer boundary. The generic
   wrapper is existing behavior, not a newly ratified outcome classification.
5. **Accept real-backend concurrency evidence gap.** Synthetic ledgers establish
   the interface rule but do not exercise FileLedger resolution above the head
   captured by its attestation. Add a disposable file-backend integration that
   actually advances custody/projection between attestation and snapshot opening
   and asserts the original H remains the operation's bound. No live user store
   is involved.

## Independent native follow-up

Root noticed and Terra confirmed an initializer compatibility regression not
raised by Fable: the initial C8a guard ran before existing `details.update`, so an
unchanged SDK error lost `intent_path` enrichment. Move the bare-raise identity
guard after the existing enrichment, preserving both diagnostics and the
original exception/cause. Add an unchanged `ArrivalRefusal` regression that
checks identity, cause, preexisting detail, and the intent path. This corrects
the first implementation without broadening the C2 error taxonomy.

## Validation boundary

Initial final engine run: **2,524 passed, 1 skipped** from `libs/engine`; SDK
**496 passed**; architecture **101 passed**. Root's focused C3 run: **57 passed**.
Follow-up validation: engine **2,528 passed, 1 skipped**; SDK **497 passed**;
initializer **11 passed**; real file-backed concurrency **3 passed**. Scoped
Ruff passed. The real integration captures H before actual append/projection
advance and opens the snapshot afterward, across read/runtime/declaration.
Read/runtime test row bounds; declaration tests its no-op plan and full basis.
The latter assertion replaced an intermediate vacuous empty-ID assertion, and
the three cases passed again afterward. Architecture remains **101 passed**;
the follow-up changes only tests and the SDK initializer exception guard.

The [final Fable-low follow-up](followup/first-slice-followup-findings.md) finished
at 16:42:56 UTC with **accept**, no corrections required. It confirmed the SDK
diagnostic/identity behavior, fresh consumer wrong-coordinate refusal, and the
actual file-backend interleaving. Its two remaining notes correctly bound the
claims: declaration's no-op case proves full basis clamping, not exclusion of a
new declaration row; nested registry opens in this file fixture do not establish
generic concurrent-writer safety. Those limitations are recorded, and neither
requires expansion of this slice.

Root's final [scope check](scope-check.json) records final reviewed code hashes,
test counts, link/whitespace checks and a clean main checkout. Initial review
source drift is explained by the explicitly reviewed follow-up; no code changed
after the follow-up packet. Runner status files retain their historical
`reviewed-awaiting-triage` result; [triage status](triage-status.json) is the final
completion marker. Both substantive reviews used `claude-fable-5-1` at low effort;
any tiny CLI helper usage is recorded separately in their result metadata.
No reviews remain pending. No production commit, staging, publishing, or
live-store/key operation is part of this pass.
