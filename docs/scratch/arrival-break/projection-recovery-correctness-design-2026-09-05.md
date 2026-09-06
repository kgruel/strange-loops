# Explicit projection recovery for restore-forward

Status: recovery procedure proposal, not implemented in this pass. The exact
row and anchor audit is now implemented privately in `arrival_restore.py`;
the shared audit result and recovery APIs below describe the proposed next step.

## Problem and boundary

Restore-forward must not install trusted custody records underneath unrelated
derived rows. A projection watermark only identifies a claimed coordinate. It
does not prove that the rows below that coordinate were derived from the same
ledger prefix. A same-height forked projection therefore passes ordinal
containment unless the operation compares the complete projected content.

Ordinary projection maintenance cannot safely repair this case. It opens the
receiver through normal attestation, and a restore candidate may legitimately
be below the lineage journal. A failed restore can also have advanced that
shared journal when it opened the trusted source. Lowering or bypassing the
witness to make maintenance open would turn recovery into acceptance of the
condition the witness was designed to refuse.

The smallest complete path has two additions:

1. a pure, backend-neutral, full projection-to-ledger audit used by explicit
   restore and recovery; and
2. a source-aware projection-recovery coordinator whose destructive adapter
   authority remains private behind the registry.

`sync_projection` remains catch-up only and
`MaintenanceCapabilities.rebuild` remains false. Query snapshots and ledger
handles gain no mutation methods.

## Full projection audit

The neutral audit accepts an already-open ledger, its separate query half, and
a captured full head:

```python
audit_projection_prefix(
    ledger: ArrivalLedger,
    query: ArrivalQuery,
    *,
    captured_head: Head,
) -> ProjectionAudit
```

It opens an `ALLOW_BEHIND` snapshot, resolves the reported `Watermark` through
`ledger.head_at`, and requires the represented ordinal not to exceed the
captured head. It reads every fact with
`FactRequest(limit=None, include_internal=True, order="oldest")` and every
tick. The two row streams are merged by
`(arrival_ordinal, arrival_seq)` and compared to `ledger.scan` expanded by the
Arrival body grammar through the represented head.

Comparison uses exact retained evidence: stored payload text, fact signature,
and every tick predecessor, window and signature field. Parsed payload equality
is insufficient because signatures bind the stored text. Missing rows, extra
rows, duplicate coordinates, changed IDs, changed fields and reordered batch
expansions are divergences.

The declaration anchor is checked separately. `own_lineage` is absent unless
the projected rows contain the exact `_decl.genesis` whose fact ID equals the
physical Arrival lineage. When the marker is present, its selected genesis must
be that exact row. A foreign genesis remains inert. This prevents an otherwise
row-identical projection from changing which declaration lineage it presents.

An absent projection returns an explicit absent result. An exact projection
returns its resolved head, row counts and opaque `view_generation`. Divergence
raises a typed value carrying the raw watermark when available, the first bad
coordinate or anchor field, and a stable reason. The snapshot is closed on
every outcome. This audit never repairs or journals.

The audit is deliberately O(N). It belongs on explicit restore and recovery,
not ordinary reads. `view_generation` can detect that projection content
changed, but it is a digest of the projection itself and cannot prove that the
content came from custody.

## Source-aware recovery operation

The public operation should state why a receiver that may be below its witness
is allowed to rebuild derived state:

```python
recover_projection_for_restore(
    registry: BackendRegistry,
    source: StoreDescriptor,
    receiver: StoreDescriptor,
    *,
    through: Head | None = None,
) -> ProjectionRecoveryResult
```

The registry owns the procedure. It never returns a ledger, query, raw backend
maintenance handle, or filesystem path chosen by the core.

The procedure performs these steps in order:

1. Require explicit supported roles on source and receiver.
2. Open and attest the source normally. Capture its head, select `through`, and
   fully verify the selected prefix.
3. Open receiver components through the registry's private component seam.
   Verify its actual `before` head at `Open` and `Full`; require the same
   lineage, `before.ordinal <= selected.ordinal`, and exact source containment
   at `before`.
4. Run the pure head observation against the receiver's binding and journal,
   presenting the bounded source proof at `selected` and omitting the damaged
   query. Require a definite `Compared` outcome. This applies rollback bounds,
   fork decisions, indeterminate-journal refusals and abandoned-history fences
   without writing a receiver witness.
