# `migrate` — Migration Sidecar

The `migrate` package transforms pre-Arrival legacy stores into a new Arrival
history. Legacy readers and codecs remain quarantined here: active runtime
packages do not import `migrate`.

The sidecar preserves source rows under the selected transform, verifies the
resulting log and row equivalence, writes a signed external report, and publishes
an explicit File descriptor with the minted lineage and `role="authority"`.
It checks that the vertex bytes captured for transformation have not changed
at publication entry and immediately before replacement. This is an offline operation on quiescent inputs; the check
is not a lock or an atomic compare-and-swap against concurrent writers.

**Publication does not adopt a declaration.** The descriptor can be resolved,
verified, and explicitly synced through the SDK. The new log still needs an
explicit declaration adoption before ordinary SDK reads, declaration edits, or
writes can proceed. Historical `_decl.*` rows are retained as migration evidence;
the current runtime does not infer the new store's identity from them or from
its locator file. The old `loops store migrate` wrapper is therefore not a
complete migration-to-current-runtime workflow.

Use isolated copies for rehearsals, with separate state/configuration and
credential roots. Keep the original stores and descriptors untouched. SQLite
copies must come from quiescent inputs or a coherent database snapshot.

The exported `edit_vertex_store_clause` helper now requires explicit `lineage`
and `expected_original` byte arguments. Direct callers must supply the exact
vertex snapshot used for planning; `run_migration` supplies these itself. An
error after replacement (for example, directory fsync failure) can leave the new
descriptor visible. Inspect the artifacts before retrying. An exact explicit
`resume_target` can re-verify an already published migration without replacing
the descriptor. It does regenerate, re-sign, and replace the migration report;
changing `tool_version` changes that signed report. This is not a general
recovery or adoption API.

Descriptors from the previous sidecar that contain `backend="file"` but omit
lineage or role are refused by the new existing-descriptor guard. They need
explicit descriptor reconciliation before this resume path can apply; adding
those fields alone still does not adopt their declaration.

## Offline descriptor publication

`publish_candidate_descriptor(PublicationRequest(...))` is the narrow final
publication primitive for an already reviewed and adopted candidate. All paths
are explicit absolute `Path` values, including the prepublication backup and
exclusive receipt. It streams the legacy-source and Arrival-store hashes,
re-parses the pinned descriptors, and requires the candidate's one store clause
to be an absolute `backend="file"`, `role="authority"` location naming the
already-final Arrival file using the exact approved backend location spelling
and the reviewed full head's lineage. Both descriptor-declared file leaves must
be regular files, not symlinks. The original must be a legacy descriptor; this
is not an Arrival-to-Arrival routing or authority-transfer operation. It never
opens the Arrival protocol, reads credentials, consults witness state, verifies
a report, or adopts anything.

The request separately carries caller assertions for the reviewed adoption
head, provenance reference, and quiescence transcript. The versioned receipt
labels these assertions as unverified by this primitive; matching Arrival bytes
does not prove A, report signatures, provenance, or writer quiescence. It uses
an exclusive backup, an exclusive deterministic same-directory stage,
`os.replace`, and directory fsync. New backups and receipts are private (0600).
The complete stage takes the live descriptor's POSIX mode before fsync; that
mode is checked again before and after replacement and recorded in the receipt.
Ownership, ACLs and extended attributes are not copied. This is atomic replacement
under caller-held quiescence, not CAS. Existing stage or receipt paths refuse;
a matching backup alone can be reused. Failures retain artifacts as evidence.

`PublicationError` exposes `phase`, `effect`, paths and pins. Effects refer only
to live-descriptor replacement: `not_attempted` can still leave backup/stage
artifacts; `replace_entered_unknown` means the replacement call raised;
`replace_returned_unverified` means it returned but directory sync or final
bytes/mode verification failed. `known_published` requires directory sync and
verified live bytes/mode, but does not promise receipt completion or continued
immutability. None is permission to blindly retry. Artifact existence is not
re-probed during error serialization. Alias checks cover the declared roles,
not every external hard link or consumer. Existing parent directories are a
trusted, quiescent namespace, not protected against hostile concurrent
parent-symlink replacement.

