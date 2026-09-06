# Runtime write extraction plan

Status: design recommendation for completion-worklist stage 3. This document
does not change the runtime. It records the smallest implementation boundary
that can move ordinary writes onto the descriptor and witnessed-ledger path
while retaining the existing fold, declaration, and recovery semantics.

The next slice should introduce one runtime write coordinator. It should accept
a fully resolved authority descriptor, prepare facts, batches, and any
automatic ticks without mutating a live `Vertex` or `SqliteStore`, then issue
one full-head CAS append through the registry's `AttestedLedger`. After the
append, it may publish the prepared projection or reconstruct it from the
committed prefix. `SqliteStore` can remain the file backend's projection and
legacy migration implementation during the transition; it must stop being a
second authority path for ordinary runtime writes.

## Current path and the seam to replace

The current path has several independent SQLite-centered decisions:

| Operation | Current behavior | Stage 3 boundary |
| --- | --- | --- |
| Fresh initialize | `apps/loops/src/loops/commands/init.py` scaffolds a vertex, seeds config through `load_vertex_program` and `Vertex.receive`, then best-effort opens a legacy canonical store for absorb. `compiler.materialize_vertex` still chooses a store implementation from the old mode/suffix path. | Resolve an explicit authority descriptor, mint an ordinary arrival genesis/key root, append declaration bootstrap and initial config through the same writer, and bind the declaration anchor to the witnessed genesis identity. Keep migration callers separate. |
| Emit | `sdk.emit.emit_fact` opens an old `VertexProgram`; `VertexHandle.receive` preselects an ID and calls `Vertex.receive_receipt`. `Vertex.receive_receipt` stores the fact before fold and `_store_tick` persists automatic boundaries through the old store. | Admission, parse, fold, boundary decision, and draft construction happen before append. Facts and generated ticks are one append unit, followed by projection publication. |
| Batch emit | `sdk.emit.emit_batch` loops `receive_as`; a later refusal can leave a committed prefix even though the API describes the operation as atomic. | Prepare every item first and append one batch (plus ticks) or refuse before append. Return an explicit committed/unknown outcome if a failure occurs after durability. |
| Declaration edit | `kind.py` plans an update and `ceremony.apply_declaration_update` writes an intent, opens the old canonical store, calls `SqliteStore.absorb_edit`, then replaces the cache. `absorb_edit` performs its own SQLite transaction and declaration-head check. | Preserve the intent/recovery wrapper and declaration planner, but turn the edit into signed `_decl.*` `RecordDraft`s and append once against the same declaration and full ledger head. |
| Reconstruct | Handle refresh/probe and declaration resolution read from the old store and may trigger recompile/epoch changes after a write. | Read a captured ledger prefix and projection snapshot; never fire boundaries or repair on replay. Reconstruct using the exact declaration anchor and committed head. |

The relevant existing primitives are already close to the needed split:
`RecordDraft`, `DeclarationAnchor`, and full-head `ArrivalLedger.append` live in
`libs/engine/src/engine/arrival_contract.py`; `FileLedger.append` in
`arrival_file_backend.py` assigns coordinates and performs the atomic log
append without signing or rehashing drafts; and `AttestedLedger.append` in
`arrival_head_seam.py` journals a durable commit after the ledger append. The
admission helpers in `admission.py` and body grammar in `arrival_body.py`
already preserve authored inner payload text and signatures.

## Proposed smallest slice: 3A

Create a store-independent planner and coordinator for one ordinary fact,
including a boundary tick. The first slice should be deliberately narrow:

1. Resolve the `.vertex` descriptor and require `role=authority` for a
   supported writer. Open it with
   `BackendRegistry.with_builtin_backends().open(...)`. Keep the returned
   `AttestedLedger` and query alive for the whole operation.
2. Read one consistent projection snapshot and the full ledger head. Resolve
   `DeclarationAnchor(own_lineage, genesis)` from the declared lineage and
   declaration controls; never infer an owner from an arbitrary record.
3. Run admission and parse/fold on detached candidate state. This must include
   strict/observer/grant checks, reserved `_decl.*` checks, and boundary
   selection. Source execution is deliberately deferred to 3B; 3A handles one
   ordinary fact whose source execution has already produced its input. A
   rejected parse, fold, authorization, or stale declaration must happen
   before any ledger call.
4. Convert the result into `RecordDraft`s. Use the existing body grammar and
   preserve the authored inner fact commitment, including exact payload text,
   `(kind, ts, observer, origin, payload_text)`, and any carried signature.
   Fresh local authorship uses the configured signer for the inner fact
   commitment and, separately, the coordinate-independent outer arrival
   commitment. An optional signer may return no signature where admission
   permits unsigned authorship. Foreign admission and migration preserve the
   source claim and follow their own unsigned outer-envelope rules; they must
   not be used as the template for fresh local authorship.