5. Audit the receiver projection against its actual `before` prefix. If it is
   exact, return `already-exact`. If it is absent, the recovery provider may
   materialize it. A typed mismatch is the evidence that licenses archive and
   rebuild.
6. Only after every custody and witness gate succeeds, obtain the backend's
   privately registered `ProjectionRecovery` handle. The adapter archives the
   original projection, quarantines new query opens, rebuilds from ordinal zero
   through `before`, and stamps only the verified resulting watermark and
   licensed declaration identity.
7. Reopen and repeat the full neutral audit through `before`. Remove the
   quarantine only after this audit succeeds. Do not write a witness: this
   operation changed no custody, and the receiver may remain below the source
   backed journal until restore-forward lands.
8. Return whether the receiver custody still equals `before`. The caller then
   retries ordinary restore-forward, whose full-head CAS, commit receipt and
   witness rules remain unchanged. Projection catch-up from `before` through
   the restored head remains an explicit subsequent operation.

The selected source head is proof of the intended restoration, not permission
to rewrite the receiver ledger. Recovery rebuilds only what the receiver
currently contains. It never projects source records that have not yet been
committed to the receiver.

## Private adapter contract

Recovery is a separate capability from routine maintenance:

```python
class ProjectionRecovery(Protocol):
    def capabilities(self) -> ProjectionRecoveryCapabilities: ...
    def rebuild(self, through: Head) -> ProjectionRebuildAdvance: ...
    def resume(self, recovery_id: str, through: Head) -> ProjectionRebuildAdvance: ...
    def close(self) -> None: ...
```

The registry holds a private `ProjectionRecoveryOpener`, parallel to its
private maintenance opener. The opener is reachable only after the coordinator
has established source, receiver, binding and witness evidence. There is no
public raw `open_recovery`, no optional attestation flag, and no method added to
`ArrivalLedger` or `ArrivalQuery`.

`ProjectionRebuildAdvance` reports an opaque recovery ID, observed prior
watermark or unknown state, resulting watermark, archive receipt, whether rows
changed, and whether this call completed a prior attempt. The core does not
interpret archive paths or formats.

For the file adapter, rebuild is bounded and starts at ordinal zero. Partial
replay would renumber row IDs and invalidate existing witness cursors. The
adapter uses the same deterministic body expansion as live indexing, drops
derived search state, and inserts no row beyond `through`. A foreign
`own_lineage` marker remains a refusal in the first implementation. Overriding
that identity claim needs a separate incident decision and is not required to
repair the demonstrated forked rows.

## Preserve and quarantine the original projection

A same-height forked projection can contain the only local evidence of the
discarded branch. An explicit rebuild must not erase it before preserving it.
The adapter therefore owns an archive-and-quarantine protocol:

1. Acquire one adapter recovery lock also honored by catch-up and later
   recovery attempts.
2. Revalidate the target head and current projection under that lock.
3. Durably create a unique recovery intent containing the target head, prior
   audit classification, archive state and no secret locator ingress.
4. Create a consistent logical archive of the committed projection. For
   SQLite this uses the backup API from a read transaction so WAL content is
   included correctly; copying the main database file alone is invalid. Close
   and fsync the archive, compute its SHA-256, atomically publish it under a
   unique name, and record the opaque archive receipt in the intent.
5. Only after the archive receipt is durable, begin the live projection's
   rebuild transaction.

The durable intent is the quarantine marker. New file-query snapshots refuse
while it exists, and catch-up refuses or joins recovery instead of writing into
the projection. Existing snapshots cannot be revoked; they retain their old
basis and generation, and SQLite prevents them from seeing a half transaction.

The archive is a logical copy of all committed projection schema, tables and
metadata. It is not claimed to preserve transient page layout or uncommitted
WAL bytes. That is the evidence level the query surface used. The archive
survives successful recovery and its receipt is returned. Recovery never
automatically restores the archive, because that would silently reintroduce
the mismatch. A later incident-only restore-archive verb may use it after an
operator reviews the evidence. Until rebuild commits, the live original is
also unchanged, so cancellation is reversible by removing only a verified
pre-rebuild intent.

Adapters with different storage choose their own equivalent archive,
transaction and quarantine mechanism. The core contract asks for durable
preservation and an opaque receipt; it does not prescribe SQLite paths.

