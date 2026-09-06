# C8b and C2 review triage — September 6, 2026

**Complete.** Combined Fable-low follow-up accepted at
2026-09-06T17:47:36Z. All findings are adjudicated; no reviews remain pending.
Final production bytes match the accepted follow-up packet. The only subsequent
design change explicitly lists pre-build `coverage()` in an acceptance case.

Initial Fable 5.1 low-effort reviews finished successfully on two frozen packets.
C8b: accept with four low findings. C2 design: needs correction, one medium
design issue plus refinements. Root dispositions follow; a combined follow-up
reviews the resulting code/design corrections. No C2 implementation is claimed.

## C8b findings

1. **Basis may serialize as null: hypothesis rejected; test gap corrected.**
   Actual `ReadBasis` has the four attributes `_safe_detail` expects; the real
   first/later-tier SDK fixtures serialize it correctly. Added explicit checks
   for lineage, full captured head, full projected-through head and generation.
   No serializer replacement is needed.
2. **Unclassified sibling interruption lost during settlement: accepted.**
   Settled unexpected exceptions now propagate instead of vanishing from the
   buckets. A deterministic two-source regression uses a custom `BaseException`
   concurrent with ID allocation failure and verifies both streams close and
   the original exception escapes. Root additionally caught `raise ... from
   None` clearing an existing cause: final code preserves exception and explicit
   cause identity. KeyboardInterrupt/SystemExit have asyncio runner behavior of
   their own; the test does not claim to simulate OS signal delivery.
3. **Secondary cleanup diagnostics absent: deferred observability enhancement.**
   Non-masking and cleanup attempts are required and implemented. Adding new
   lifecycle payload/DTO fields or a tuple of cleanup errors is outside this
   bounded correction. No cleanup-success claim is inferred when another error
   remains primary. The existing collector lifecycle vocabulary is preserved.
4. **Full SDK run preceded last engine fixes: addressed.**
   Full SDK rerun passed 509; full engine rerun passed 2,540/1 skipped;
   architecture 101. The final explicit-cause preservation line is additionally
   covered by the 30-test engine source run. Exact sequence and limits remain
   visible in the validation report rather than being hidden by a combined count.

Root/architecture findings also froze the private state envelope (the pair list
remains coroutine-owned accumulation) and moved the SDK tests into their existing
source module to reuse fixtures without an undeclared test-module import.
No architecture exceptions, dependency changes or weakened checks were added.

## C2 findings

1. **Phase naming collision: accepted correction.** Existing `details.phase`
   remains unchanged. New engine `coordinator_phase` exclusively populates the
   proposed `details.evidence.phase`. Attempt/state invariants are explicit.
   The initial text said not every exception already carried phase; it did not
   say no exception did, but the proposed attribute collision was still real.
2. **Search pre-build proof: accepted refinement.** The worklist explicitly
   records snapshot/provider failures after target selection but before build
   as not-entered/not-attempted; the projection catch-up wrapper is
   entered/unknown. These are coordinator control-flow proofs, not deductions
   from nested exception types or claims about unrelated witness effects.
3. **Cause traversal unspecified: accepted.** Explicit BaseException-valued
   `.cause`, otherwise `__cause__`; at most two nodes beyond the wrapper,
   identity-cycle detection, safe coordinate fields, 512-character messages
   with truncation indication. No `__context__`, arbitrary repr or payloads.
4. **Dead mapping / unmatched error behavior: accepted worklist cleanup.**
   Future implementation removes the unreachable generic-refusal entry and
   leaves unmatched TypeError/ValueError unchanged. This describes current
   behavior rather than inventing a broad public compatibility promise.

Initial packets/raw output remain byte-preserved. The follow-up packet contains
the final relevant source, tests and revised design. Main is untouched; this pass
remains uncommitted after `cfb26920`.

## Follow-up dispositions

1. **Implicit context when re-raising a sibling interruption: no change.**
   Python may attach the bookkeeping failure as implicit `__context__`.
   Exception identity and its original explicit `__cause__` are preserved;
   this slice does not promise to preserve or suppress implicit context.
2. **Multiple sibling control exceptions: no change.** After settlement, the
   first unexpected exception in source order propagates. Secondary diagnostics
   remain outside this bounded correction; no ExceptionGroup API is introduced.
3. **Search coverage preflight: accepted documentation refinement.** Added
   `maintenance.coverage()` failure before build to the C2 acceptance case.
   The reviewed local-flag design already places it before the mutation boundary.

The follow-up's closing caveat about `sync_target` routing is a reminder of
scope: that routing is a C2 proposal, not an implementation claim. Test counts
are independently captured runner evidence, not tests performed by Fable.
Both initial jobs and the follow-up verified substantive Fable model output
at requested low effort; tiny CLI auxiliary output was not a substitute reviewer.
