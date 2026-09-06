# Declaration edit and descriptor adoption design

This proposal implements the corrected declaration-edit handoff in
`declaration-edit-handoff-2026-09-05.md` and slice 4 §F/G. Declaration edits
remain live protocol operations after initialization. `absorb` genesis mode
dissolves into initialization; reanchor is removed; descriptor adoption only
designates an already-existing lineage and does not transfer authority.

## Contract and DTOs

The engine should expose one descriptor-first edit path, with SDK names
remaining the public convenience layer:

```python
@dataclass(frozen=True)
class DeclarationEditPlan:
    target_path: Path
    descriptor: StoreDescriptor
    lineage: str
    basis: ReadBasis                 # attested CURRENT snapshot
    captured_head: Head              # full CAS token
    before_documents: tuple[dict, ...]
    proposed_documents: tuple[dict, ...]
    changes: tuple[DeclarationChange, ...]
    authored_at: float
    observer: str
    drafts: tuple[RecordDraft, ...]  # exact signed rows, in append order
    old_cache_sha256: str
    proposed_text: str
    intent_path: Path

@dataclass(frozen=True)
class DeclarationEditResult:
    status: Literal["applied", "noop", "stale", "refused", "needs-recovery"]
    descriptor: StoreDescriptor
    basis: ReadBasis
    captured_head: Head
    commit: Commit | None
    fact_ids: tuple[str, ...]
    intent_path: Path | None
    file_written: bool

@dataclass(frozen=True)
class DescriptorAdoptionPlan:
    target_path: Path
    old_descriptor: StoreDescriptor | None
    descriptor: StoreDescriptor
    observed_head: Head
    old_cache_sha256: str
    proposed_text: str
    intent_path: Path
```

The engine API is `prepare_declaration_edit`,
`apply_declaration_edit`, and `recover_declaration_edit`. Preparation parses and
runs `lang.validate_vertex`, resolves the explicit descriptor through
`BackendRegistry`, opens one attested CURRENT snapshot, and resolves the
existing declaration documents from that same basis. It computes
`lang.document.diff_documents` and captures the full `Head`; a timestamp or
projection fingerprint alone is not a CAS token. Empty changes return a typed
`noop` plan and append nothing.

Application creates an exclusive, fsynced sibling intent before opening the
append path. The intent contains the descriptor, lineage, full captured head,
old cache hash, proposal bytes, one timestamp, every exact draft body and
signature, and planned fact IDs. It contains no private key. The coordinator
constructs the semantic batch itself: one `RecordDraft` for a single change, or
one `RecordDraft(kind="batch", body=body_of_batch(rows),
signature=arrival_signature)` for multiple changes. The adapter receives that
exact draft and appends it without regrouping or reframing. The coordinator
then calls the registry-opened `AttestedLedger.append(captured_head, drafts)`
once; it does not call SQLite or `ArrivalLog` and does not retry with new
signatures. The result carries the actual `Commit` when witnessed.

Recovery opens through the same registry, checks the physical lineage and exact
planned records at the expected suffix positions, and only then finishes cache
publication. It distinguishes `already-applied`, `safe-to-finish`,
`not-applied`, and `conflict`; an unknown append is reconciled by exact draft
membership, never by a matching folded document fingerprint. A later ordinary
append does not erase proof that the planned suffix committed. If there is no
original `Commit` object after a process death, recovery reports the verified
head and leaves commit absent rather than fabricating one.

Cache publication first writes and fsyncs a complete same-directory temporary
file. The intent records the exact old bytes/hash. After re-reading and checking
those bytes, the publisher renames the old target to a unique sibling backup
and fsyncs the directory. It reads the backup again to verify the captured hash,
then exclusively links the complete temporary file into the now-empty target
pathname and fsyncs the directory. If another actor recreates the target,
exclusive publication fails and leaves the competing target, verified backup,
temporary file, and intent in place; recovery reports conflict without
overwriting any of them. If the post-detach backup hash is wrong, publication
also stops with all evidence retained. This is a cooperative protocol for
writers that honor the intent gate; an uncooperative writer can still race the
initial read/rename window, so the verified backup and conflict evidence are
the recovery boundary rather than a claim of filesystem-wide CAS. Intent
removal is followed by parent-directory fsync. Failures after an observed
custody commit are committed-incomplete outcomes with phase, head/commit when
available, exact IDs, and intent path.

## Signing and key-history order