5. Add an automatic tick draft after the candidate fold when a boundary fires.
   Its body must describe the post-fact candidate state, use the destination
   custodian as observer, and retain the local chain fields and inner signature
   required by the signing-era floor. Its outer arrival envelope is unsigned.
   Foreign tick admission's null-chain rules do not apply to this freshly
   authored tick. The fact and tick drafts go to one
   `ledger.append(expected, drafts)` call.
6. On success, publish the prepared fold and refresh/reconstruct from the
   committed `Commit.after`. On failure after durable append, raise or return a
   typed committed/unknown result containing the commit/head and record IDs.
   A projection or reconstruction failure must never be translated into an
   uncommitted refusal or retried as a new append.

This is the smallest useful slice because it establishes the custody boundary
without first redesigning every read DTO or deleting the legacy store. It also
moves rejection before durability, which the current `Vertex.receive_receipt`
ordering cannot guarantee.

### Batch and source execution follow-up

The next slice, 3B, extends the same planner to source execution and SDK batch
emission. It must prepare all facts and all generated ticks before one append
call. `arrival_body.body_of_batch` can encode a same-observer group, while
`FileLedger.append` already accepts a sequence of drafts and commits that
sequence atomically. Therefore mixed-observer input is not an automatic
refusal: group it into the existing batch form when representable, or emit a
sequence of separate fact/batch drafts in the same append call. Preserve the
API's item boundaries and never silently turn one SDK call into independent
ledger appends. If the backend's atomic record limit cannot fit the complete
sequence and ticks, report that limit before mutation.

`emit_batch` should then return receipts tied to one `Commit`, or an explicit
atomic-limit/refusal result. It must not loop over independent appends while
claiming atomicity. If a later operation can fail after a durable append, the
SDK result must expose committed/unknown state and identity so reconciliation
can inspect the existing record rather than duplicate it.

## Initialization, declarations, and identity

Fresh initialization has two roles that must not be conflated, although the
current arrival-canonical identity value is deliberately shared:

* `ArrivalLog.mint` (or the equivalent backend mint operation) creates the
  ordinary signed arrival genesis/key root. It is the ledger's first identity.
* The declaration genesis is a subsequent signed `_decl.genesis` control
  record whose payload carries the declaration's own lineage marker. In the
  current arrival projection, `licensed_own_lineage` licenses the marker only
  when the consumed `_decl.genesis` FACT ID equals the physical arrival
  ledger's lineage. Thus the roles differ (ledger root versus declaration
  anchor), but their identity value is equal; the anchor's `own_lineage` and
  `genesis.id` must both equal the physical ledger lineage.

