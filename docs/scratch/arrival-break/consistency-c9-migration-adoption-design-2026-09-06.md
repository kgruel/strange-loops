# C9 migration to current Arrival adoption

## Current gap

At baseline `50e37595`, before this publication slice, the offline sidecar creates a valid
Arrival **custody** history, then rewrites a legacy vertex store clause. It does
not create a current Arrival declaration history. `run_migration` mints a
physical lineage and appends transformed records through the registry
([sidecar.py](../../../libs/migrate/src/migrate/sidecar.py)), but
`edit_vertex_store_clause` writes only `backend="file"`
([sidecar.py](../../../libs/migrate/src/migrate/sidecar.py)). The current
SDK refuses a descriptor without an explicit role
([target.py](../../../libs/sdk/src/sdk/target.py#L88)).

Adding `role="authority"` and the physical lineage is necessary, but it does
not make the target usable. Ordinary descriptor-based Arrival reads resolve the effective
declaration from the captured projection and refuses when no declaration is
adopted; it will not substitute the locator file
([read.py](../../../libs/sdk/src/sdk/read.py#L194)). Projection identity is
licensed only by a consumed `_decl.genesis` fact whose **fact ID equals the
physical log lineage** ([arrival_projection.py](../../../libs/engine/src/engine/arrival_projection.py#L423)).
The sidecar transform creates migration key introductions and migrated rows, but
no such declaration fact. Therefore a role-only publication would make
`resolve_arrival_target`, `verify_target`, and `sync_target` reachable, while
inspection, normal reads, declaration editing, and writes still honestly
refuse.

The current initializer already has the exact declaration-anchor construction:
`_draft` makes one `_decl.genesis` row using canonical document JSON, a FACT
inner signature, and an ARRIVAL outer signature
([arrival_initialization.py](../../../libs/engine/src/engine/arrival_initialization.py#L273)).
That construction must be extracted or shared; a migration-specific copy would
invite wire and signing drift.

## Bounded publication hardening

First change only the sidecar publication output, not old records or source
inputs. Its surgical editor must write and re-parse:

```kdl
store "<rehearsal arrival location>" backend="file" lineage="<physical lineage>" role="authority"
```

It must retain the existing same-file atomic replace and non-store AST equality,
and validate all three descriptor claims. This makes the copied target an
explicit descriptor declaring the operational authority role; the registry still
checks the residence and lineage, and the declaration is still unadopted.

The later adoption slice should retain a hash of the exact copied vertex bytes
used for transform and report it. That hash is a proposal, not current sidecar
output. It prevents a later local edit from silently becoming the adoption
declaration. The sidecar already protects legacy-source content during its run;
the publication implementation now checks its captured declaration bytes in
memory, but does not persist that snapshot for a later adoption ceremony.

For a rehearsal, copy the legacy source and vertex before any sidecar write,
write all staging log/report/credentials under a disposable root, and isolate
XDG state/config/LOOPS_HOME. A live SQLite source needs a coherent snapshot
mechanism or a quiesced copy; byte copying a changing database is not an honest
fixture. The original source, vertex, store, keys, and witnesses remain untouched.

## Explicit adoption, a later append-forward ceremony

A new dedicated engine operation with an SDK wrapper should adopt a **reviewed
snapshot** into the already-migrated copied log. It is neither `init_vertex`
nor `edit_declaration`: initialization mints a fresh lineage, while declaration
editing correctly requires an existing historized declaration.

Inputs are: the explicit authority descriptor; the selected migration head `S`;
an explicitly reviewed declaration snapshot; declared adopting observer; mapped
credentials; and an optional verified migration-report receipt. The operation
must:

1. Open the descriptor through the registry, capture `H`, require `H == S`, and
   `Full(S)`. A changed source target refuses before an adoption append.
2. Require an explicit selected document snapshot. The initial recommendation is
   the copied locator bytes used by transform, re-parsed and compared with a
   retained hash/documents only after the caller names that snapshot for
   adoption. A copied legacy locator is evidence to review, not automatic
   authority: it can be stale relative to the legacy store's then-effective
   declaration. Any alternative reviewed declaration needs its own named
   input/evidence. The ceremony never reads a later cache as authority.
3. Scan the captured prefix for declaration identity conflicts before drafting:
   refuse an existing current-lineage `_decl.genesis`, any fact already using the
   physical-lineage fact ID, and any historical `_decl.*` record that claims the
   new physical lineage. Historical foreign or legacy declaration rows remain
   retained evidence; they are not selected, removed, or reinterpreted as this
   store's authority.
4. Parse and validate the selected documents with the current Vertex grammar and
   runtime identity validator. Refuse duplicate document subjects and loop/vertex
   collisions. In the first adoption slice, every selected observer public key
   must match a key already valid for that observer at `S`; it neither introduces
   nor replaces keys. A later key-changing adoption must use the existing
   key-introduction/declaration path with separately designed ordering.
5. Verify registry-forming migration signatures (genesis and key introductions)
   with an injected ARRIVAL verifier. `verify_target` alone establishes grammar,
   density, lineage, and hash chain, not signatures, key trust, or projection
   agreement. Migrated ordinary envelopes may remain unsigned under the existing
   migration contract; adoption must not claim their authorship.
6. Resolve a pre-created mapped binding for the adopting observer after capture.
   Its public key must equal the key valid for that observer at `S`; no resolver
   mint, legacy import, or fallback occurs in adoption. Use separate FACT and
   ARRIVAL requests/signatures, then verify both against that captured key.
7. Append exactly one initializer-compatible `_decl.genesis` draft whose fact ID
   is the physical lineage. Existing migration rows stay byte-for-byte intact.
   The commit names `before=S` and `after=A`; it is the explicit identity claim.
8. Explicitly sync through `A`. Only that consumed row lets the projection stamp
   `own_lineage`. Publish/reconcile the copied locator cache as an operation
   phase, retaining the real commit if it fails after append.

This needs an intent/recovery record analogous to initialization/declaration
editing: durable planned draft, descriptor, `S`, selected document hash, author,
and public non-secret binding evidence. Recovery never re-signs or duplicates a
committed draft. It may append the exact reserved draft only after proving that
the captured `S` still names the pre-append target and that no planned draft is
present; otherwise it compares the durable draft, synchronizes, and finishes
cache publication. Refusal before append has no fabricated commit; post-append
failure retains `Commit` and an adoption-specific incomplete result.

## Signer and provenance boundaries

The sidecar `Signer(observer, digest)` currently signs genesis, key
introductions, and the external report without a domain/purpose argument.
For the first adoption, registry-forming signatures must verify in
`ARRIVAL_DOMAIN`. The existing production wrapper uses `arrival_signer_for`,
which already signs in that domain. A custom injected sidecar signer outside
that contract must refuse at adoption even if structural Full verification
passes. Lock this requirement into the adoption inputs and tests before
implementing the ceremony.

Mapped credentials are domain- and purpose-specific. Do not silently route the
sidecar's undifferentiated callback through one mapped signer. Decide whether migration report signing stays
an explicitly injected sidecar/report verifier, or version the sidecar signer
contract with an explicit report domain. The adoption record itself uses current
FACT/ARRIVAL domains only.

`verify_migration_report` must run against target head `S` before adoption; its
current live-head equality is expected to fail after the adoption append. An
adoption outcome may retain report path/digest and verified `S`, but this is
external audit evidence, not a claim that the report itself is an on-ledger
identity record. If durable source-to-adoption provenance is required, it needs
a separately designed versioned declaration payload or evidence event.

The filename-derived sidecar custodian is quarantined historical behavior. The
new ceremony must take the explicit observer and prove it is authorized by the
captured migration key registry. Foreign `_decl.genesis` records remain inert:
only an ID matching the physical lineage licenses the projection marker.

## Acceptance path

Use a temporary copied JSONL fixture first. Prove: sidecar output has explicit
backend/lineage/authority and `Full(S)`; report verifies at `S`; pre-adoption
sync can build a projection but inspection/read/write refuse for no adopted
declaration; adoption refuses stale `S`, wrong mapped public key, bad genesis or
key-introduction signature, an existing/current-lineage declaration collision,
conflicting physical-lineage fact ID, a historical declaration overlay claiming
the new lineage, changed copied declaration bytes, invalid runtime identity, and
new/replaced observer keys without an append. Success appends one exact anchor,
preserves every prefix row through `S`, and treats that synthetic anchor as
outside the sidecar's source-equivalence comparison. It syncs and makes
inspection/read basis `A` agree. Recovered after-append failure must not
duplicate the anchor. A later mapped write must use the captured key history and
report its actual post-commit projection result; ordinary mapped writes may
already synchronize as part of their supported operation, so no universal second
sync claim is made.

## Finite implementation order

1. Complete and review the bounded publication implementation with synthetic
   offline integration tests. It remains explicitly unadopted.
2. Design and implement a shared initializer-compatible anchor-draft builder,
   captured-prefix collision/key/document validation, adoption
   intent/apply/recovery types, and a narrow engine append seam.
3. Add an SDK adoption wrapper with mapped binding and captured key-registry
   checks, without importing the migration sidecar into ordinary reads/writes.
4. Add a rehearsal orchestrator that snapshots/reviews input, invokes sidecar,
   verifies its report at `S`, then calls adoption. It owns temporary roots and
   report provenance presentation.

Open decisions: whether the report’s signature domain is versioned; whether a
reviewed non-identical declaration can be adopted; and whether source-to-anchor
provenance must be durable rather than retained in the operation receipt.
