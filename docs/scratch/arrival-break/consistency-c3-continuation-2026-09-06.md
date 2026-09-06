# C3 continuation follow-up — September 6, 2026

Status: complete; implemented, validated and accepted by Fable-low.
Baseline: `bacaeb96` on `arrival/finish`, the C5 checkpoint. Sol owns the engine
change and adversarial tests, Terra the public SDK acceptance, Luna independent
audit and validation, and root integration, documentation and review triage.

## Contract and implementation

A continuation retains its original full captured head H, represented prefix P,
request, cursor and derived-view generation. Opening a later page revalidates
the saved heads against custody. The query transaction may nevertheless observe
a projection that has advanced since the token was issued.

The resumed snapshot's actual watermark now uses `complete_projection_custody`,
the same helper used by fresh reads, runtime capture and declaration preparation.
It requires the captured lineage, custody membership, the exact returned
lineage/ordinal and full-head agreement when the watermark is at H. Backend
membership refusals retain their identity. Valid progress beyond H remains
allowed, while the returned continuation basis retains the original H and P.

Contradictory snapshot/custody evidence uses `HeadMismatch`, matching fresh
reads. A foreign snapshot remains `NotAuthority`. Token-head mismatches,
generation changes and continuation lifecycle failures retain
`InvalidContinuation`; a backend's missing-prefix exception passes through as
the same instance. No new refusal is inferred merely from projection progress.

This completes the snapshot-watermark follow-up identified in the first C3
slice. It does not change token encoding, adapter responsibilities, generation
policy, CURRENT/ALLOW_BEHIND policy or automatic projection maintenance.
Missing/regressed projections and changed generations still refuse. The shared
helper establishes custody evidence for a coordinate, not equivalence of every
projected row to custody. The file adapter's existing bounded generation digest
and row filtering continue to protect continuation stability.

## Acceptance and review

An isolated baseline run reproduced three failures: the old resumed branch
accepted a substituted same-height hash, a wrong returned ordinal and a wrong
returned lineage. The new five-case matrix also preserves foreign-watermark
refusal before lookup and the identity of a missing-prefix exception. Each case
asserts snapshot/query/ledger cleanup. A positive ALLOW_BEHIND case retains
distinct original H/P despite a valid newer snapshot; existing token and
generation protections continue to pass. The focused consumer suite passed
31 tests. The SDK's real file-backed packed-batch pagination
test now appends another batch and explicitly synchronizes the projection
between pages. Resumed pages retain the original full basis and exclude the
new rows; a fresh read sees them.

Full validation passed **2,568 engine tests / 1 skipped**, **540 SDK tests** and
**101 architecture tests**. Scoped engine and SDK Ruff passed. See the
[independent validation](consistency-c3-continuation-validation-2026-09-06.md)
for commands, evidence provenance and scope. Fable-low accepted with no blockers.
One optional pair of tests for unchanged intermediate/regressed watermark
branches is deferred; a packet visibility question about SDK `projected_after`
is resolved by source and executed tests. See the
[primary triage](reviews/consistency-c3-continuation-2026-09-06/primary-triage.md).
Production and tests are unchanged after validation and review. No jobs remain.
Included in the C3 continuation checkpoint; nothing pushed or applied to live stores.
Review metadata retains the uncommitted state at the time of review.
