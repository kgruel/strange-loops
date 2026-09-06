# C2 implementation — September 6, 2026

Status: complete. Final source passed validation and the Fable-low follow-up
accepted; all review findings are adjudicated. Baseline:
`8a045f1f` on `arrival/finish`. This is the implementation of the accepted
[C2 evidence design](consistency-c2-evidence-design-2026-09-06.md), using Sol for
engine implementation, Terra for SDK acceptance tests, Luna for independent
validation, and root for SDK integration, file-backed tests and review triage.

## Result

Arrival `sync_target` now normalizes maintenance exceptions through the same
SDK boundary already used by search synchronization. Existing SDK classes,
`loops.sdk/error/v1`, outcomes, source types and operation-specific
`details.phase` remain intact. Cancellation and process-control exceptions
return unchanged from normalization and escape the public operation by bare
re-raise. Unmatched `TypeError` and `ValueError` remain engine exceptions.

The optional `details.evidence` object uses `loops.sdk/evidence/v1`. Only the
explicit engine `coordinator_phase` supplies its phase. Whitelisted resource
proofs supply effects; nested exception classes never determine whether a
mutation happened. Available identity and basis coordinates are retained;
explicitly unavailable maintenance heads/coverage are null, distinct from
attributes absent on older wrappers. No Commit receipt is synthesized.

- Projection catch-up wrappers report `derived-sync` and derived
  `entered/unknown` after entering `maintenance.catch_up`.
- Search wrappers report derived `not-entered/not-attempted` after target
  selection but before build, including snapshot opening, provider acquisition
  and initial coverage lookup. Immediately before `maintenance.build`, the
  coordinator records entry; subsequent failures report `entered/unknown`.
- Declaration preparation raises carry `prepare` and custody
  `not-entered/not-attempted`. Behind-projection causes retain full captured
  and projected heads where established. If snapshot opening itself refuses,
  the outer error retains the already captured head without inventing a
  projected head. These proofs say nothing about external signer effects or
  the separate witness operation performed during attested opening.

New constructor fields default to None, so old manually constructed wrappers
assert no coordinator phase or attempt proof. All preparation helper call
sites were checked to be inside preparation, before any custody append.

## Diagnostic bounds

The shared serializer chooses a BaseException-valued `.cause` first, otherwise
`__cause__`. It emits at most two causal nodes beyond the outer error, stops on
identity cycles, and caps each cause message at 512 characters with a
`truncated` marker. It excludes implicit `__context__` and record bodies.
Coordinate serialization accepts primitive scalars and paths; unsupported
scalar identity attributes are omitted without arbitrary `str` or `repr` execution. Cause
messages still use bounded exception text, as specified by the design.

Existing ordinary/batch/init/restore outcome classifications and source-tier
DTOs are retained. Explicit causal diagnostics are additive for normalized
errors that carry a cause, but this slice does not infer new effect proofs for
those legacy wrappers. C8b's incomplete collection remains at
`terminal.details.collection`; earlier durable tiers and paired partial
observations retain their existing representation.

## Validation and review

Focused tests cover engine preflight/build boundaries, declaration refusal
coordinates, constructor compatibility, causal bounds, SDK routing and
cancellation. Tests with real file adapters inject the same typed refusal
before search build and after actual index mutation, and after actual
projection catch-up. They verify the observed coverage/head, unchanged custody,
and absence of a fabricated Commit through the public SDK operation.

Final checks after review corrections passed: engine **2,550 passed / 1 skipped**,
SDK **525 passed**, architecture **101 passed**. Scoped Ruff passed. These runs
cover all final production and test changes, including constructor compatibility
and absent-coordinate corrections. Earlier full runs (2,547/523/101) and the
intermediate 10-test constructor check are historical in the
[validation note](consistency-c2-validation-2026-09-06.md).

The initial Fable-low review required corrections for absent declaration
coordinates versus explicit null, unsupported scalar omission, and contradictory
effect combinations. All three are fixed. Its hypothetical preparation-helper
use during recovery was rejected after an exhaustive call-site audit found no
such path; the full module is included in the follow-up packet. The
[primary triage](reviews/consistency-c2-2026-09-06/primary-triage.md) records each
finding. The follow-up **accepted** all corrections and the call-site rebuttal;
no reviews remain. Production/test bytes match the final full validation and
accepted review packet.

## Remaining scope

Legitimate projection advancement beyond a captured target remains supported;
coverage is not a full row audit. Preparation custody proof does not assert a
transaction across custody, witnesses, cache publication or external actions.
Broad error-envelope reshaping and cleanup-policy changes remain separate work.
The follow-up reviewer noted optional captured-head enrichment for other
in-basis declaration refusals; this existing omission remains explicit follow-up,
without widening C2 beyond its reviewed behind-projection path.
C4 credential configuration and the remaining identity/continuation/aggregate
matrix items are subsequent slices. C2 changes are uncommitted; nothing pushed
or applied to live stores.
