# Explicit restore-forward

The user approved a separate restore-forward operation: “that would fit the
data-model well.” This resolves the first transfer boundary finding. Empty
receiver import remains a separate procedure to implement.

## Implemented boundary

`BackendRegistry.restore_forward(source, receiver, through=...)` is a complete
procedure returning `RestoreForwardResult`. It returns no custody handle.
`ArrivalLedger` has no new opcode; existing full-head `replicate` is its only
ledger mutation. Both descriptors must explicitly designate Authority or
Replica, and registered adapter capabilities and lineage pins still apply.

The source opens through ordinary attestation. Its selected full prefix is
verified. The receiver must already have a fully verifiable genesis and head,
and that head must be the exact head at the same coordinate in the source.
The procedure copies the detached suffix in one atomic replication, refusing
an insufficient adapter record limit instead of splitting the operation.

The witness seam's existing comparison is now factored into a pure
`_HeadObservation` over a two-operation read-only evidence protocol. Ordinary
`AttestedLedger` still compares and writes earned evidence at construction.
Restoration uses a bounded source proof to compare the *proposed* receiver
head, at the receiver's own binding, with its existing projection evidence.
This preflight writes no receiver acceptance. Rollback, replacement, reset
fences, indeterminate comparison, and unanswerable evidence still refuse.

Only after proof does the procedure enter the receiver's full-head CAS.
After a receipt returns, it opens the actual receiver through the ordinary
comparison again, witnesses the actual commit, and records the receiver's
binding. The journal is append-only and its established head is never lowered
by restoration. No trust reset, projection repair, cache publication,
re-signing, coordinate assignment, or new genesis takes place.

## Concurrent changes and recovery evidence

The receiver CAS rejects a competing writer. The selected head is fixed;
source writes after capture cannot silently extend this operation. If a new
witness head or trust reset becomes visible while replication runs, the
post-commit comparison can refuse. This returns a known committed-incomplete
outcome carrying the exact Commit. It never pretends that custody rolled back
when its later acceptance failed.

An exception after entering replication without a receipt returns
`RestoreForwardUnknown`, retaining the exact receiver-before and selected
target Heads. Reconcile those identities before repeating. A receiver already
at the exact selected head returns a no-op with `commit=None`; retry after a
lost successful receipt therefore does not duplicate records. A torn or
otherwise unverifiable receiver still refuses and is not automatically repaired.

The witness and ledger are separate resources: this operation provides the
same comparison/append observation model as ordinary attestation, not a new
cross-resource transaction. Concurrent changes after the final comparison
remain observable on the next ordinary open. Preflight and post-commit tests
cover both a higher witness and a trust reset during the actual append.

## SDK and CLI

`sdk.restore_forward(source.vertex, receiver.vertex)` returns the v2 model
with source/receiver descriptors, captured source Head, receiver before/after
Heads, and an actual optional Commit. Serialization reports receipt identity,
record count and durability without copying record payloads. SDK errors
preserve refused, unknown, and committed-incomplete outcomes.

`loops-min restore-forward SOURCE.vertex RECEIVER.vertex` delegates directly
to the SDK and uses the existing JSON/exit-status envelope. This operation has
strict descriptor resolution and no legacy writer fallback. Its inclusion
therefore does not depend on the remaining broader SDK legacy cutover.

## Validation

Thirteen dedicated engine cases cover exact restoration, repeat/no-op,
rollback-floor refusal, fork, absent receiver, atomic limit, stale CAS,
lost receipt, witness failure, reset fencing, concurrent witness/reset,
projection evidence, and opaque registered backend resources. Four SDK cases
cover public serialization, unknown/committed outcomes, and legacy refusal.
A real CLI process test proves ordinary rollback refusal before restoration,
exact bytes afterward, and successful ordinary verification.

Cross-model review is queued while Claude/Fable remains rate-limited. This
stage is implemented and locally validated, not cross-model accepted yet.
