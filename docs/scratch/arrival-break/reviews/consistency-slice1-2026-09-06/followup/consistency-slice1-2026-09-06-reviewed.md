# Arrival consistency slice 1 — September 6, 2026

Status: first Fable-low review accepted; bounded follow-ups implemented, final review pending.

This implements C3 and C8a from the [consistency contract matrix](consistency-contract-matrix-2026-09-06.md),
following the [recommendations review triage](reviews/consistency-2026-09-06/primary-triage.md).
The user authorized the existing Sol/Terra/Luna implementation pattern and a
Fable review at the end. Work is confined to `loops-wt/arrival-finish` on
`arrival/finish`; prior Arrival changes remain uncommitted.

## Scope and acceptance

C3 gives fresh reads, runtime capture, and declaration preparation one narrow
rule for completing a projection watermark through custody: verify lineage,
resolve membership even above the captured head H, require hash agreement when
the custody-resolved head is at H's ordinal, and only then clamp a legitimate advance
to H. H remains the read bound and write CAS basis. Continuation generation and
prior-prefix rules remain a separate lifecycle. This does not add a full
projection-content audit, read repair, or protection from an arbitrarily
dishonest custody adapter.

C8a preserves initializer exception identity and cause when SDK normalization
returns the original object. A new normalized exception still chains from its
engine cause. Existing intent-path enrichment is retained before the bare
re-raise. The outcome taxonomy is unchanged.

Rejected write preparation must precede signing and append. Resource ownership
must still close snapshots, queries, and ledgers. Accepted attestation can write
external witness evidence before a later refusal; no zero-filesystem-effects
guarantee is introduced.

## Delegation and validation

Sol owns C3 engine implementation and focused regressions. Terra owns C8a SDK
implementation and initializer tests. Luna independently challenges acceptance
and runs broader validation. Root owns integration judgment, review artifacts,
and final triage.

Terra's completed C8a checks: initializer **10 passed**; SDK **496 passed**;
scoped Ruff passed. Existing original-cause and interrupt regressions preserve
the exact exception object; the mapped `UnknownBackend` regression retains the
original engine exception as `ArrivalRefusal.__cause__`.

Sol's C3 uses `complete_projection_custody` in the existing engine head seam.
Fresh `open_read`, `_current_write_basis`, and `prepare_declaration_edit` call it
with their own refusal families; backend `head_at` failures pass through the
helper unchanged. Declaration preparation retains its outer preparation-refusal
wrapper and cause. The helper also checks that the returned Head's lineage and
ordinal match the requested Watermark coordinate. It does not conflate those
two types. Continuations retain their existing exact token-head checks and
generation/prefix rules; their current-snapshot resolution was not changed.

Sol's focused checks: owning consumer/runtime/declaration tests **57 passed**;
dependent runtime capture/batch/boundary/source tests **69 passed**; SDK
declaration integration **34 passed**; architecture Rule 18 **35 passed**.
Fresh read substitution was observed failing to refuse before the correction.
Synthetic backend regressions cover valid advance, foreign evidence, nonexistent
prefix above H, disagreement between captured and later custody answers at the
same height, wrong-coordinate returns,
preparation before signing/append, and resource closure. These prove adapter
interface behavior, not an exploit against a live file backend. Existing file
integration and pagination tests remain part of validation.

Terra independently reviewed helper and caller integration with no C3 blocker.
All changed callers/tests passed owning Ruff. The head seam passes with E501
excluded; its sole full-file E501 is the pre-slice module-docstring line 23,
confirmed identical in the saved baseline. No legacy formatting was changed.

The final stable-tree engine run from `libs/engine` passed **2,524 tests, with 1
skipped** (67.02s). The broader SDK suite passed **496**, and architecture passed
**101**. The earlier engine count of 2,514 was superseded because collection
overlapped addition of the remaining regression tests. Root also reran the
final focused C3 suite: **57 passed**. See the [independent validation note](consistency-slice1-validation-2026-09-06.md).

The first [Fable-low review and root triage](reviews/consistency-slice1-2026-09-06/primary-triage.md)
accepted the implementation, with small test/evidence gaps. Root separately
found and Terra corrected lost intent-path enrichment for an unchanged SDK
error. Final initializer **11 passed**, SDK **497 passed**, and scoped Ruff
passed after that correction. Consumer wrong-coordinate coverage now includes
refusal and resource closure. A real FileLedger integration exercises all three
paths with custody/projection advancement after attestation and before snapshot
opening: observed watermark exceeds H while the resulting basis stays at H.
Read/runtime rows exclude the appended fact; declaration preparation succeeds
as a no-op at its original basis. Final engine **2,528 passed, 1 skipped**;
scoped test Ruff passed. These stores and their custody state are temporary test
fixtures. The added real-backend evidence concerns bounded reads/preparation,
not signature-domain or adversarial projection-content verification.

The final review will be recorded here when complete. C1 registry
injection and C2 phase/cause/effect design remain separate next slices, as do
the remaining identity and recovery work. No live-store/key migration, commit,
staging, or publishing is part of this pass.