The initializer should use an intent/recovery boundary for the gap between
those operations. The declaration draft must use the already-minted physical
lineage as its fact ID (the arrival backend's ceremony identity rule), rather
than minting a second lineage value. A failure after the ledger genesis is
durable must be recoverable by identity; it must not mint a replacement root.
Initial config facts can follow in one writer batch once the declaration
anchor exists. Legacy migration may carry foreign declaration genesis rows,
but only a local marker licensed by this exact ID equality becomes self.
Migration/fresh initialization remain distinct callers: migration preserves
authored source commitments through the sidecar transformer, while fresh init
uses the new authority writer. No in-band migration receipt is needed.
The migration sidecar still owns its separate obligations: read a stable
legacy snapshot, mint target genesis/key records from the declared observers,
append transformed groups through the ordinary sink, and publish its signed
report/bootstrap evidence out of band. Its explicit legacy mixed-group design
decision remains a migration concern; it must not be inferred from the
runtime SDK batch rules below.

Declaration edits should retain `plan_declaration_update`, its allowlist, and
the durable `.intent` file replacement protocol. Preparation must:

* resolve the exact declaration lineage and current declaration control head;
* compare the caller's expected declaration head and the full ledger head
  before appending;
* create the signed `_decl.*` drafts with one timestamp and payload lineage;
* append the complete edit as one arrival batch through the authority ledger;
* replace the file cache only after the commit, leaving the intent in
  needs-recovery state if cache projection fails.

`adopt` is an explicit descriptor lineage designation operation and should
remain separate from ordinary runtime edits. `reanchor` rewrites identity and
is intentionally dead. An edit must survive reconstruction at the new
prefix; a reanchor must not become an accidental alias for it.

## Required invariants

| Invariant | Implementation rule | Failure result |
| --- | --- | --- |
| Full-head CAS | Capture `(lineage, ordinal, predecessor/hash)` and pass it unchanged to one `append`. | `HeadMismatch` leaves the ledger and attestation journal unchanged and is safe to retry after refresh. |
| Authored commitment | Preserve inner signature and exact payload text; destination custody does not rewrite it. | Admission refusal before append, with no new record. |
| Outer signature | Keep outer arrival signature separate from inner fact signature. Use only the designated authority/founding key where the wire rule calls for it. | Typed signature/authority error before append. |
| Authority designation | Supported writers require descriptor `role=authority`; replica/archive handles cannot mutate. | `NotAuthority` before append. |
| Declaration identity | `own_lineage` and `genesis.id` equal the physical ledger lineage; later control payloads carry that same lineage. | Refuse without ledger/journal mutation. |
| Fold/boundary ordering | Compute candidate fold and tick body before append; publish state only after commit. | Parse/fold rejection leaves no bytes; postcommit projection failure is committed/unknown. |
| Witness distinction | `AttestedLedger` may have a durable commit followed by `NotWitnessed`. Preserve the commit identity. | Do not retry blindly; reconcile by head and record IDs. |
| Replay | Scan an already committed prefix without executing receives or firing boundaries. | No duplicate tick or history. |
| Batch boundary | Preserve one body/record boundary for a valid same-observer batch, or separate draft boundaries inside the same atomic append for mixed observers; include associated ticks in that append. | Invalid item or atomic-limit failure leaves zero new records. |

## Adapter-owned binding identity prerequisite

There is a separate seam that must be resolved before calling this path
backend-neutral. `arrival_head_seam.canonical_location` currently applies
`Path.resolve()` to every location, while the backend contract explicitly says
that a location may be a path, DSN, or service URL and is interpreted only by
its adapter. The registry correctly keeps non-file locations opaque in
`descriptor_for`, but `AttestedLedger` still stores `_canonical` and uses
filesystem `_identity_of`/path-based binding helpers. A DSN can therefore be
mangled against the process cwd, and an adapter cannot provide its own stable
binding identity.

The smallest contract decision is to move binding identity behind the opener:

* the adapter returns an opaque, adapter-owned binding key (for the file
  adapter this retains canonical path aliases and live `(st_dev, st_ino)` alias
  detection); and
* the seam journals and compares that key without calling `Path.resolve()` or
  `Path.stat()` itself. Non-file adapters may use a normalized DSN or a server
  identity supplied by the adapter, but the seam must not guess.

Until that decision lands, stage 3 may use the file adapter through the
existing seam, but it should not claim that arbitrary descriptor locations are
safe. This is a concrete precondition for backend-neutral writes, not a reason
to add a second ad hoc path canonicalizer to the runtime writer.

### Binding provider shape without changing the opener tuple

The existing `BackendOpener` return type is already consumed by SDK/Terra and
should remain `tuple[ArrivalLedger, ArrivalQuery]`. Put binding policy in the
registry's registration metadata instead of adding a third return value:

```text
BackendRegistration(
    opener: BackendOpener,
    binding_provider: Callable[[StoreDescriptor], BindingIdentity],
)
BindingIdentity = backend-namespaced opaque key + adapter diagnostics
```

`BackendRegistry.open` keeps its current tuple. A separate registry lookup
supplies the binding identity to the attestation seam (or the registry wraps
the seam construction), so the seam compares the provider's key and does not
interpret `descriptor.location`. The file provider retains today's canonical
path, live `(st_dev, st_ino)` alias check, and `bindings.jsonl` location/lineage
compatibility; its opaque key can be namespaced as `file:` while keeping those
legacy records readable. A remote provider can return a namespaced key such as
`postgres:` derived from its own endpoint/instance identity and leave the DSN
text unchanged. This is a registration policy decision, not a change to the
adapter opener protocol.

A focused regression should make the boundary executable. Open a file
descriptor through a symlink (and, on the host, a case-variant alias), bind its
lineage, then present a replacement lineage through the alias; the existing
file adapter identity check must still raise `LineageReplaced` before journal
write. Separately pass a fake registered adapter a location such as
`postgresql://node/db?sslmode=verify-full`; assert that the adapter receives
that exact string and returns its opaque binding key, while the seam performs
no `Path.resolve()` or `Path.stat()` on it. This test requires only the
adapter-owned binding result and does not require a second backend or a live
service.

## Affected files and dependency order

The first implementation should touch a small set of owners:

* Add a planner/coordinator module under `libs/engine/src/engine/` (for
  example, `runtime_write.py`) with no `SqliteStore` import. Reuse admission,
  `arrival_body`, declaration, and contract types.
* Add the minimum descriptor-first materialization/writer hook in
  `compiler.py`, `program.py`, and `handle.py`. Remove the old credential
  mutation of `vertex._store` from the ordinary writer path rather than
  teaching the planner about that private object.
* Adapt `vertex.py` so receive/fold/boundary planning can run detached and
  returns drafts plus candidate state. Leave legacy store calls available to
  migration/compatibility callers until their cutover.
* Integrate declaration preparation with `ceremony.py` and `declaration.py`;
  do not delete intent/recovery or make SQLite the new coordinator.
* Rewire `libs/sdk/src/sdk/emit.py`, `kind.py`, and the initialize command only
  after the engine slice is tested. Stage 5 can delete old writer modes once
  all callers use the registry.
* Resolve the adapter binding-key contract in the registry/head seam before
  registering a non-file backend. Preserve existing file alias detection and
  lineage journal bindings while moving the filesystem operations into the
  file adapter.

Dependencies are descriptor/registry contracts, then the detached planner,
then one-fact writer, then batch/source execution, then declaration/init and
SDK/CLI wiring. Terra's query snapshot API is needed for the read half, but
the planner must not wait for a broad query rewrite. The legacy SQLite
projection remains a compatibility dependency only until the file adapter can
materialize the committed prefix through the new query path.

## Concrete acceptance tests

The 3A test set should be small but adversarial:

1. **Ordinary authority write.** An explicit file descriptor opens through the
   registry, performs one append, and returns a commit whose record body,
   authored inner signature, lineage, and predecessor are exact. An import or
   fake-adapter spy proves no direct `SqliteStore` authority call occurs.
2. **Refusal leaves no append.** After a descriptor has been opened and its
   open-time attestation outcome recorded, malformed payload,
   strict/admission failure, reserved declaration namespace, wrong
   observer/grant, and stale full-head CAS leave the arrival log, ledger head,
   and any new append journal entry unchanged. Tests must distinguish this
   from an independent open that legitimately earned a bootstrap or advance
   attestation before the write was attempted.
3. **Boundary in one commit.** A fact that fires a count/vertex boundary
   appends the fact and tick in one ledger call. The tick reflects candidate
   post-fact state, uses the target custodian, and preserves the fresh local
   tick chain and required inner signature. Reconstructing/replaying the
   prefix creates no second tick.
4. **Committed projection failure.** Inject a query/projection failure after
   ledger durability. The result exposes committed/unknown state with
   `Commit.after` and record IDs; retry/reconciliation finds the same records
   and does not append duplicates.
5. **Batch atomicity.** An invalid second item or backend atomic-limit failure
   produces zero new records. Same-observer input may be one arrival batch;
   mixed-observer input may be a sequence of separate drafts, but all records
   and generated ticks share one append commit. No item is committed as a
   prefix when a later item refuses.
6. **Declaration edit.** A stale declaration head refuses without log/cache
   mutation. A valid edit creates signed `_decl.*` records with one timestamp
   and matching anchor lineage. Cache replacement failure leaves durable intent
   for recovery; reconstruction sees the edit. `adopt` is explicit and
   `reanchor` is unavailable.
7. **Initialization identity.** Fresh init produces one ordinary ledger
   genesis/key root, then a declaration genesis whose FACT ID equals the
   physical ledger lineage, then config through the writer. A failure between
   root and declaration bootstrap recovers by the existing identities rather
   than minting a second root.
8. **Binding identity.** The file adapter retains symlink/case/live inode alias
   detection and refuses a replacement lineage. A fake non-file adapter gets
   an opaque DSN unchanged and supplies the binding key; no seam code resolves
   it as a local path.

## Follow-on slices and risks

After 3A is green, 3B adds source execution and atomic SDK batches. 3C wires
declaration edits and fresh initialization. Only then should stage 5 remove
old canonical store modes. The main technical risk is detached fold planning:
copying a mutable `Vertex` may lose loop state or epoch semantics, while
reusing `Vertex.receive_receipt` would append before it knows whether folding
will refuse. The implementation should add an explicit planning hook or a
storeless candidate state, with IDs reserved before planning when IDs affect
the fold, and no live boundary side effects.

Other risks are bounded by the acceptance tests: a generated ID must remain a
stable identity across reconciliation; an unknown post-commit error must never
be retried as uncommitted; declaration cache/file and ledger commits cannot be
one filesystem transaction, so intent/recovery remains the bridge; and a
backend atomic limit must cause a preflight refusal rather than a prefix
commit. These constraints keep the slice incremental without retaining SQLite
as an independent authority.
