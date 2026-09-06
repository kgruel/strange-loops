# Transfer coordinator implementation design

Status: primary's next-stage design, supplementing `transfer-handoff-2026-09-05.md`.
This exposes the existing wire and ledger contract; it adds no transfer-of-
authority protocol, transport database, or alternate custody mode.

## Exact export and replication first

An engine `open_export(registry, descriptor, *, through=None, codec=...)`
returns a closeable captured export. Registry attestation precedes capture;
an explicit through head must be a verified member at or below that captured
head. The existing adapter export supplies exact records and deterministic
manifest. Keep all handles alive through iteration and close them on success,
failure or caller context exit. Export requires no query projection. A lazy
generator that references a ledger already closed by its opener is invalid.

For an SDK output artifact, stream the exact wire bytes into a unique temporary
file beside the destination, flush and fsync it, then exclusively link it into
the destination pathname and fsync the parent. Return the existing manifest
in the SDK result beside that artifact path. This needs no new archive or
two-file atomic-publication protocol. Do not publish a truncated successful-
looking prefix after a late scan refusal. Confirm the final public operation
name against current SDK/store entry points before implementation. A separate
low-level stream API can return manifest plus iterable without pretending
output on stdout can be rolled back.

Replication captures source and receiver independently. Source role must
support export/scan, receiver designation must be Authority or Replica and
its capabilities must support the operation. An existing receiver prefix
must agree with the source at the receiver's full head; a receiver already
at or beyond the exported prefix returns a no-op only after exact common-
prefix verification. Same lineage is not sufficient evidence. A fork refuses
before mutation. Copy the missing suffix verbatim, in one `replicate(expected,
records)` call, preflighted against max_atomic_records. Limited-backend
resumable transfer remains deferred; do not silently split this unit.

For an unminted receiver, expected=None is a request for the backend's
exclusive creation decision, not a claim that a PreGenesis observation proves
absence. Preserve any opening refusal and let the typed supported creation
path distinguish absence from corrupt or conflicting evidence. The adapter
must refuse an existing incompatible target without truncation.

Return source captured/selected heads, receiver before, actual Commit when
held, record count and explicit projection outcome. Replication does not mint
a different lineage, re-sign records or publish a descriptor as an authority
transfer. Projection maintenance is explicit and uses the receipt's after
head. A failed opener is a precommit refusal; an entered replicate with no
receipt is unknown; NotWitnessed and projection failures retain the commit.

## Admission second

Prepare a detached foreign observation set from a bounded source scan. Preserve
source group boundaries and ordinals. The new structure must carry in-memory
key-history evidence and source descriptor/head, not SourceRows.canonical's
legacy Path that causes `_source_registry` to construct ArrivalLog directly.
Use `key_registry_from_records` for forming-record verification. Use separate
FACT and ARRIVAL verifier callbacks; they verify different commitments.

Destination preparation uses one Authority/CURRENT read for effective local
declaration, custodian, held facts and held ticks. It preserves existing foreign
admission meaning and the `_comparable` / `_draft_for` rules: exact authored
fact text/signature stays intact, while foreign ticks drop their source-local
chain and tick signature. Ordinary local-emission grant/signing rules are not
silently substituted for these transfer rules. Destination outer signatures
must not impersonate foreign authors.

Deduplicate both against held rows and within the offered set before signing
or append. Review `_drafts_for` carefully: it currently adds fresh rows to
the held map only after scanning an entire source group, so duplicates within
one incoming batch can evade its first comparison pass. Equal IDs with equal
content are skipped; different content or row class refuses before any append.
Preserve atomic source ceremony groups after dedup according to the existing
one-row-fact / multiple-row-batch rules.

Verify the surviving admitted signed fact rows against the source's key valid
strictly before their original source position. Deduplicated held rows are
outside that new-admission claim. Optional unsigned observations remain
unsigned. Source key self-consistency is not target-operator trust; the result
must state the verification scope. Do not import source introductions into the
destination's key history as an accidental side effect of admitting facts.

Prepare all exact drafts, counts, IDs, source basis, target basis and full CAS
head before the one append. Reconstruct append inputs from detached evidence
so a caller cannot mutate dictionaries after the intent/report is captured.
No automatic retry after unknown durability and no re-signing on recovery.
Projection failure retains the actual admission receipt. Selection/slicing
is an admission input filter and never claims to be an exact ledger prefix.

## Acceptance and retirement

Use real temporary ledgers for export/import/export byte identity, append
during lazy export, existing receiver with equal/ahead/forked prefixes,
missing projection, atomic cap, failed output publication, foreign signatures,
same-batch duplicate IDs, mixed source groups, stale target and every durability
outcome. Verify no legacy constructor is reachable from supported calls.

Only after these paths and their SDK surfaces pass should `store.merge`'s
SQLite transport/merge arms and direct ArrivalLog constructor routes be
retired. Extract surviving pure codecs/column vocabulary first; migration
keeps its own frozen legacy reader. This stage does not migrate live stores.