The migration report certifies the head at migration completion. Its current
verifier requires that exact live head, so verify it before a later adoption or
ordinary append advances the target. Structural Full verification without an
injected signature verifier does not establish historical authorship.

See the [publication report](../../docs/scratch/arrival-break/consistency-c9-migration-publication-2026-09-06.md)
and [adoption design](../../docs/scratch/arrival-break/consistency-c9-migration-adoption-design-2026-09-06.md).
The historical sidecar design is recorded in
[the slice 4 proposal](../../docs/scratch/arrival-break/slice4-design-proposal.md).

## Offline copy rehearsal

Repository-local `scripts/arrival_rehearsal.py` runs the migration/report/adoption/
read/write/export checks against already-copied inputs under an explicit private
sandbox. `scripts/arrival_rehearsal_recovery.py` exercises both durable adoption
interruption points on separate prefix copies with signing credentials offline.
Both accept `--help`; they are rehearsal tools, not a live cutover command.

The loops store rehearsal established these constraints:

- Empty historical observer labels are refused. The separately authorized
  `scripts/prepare_legacy_unattributed.py` preparation policy maps only unsigned
  flat facts with exactly empty observers to `legacy/unattributed` and produces
  a row/hash audit manifest. It never runs implicitly during migration, and
  its output is a distinct source. The migration report certifies that prepared
  source; the preparation manifest links it to the untouched archive.
- Preserved legacy boundary ticks can predate declaration adoption and prevent
  ordinary writes under the continuity contract even when reads and export work.
  Explicit `--runtime-epoch fresh` adoption starts declared initial execution
  state after the adoption ordinal and enabled writes on the loops copy. Strict
  remains the default; historical facts/ticks stay queryable in either mode.
- Observer mapping changes fact hashes. On the loops copy it invalidated 39
  retained historical tick-window commitments; the original archive passes.
  Migration preserves the prepared facts and old tick rows without rewriting
  commitments. Full Arrival verification is not a clean historical tick audit.
  Keep the original archive and mapping manifest, and use the provenance
  verifier below to prove the accepted transformation before live cutover.

See the [real-store rehearsal report](../../docs/scratch/arrival-break/loops-real-store-rehearsal-2026-09-18.md)
for the exercised scope, evidence, and remaining historical-commitment limitation.

### Verify the audited observer mapping

`scripts/verify_legacy_provenance.py` independently verifies the supported flat,
zero-drop `legacy-unattributed-v1` preparation through a reviewed migration head:

```sh
uv run python scripts/verify_legacy_provenance.py \
  ORIGINAL.jsonl PREPARED.jsonl MANIFEST.json TARGET.arrival \
  --reviewed-source-sha256 ORIGINAL_SHA256 \
  --reviewed-manifest-sha256 MANIFEST_SHA256 \
  --migration-lineage LINEAGE \
  --migration-ordinal S_ORDINAL \
  --migration-record-hash S_RECORD_HASH \
  --output NEW_EVIDENCE.json
```

Supply the source/manifest hashes and S from independently retained reviewed
evidence, not claims freshly extracted from untrusted input. The verifier checks
all mapped and unchanged rows, the original tick chain, exact ordered preservation
through S, and all later tick-chain windows. Unsupported inputs or unexplained
changes refuse. Output creation is exclusive; inputs are never repaired.

A successful result says `preserved-boundaries-with-audited-transformation`.
It distinguishes explained historical windows from unchanged windows and does
not claim historical authorship. It verifies registry-forming Arrival signatures;
verification of the signed migration report remains a separate step at S.
The standard deep audit is unchanged and still reports changed historical windows.

See the [verification contract](../../docs/scratch/arrival-break/legacy-provenance-verification-2026-09-18.md)
and [cutover plan](../../docs/scratch/arrival-break/loops-live-cutover-plan-2026-09-18.md).