## Outcomes

`ProjectionRecoveryResult` has no `Commit`, because custody did not change. It
contains:

- source captured and selected heads;
- receiver `before` and post-operation observed heads;
- prior projection audit evidence;
- resulting projected head and generation when established;
- opaque archive receipt, or `None` for absent/already-exact projections;
- status, `changed`, `rebuilt`, and `ready_for_restore`.

Successful statuses are exact and mutually exclusive:

| Status | Meaning |
| --- | --- |
| `already-exact` | Full audit already matched; no archive or rebuild occurred. |
| `materialized` | No prior projection evidence existed; a projection was built. |
| `rebuilt` | Prior evidence was archived and the replacement passed full audit. |
| `receiver-advanced` | The requested prefix was rebuilt and audited, but custody advanced concurrently; restore must recapture. |

Failures preserve their phase and evidence:

- `ProjectionRecoveryRefused`: a source, receiver, witness, identity or
  pre-mutation capability gate refused; original projection is untouched.
- `ProjectionRecoveryUnknown`: archive/rebuild was entered and the caller
  cannot establish whether the derived commit landed. It carries recovery ID,
  target, archive receipt when known, prior evidence and best-effort observed
  projection. The intent remains.
- `ProjectionRecoveryIncomplete`: rebuilt projection is known committed but
  post-audit or quarantine cleanup failed. It carries the established
  projected head, archive receipt and retained intent.

These types never imply that a projection result is a custody receipt.

## Crash and race behavior

- **Before intent:** no projection mutation and no archive claim.
- **Intent before archive:** live projection is unchanged and quarantined.
  Resume verifies the intent and creates the archive; it never overwrites an
  existing archive name.
- **During archive:** an unpublished temporary archive is ignored and cleaned
  only after its intent identity is verified. Rebuild cannot start without a
  durable archive receipt.
- **During rebuild:** one SQLite transaction contains row deletion, complete
  replay, identity derivation and watermark stamp. Rollback preserves the old
  live projection; no partial watermark can commit.
- **Commit acknowledgement lost:** the intent remains. Resume audits the live
  projection. Exact content advances to post-audit; other content is rebuilt
  again from verified custody. The original archive is retained.
- **After rebuild before audit or cleanup:** new query opens remain
  quarantined. Resume re-audits before removing the intent.
- **Concurrent projection catch-up/recovery:** the shared adapter lock
  serializes them. State is re-read under the lock. A valid newer projection is
  never rewound to the requested head; report no-op/stale and recapture.
- **Concurrent receiver append:** the captured prefix remains valid, so a
  bounded rebuild may finish honestly behind. The final receiver head differs,
  `ready_for_restore` is false, and restore-forward recaptures rather than
  using stale CAS evidence.
- **Concurrent source append:** `selected` remains fixed and no later source
  record enters the operation.
- **Custody rewrite or interior corruption:** full verification or target
  revalidation refuses before projection mutation.
- **Restore race after recovery:** ordinary restore's exact-head CAS is the
  authority. A failed CAS does not undo the valid rebuilt projection.

## Why no additional source hash is needed

A `Head` contains lineage, dense ordinal and the chained record hash. Full
verification through the receiver's `before` head, exact containment in the
selected source, adapter revalidation under lock, and the full post-rebuild
row audit bind the complete canonical prefix. Another projection digest would
only name derived bytes; it would not add provenance.

An opaque projection generation becomes necessary if preparation and rebuild
are split into independently callable phases. This design keeps proof and
mutation in one registry-owned operation and revalidates under the adapter
lock, so no new public projection-CAS token is needed.

## Necessary now and later

Implemented to stop the demonstrated incorrect restore success:

- full neutral projection row and declaration-anchor audit before and after
  explicit restore.

Still needed to provide usable recovery after that refusal:

- source-aware registry recovery with no witness lowering;
- a separate private recovery provider;
- durable archive/quarantine before destructive rebuild;
- bounded ordinal-zero replay, final audit, typed unknown/incomplete outcomes,
  and race tests.

Later work can add generic recovery when receiver custody and witness already
agree, replacement of an unopenable SQLite file, foreign declaration-identity
incident recovery, signed recovery receipts, remote provider implementations,
or a combined restore-and-rebuild ceremony. None should be inferred from this
first operation.