Each declaration row is a fact row. Its inner signature is the existing fact
commitment over `(kind, authored_at, observer, origin, payload_text)` and is
made by the fact signer. The enclosing Arrival fact or batch has its separate
Arrival-domain signature made by the arrival signer. The DTO must retain both
values and their exact payload text; a convenience credential provider supplies
both callables and must reject a missing or cross-domain signer before intent
creation.

One effective timestamp is assigned to the whole transition. All planned
records are preflighted against the adapter's atomic record limit before the
intent is written. The normal edit is packed as one declaration batch when it
contains multiple rows, preserving the all-or-nothing historical transition and
same-timestamp semantics. The adapter still receives the full expected head and
must reject a moved head without appending any prefix.

An observer public key in `_decl.observer-defined` is declaration meaning; it is
not an Arrival cryptographic introduction. If the proposed declaration adds an
observer carrying a key, a preceding `k="key"` draft with body
`{"observer": name, "key": public_key}` is required. That introduction is
signed by an observer key already valid strictly before its position. Only then
may a later record use the new observer. A keyless declared observer is legal
and produces no introduction. The edit author must itself resolve to a key
already valid at the append position; mandatory signing is the ceremony's
authorship gate. Declaration grammar and existing semantic validation remain
separate from `grant_for_observer`, which this operation does not invoke.
Revocation changes future admission and does not rewrite or
invalidate prior signatures. No reanchor or authority-transfer record is
generated.

## Descriptor adoption

`prepare_descriptor_adoption` is separate from an edit. It resolves the
requested backend and opaque location, obtains an attested head, and verifies
that the observed physical lineage equals the descriptor lineage. It prepares a
surgical store-clause update while asserting that all other parsed fields are
unchanged. `apply_descriptor_adoption` uses the same durable intent and
exclusive cache publication protocol, but appends no fact, key, or declaration
record. It refuses an absent, conflicting, or wrong-lineage target and never
uses a descriptor change to bypass declaration authorship or transfer authority.
`recover_descriptor_adoption` compares exact old/proposed bytes and the observed
binding before finishing; it never infers adoption from a missing projection.

## Neutral authorship seam

The neutral seam now uses the existing `ArrivalLedger.scan` iterable rather
than introducing a new protocol. `key_registry_from_records(records, verify)`
returns `(KeyRegistry, tuple[KeyResolution, ...])` for the registry-forming
width, while `verify_authorship_records(records, verify)` returns the same
pair after checking every signed envelope. Both consume the existing record
fields, `KEY_INTRODUCTION_KIND` ordering, and the rule that a key is valid only
when introduced before the record it verifies. The iterable must be a complete,
ordered, structurally verified genesis-through-head prefix; the seam does not
decode or recheck chain structure. Legacy `key_registry(log, ...)` and
`verify_authorship(log, ...)` delegate to these functions, preserving exact
behavior for `ArrivalLog` callers. `AttestedLedger` supplies the scan and the
file adapter remains responsible for decoding and storage. Initializer and
declaration code therefore depends on `ArrivalLedger`, `RecordDraft`, `Head`,
and `Commit`, with no `ArrivalLog` or SQLite import.

## SDK ownership and migration

`engine.declaration` owns document resolution and diff DTOs; a new focused
engine declaration-edit coordinator owns basis capture, signing, exact intent,
append, and cache recovery. `arrival_registry` and `arrival_head_seam` own
backend opening, attestation, full-head CAS, and close forwarding. `lang`
continues to own parsing, validation, `vertex_to_documents`, and
`diff_documents`. `sdk.kind` maps `add_kind`, `edit_kind`, `remove_kind`,
`grant_observer`, and `revoke_observer` to one generic edit executor. It must
stop calling legacy probe/open/SQLite ceremony arms for Arrival descriptors.
SDK result models expose descriptor, basis, planned IDs, commit, and typed
committed/unknown outcomes; they do not collapse these into message-only
`CeremonyFailed`. `recover_ceremony` delegates to the new recovery DTO.

Acceptance must cover default custody initialization followed by kind add/edit,
singleton and tombstone edits, grant/revoke, new-key introduction and later
signed use, keyless declared observers and refusal when the edit author has no
valid in-log key, no-op, same-timestamp
batch, stale full-head CAS, malformed/semantically invalid proposals, missing
or cross-domain signers, and atomic-limit refusal before append. Inject durable
append-then-raise, unwitnessed append, projection failure, intent-save failure,
cache publication failure, and competing cache edits. Verify exact inner and
outer signatures, zero-prefix mutation on precommit refusal, exact draft
recovery without duplicate transitions, and descriptor adoption preserving
unrelated source bytes.
