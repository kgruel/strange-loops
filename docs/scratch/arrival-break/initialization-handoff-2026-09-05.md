# Arrival initialization handoff

Status: primary's implementation constraints for the next bounded proposal;
not a completed initializer or a new protocol. The runtime and SDK emission
stages continue independently. The architecture suite and slice-4 corrections
govern this note.

## Existing behavior and intended cut

`sdk.declare.init_vertex` currently writes a declaration with an implicit
SQLite/JSONL store. It does not perform the Arrival bootstrap. Keep the public
operation name and replace its supported ordinary-store behavior with explicit
descriptor initialization; do not add a permanent `init_arrival` API family.
Aggregate scaffolding has no ledger bootstrap and remains a distinct case.

The existing `engine.ceremony` plan/apply/recover operations preserve valuable
intent, stale-plan and file-cache semantics, but their storage mechanics use
legacy probing, `_open_store`, and `absorb_genesis`/`absorb_edit`. Extract those
semantics onto the registry and Arrival drafts. Do not invoke legacy ceremonies
inside the new initializer as a temporary shortcut.

## Identity, signatures and recovery

Fresh initialization requires an explicit Authority descriptor, an observer,
and corresponding founding public key and signer. Engine receives credentials
as arguments; SDK owns custody lookup and key-file management. Mint through the
registry's attested ledger. A descriptor lineage pin must be honored.

The ordinary ledger genesis occupies ordinal zero. The declaration genesis
follows as a signed `_decl.genesis` fact whose **fact ID equals the physical
ledger lineage**. Its payload is the current Arrival declaration grammar's
protocol and document set, without legacy cursor/chain era pins. The inner
fact signature and outer Arrival signature follow fresh local authorship
rules and remain distinct. Source-check `ArrivalStore`'s ceremony encoding
before choosing whether declaration edits use a batch body.

The gap between mint, declaration append, projection sync, and publication of
the `.vertex` file needs durable intent and recovery. Reserve stable identity,
draft IDs, timestamps, documents, and descriptor in the intent before their
corresponding durable actions. Persist no private keys. Recovery must establish
what exists through the attested ledger and compare exact planned content;
it must neither infer absence from a stale projection nor mint a replacement
lineage when an earlier mint may have succeeded. Unknown append and
NotWitnessed preserve their reconciliation identities. Existing artifacts
without matching intent cannot be overwritten merely because init was retried.

The implementation proposal should specify the smallest recoverable phases
and failure injection points. Reuse atomic/exclusive intent and file replacement
helpers where they fit, while avoiding collision with legacy intent formats.
An operation that fails after bootstrap durability must report that durability
even when projection or descriptor publication remains incomplete.

## Declaration edits follow initialization

Read effective documents and declaration control head from the same CURRENT
snapshot and retain the full ledger head for the one append CAS. Preserve the
existing frozen allowed definition/tombstone vocabulary, one edit timestamp,
mandatory inner signatures and original annotation payloads. A stale plan
must not append or replace the file cache. Cache failure after append leaves
recoverable intent and the actual commit; replay sees the new declarations.

Descriptor adoption is a separate new operation. `reanchor` remains removed;
it is not a recovery or adoption synonym. Location/role designation must not
be mistaken for implementing the deferred authority-transfer protocol.

Declaration observer keys and the Arrival key history are distinct evidence.
`arrival.verify_authorship` resolves signatures from physical genesis and
signed `key` records only; an observer document does not introduce a key into
that history. The grant/rotation integration must establish the required key
record before a signed observation relies on it, using an already-valid
introducer key under the existing wire rule. Do not invent self-certification
outside ordinal zero. Acceptance for granting a new signed observer must
include grant, emit, and verification using the ledger alone. Unsigned
ordinary authorship remains governed by the existing optional-signature rules.

## Minimum acceptance evidence

- A real temporary initializer produces verifiable ledger and declaration
  genesis, correct identity equality, explicit descriptor and CURRENT reads.
- Wrong role, malformed declaration, missing signer and conflicting existing
  artifacts refuse at their defined precommit phase.
- Inject failures after mint, declaration append, sync and file publication;
  recovery retains the original lineage and does not duplicate controls.
- A valid declaration edit is atomic; stale plans leave bytes unchanged;
  file-cache failure after append recovers the original committed edit.
- SDK results serialize refusal, committed and unknown states without
  renderer-specific behavior. No legacy authority opener runs on this path.
- Completed implementation receives a Fable review including full untracked
  modules and tests, followed by source-backed triage.
