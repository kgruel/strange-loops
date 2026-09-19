# Loops live Arrival cutover plan

This is an execution plan for a future, separately authorized maintenance
window. It does not authorize a live migration, key access, descriptor swap or
write. It uses the user-approved `legacy-unattributed-v1` transformation and
the fresh runtime epoch; it does not recast the old tick-window commitments as
unchanged commitments over the prepared archive.

The September 18 copy rehearsal is evidence for the path, not an input to this
cutover. Its source snapshot, prepared copy, lineage, report and credentials
are never promoted to production. The live window starts with a new snapshot
and independently captured pins.

## Supported runtime boundary

Use the descriptor-first SDK after the descriptor is published:

- Reads and inspection: `inspect_declaration`, `read_summary`, `read_facts`,
  `read_ticks`, `read_state`, `read_timeline`, `search_facts`, `sync_target`,
  and `verify_target`.
- Writes: `preview_emission`, `emit_fact`, `emit_batch`,
  `edit_declaration`, and the SDK kind-mutation APIs, with a mapped credential
  provider.
- Source/cadence execution: asynchronous `run_sources`, with an explicit
  observer, mapped provider, collector factory, and dispatcher supplied by the
  production job. It requires one Arrival Authority vertex.
- Preservation: `export_target` creates an exclusive exact Arrival export at a
  captured head.
- Adoption: `adopt_arrival(..., runtime_epoch="fresh")`; if an intent remains,
  only `recover_arrival_adoption(intent_path)` may reconcile it. Recovery has
  no signer or epoch argument.

Do **not** use `loops emit`, `loops sync`, `loops stream`, `loops read`,
`loops store`, `loops store absorb`, `loops store adopt`, `loops store reanchor`,
or `loops store reindex` against the candidate or live descriptor. Those
commands retain the legacy SQLite/canonical-store and `open_vertex` consumer
paths. This plan has not established a refusal for each command, including
`loops store absorb`; it makes no safety claim based on such a refusal. Keeping
them disabled is the protection. They do not form a reviewed Arrival-v2 writer
or reader handoff. In particular, `loops store migrate` is not the cutover
ceremony: it has no reviewed-snapshot, provenance verification, mapped-binding,
fresh-adoption, or recovery handoff.

The legacy source and its sibling SQLite index are archival inputs after the
swap. Neither is a fallback writer for an Arrival lineage.

## Inputs and durable locations

The maintenance owner records absolute paths and SHA-256 values in the cutover
receipt, without payloads or private key material. Keep `ORIGINAL_SOURCE_SHA256`,
`ORIGINAL_VERTEX_SHA256`, and `CANDIDATE_VERTEX_SHA256` distinct; the source
and descriptor pins are not interchangeable.

| Role | Required property |
| --- | --- |
| `LIVE_VERTEX`, `LIVE_SOURCE` | Existing production `.vertex` and canonical JSONL, captured after writer quiescence. |
| `CUTOVER_ROOT` | New access-controlled directory outside the repository and outside the live vertex directory. It contains snapshots, candidate, reports, exports and receipts. |
| `CUTOVER_STATE` | New durable `$XDG_STATE_HOME` for migration, adoption, recovery, and every later Arrival writer. It contains the authoritative Arrival head journal; it is not a rehearsal state directory. |
| `CUTOVER_BINDINGS` | New durable mapped-credential root. It is neither a copied rehearsal provider root nor `$XDG_STATE_HOME`. Its selected public binding is recorded in the receipt. |
| `ARCHIVE_ORIGINAL` | Immutable original JSONL/vertex snapshots plus a separately named, exclusively written prepublication vertex backup. Keep all of them after cutover. |
| `PREPARED_SOURCE`, `PREPARATION_MANIFEST` | Exclusive output of `prepare_legacy_unattributed.py`; retain both alongside the original snapshot. |
| `CANDIDATE_VERTEX`, `ARRIVAL_STORE` | A copied vertex and its lineage-named Arrival file minted directly in the final durable store directory. Before adoption, rewrite only the candidate descriptor text to name that same resolved path absolutely. |

No live private-key directory is reused as a rehearsal credential root. Migration
uses the approved current custodian signing capability only while writers are
quiesced. The production mapped provider is created in `CUTOVER_BINDINGS` from
the explicitly selected approved key reference or a controlled one-time legacy
import. Its public key must equal the captured declaration key. The private
credential source stays under its normal custody controls; recovery later uses
only public FACT and Arrival verification and must work with that source
offline.

Every candidate migration, report check, provenance check, adoption, recovery,
post-adoption SDK check, and later enabled Arrival writer runs with
`XDG_STATE_HOME` set to exactly `CUTOVER_STATE`. Do not inherit a rehearsal
state root or an operator's default state root. `CUTOVER_BINDINGS` is passed explicitly to
`MappedCredentialProvider`; it is never inferred from XDG state.

## Quiescence and fresh pins

Before taking any snapshot, stop and account for every process that can change
the canonical JSONL, its derived SQLite index, the vertex, or its adjacent
key/configuration files. The known inventory includes interactive `loops emit`,
scheduled or manual `loops sync` source runs, `loops init`, all `loops store`
mutators, local scripts using legacy stores, direct SDK/engine writers, and any
service using the vertex. Disable their schedulers and prevent new sessions;
record owners, process IDs or service revisions, and the time the stop took
effect. Readers may stay only if they do not repair, reindex, or write local
metadata into the cutover locations.

Take a new source and vertex snapshot only after that gate. The following are
the shell primitives to record in the operations transcript; substitute the
approved absolute paths and run them only in the maintenance window:

```sh
umask 077
mkdir -p "$CUTOVER_ROOT/original" "$CUTOVER_ROOT/prepared" "$CUTOVER_ROOT/receipts"
cp -p "$LIVE_SOURCE" "$CUTOVER_ROOT/original/project.jsonl"
cp -p "$LIVE_VERTEX" "$CUTOVER_ROOT/original/project.vertex"
shasum -a 256 "$LIVE_SOURCE" "$LIVE_VERTEX" \
  "$CUTOVER_ROOT/original/project.jsonl" "$CUTOVER_ROOT/original/project.vertex"
cmp -s "$LIVE_SOURCE" "$CUTOVER_ROOT/original/project.jsonl"
cmp -s "$LIVE_VERTEX" "$CUTOVER_ROOT/original/project.vertex"
```

The two `cmp` checks and matching hashes are a gate, not a best-effort log.
Capture the source hash again immediately before migration, before descriptor
publication, and after all pre-publication checks. Any change releases the
quiescence lock, abandons the candidate, and starts a new snapshot; no resume
against changed source is allowed.

## Audited preparation and provenance gate

Prepare only the copied JSONL. Its policy changes an exactly empty observer on
an unsigned flat fact to `legacy/unattributed`; it preserves IDs, payload text,
timestamps, order, all ticks, and every other field. It refuses a missing/null
observer, a signed blank observer, an input/output alias, overwrite, or no
eligible rows. The original snapshot remains immutable. Record the new snapshot's affected-row
count explicitly for review; the rehearsal count was 982, not a fixed expected
count for a later production snapshot.

Run the preparation utility with exclusive output and a new manifest, then pin
the original source and manifest hashes outside all inputs. The exact
provenance-verifier interface agreed for the cutover is:

```sh
uv run python scripts/verify_legacy_provenance.py \
  "$ARCHIVE_ORIGINAL/project.jsonl" "$PREPARED_SOURCE" "$PREPARATION_MANIFEST" "$ARRIVAL_STORE" \
  --reviewed-source-sha256 "$ORIGINAL_SOURCE_SHA256" \
  --reviewed-manifest-sha256 "$MANIFEST_SHA256" \
  --migration-lineage "$LINEAGE" \
  --migration-ordinal "$S_ORDINAL" \
  --migration-record-hash "$S_RECORD_HASH" \
  --output "$CUTOVER_ROOT/receipts/legacy-provenance.json"
```

This verifier is read-only, requires independent pins, and is limited to the
flat zero-drop preparation policy. It verifies the original historical
predecessor/cursor/window chain, the mapping manifest, the prepared prefix at
S, and later physical tick-chain evidence. A pass means **preserved boundaries
with audited transformation**. It does not claim old fact-window hashes were
unchanged after observer mapping. Migration report signature/authorship checks
remain a separate gate.

The verifier has passed the loops-copy rehearsal and Fable review. Repeat it
against the fresh quiescent production snapshot and independently retained pins
before this plan can run; the old rehearsal receipt is not a substitute.

## Candidate migration and adoption

Build a candidate vertex from the fresh vertex snapshot in `CUTOVER_ROOT`; do
not call migration with `LIVE_VERTEX`. Place its pre-migration source residence
so parsing the copied vertex resolves the store clause to exactly
`PREPARED_SOURCE`. Record the candidate bytes, its parsed source path, and that
resolved path before migration. This makes the reviewed original vertex bytes
and the published candidate differ only in controlled residence, while ensuring
the migration consumes the prepared copy rather than an accidental sibling.

The existing migration API publishes only into the vertex it receives, so using
a candidate keeps the live declaration unchanged during migration and adoption
gates. Pass the final durable store directory as `run_migration(store_dir=...)`
up front: its lineage-named `outcome.target_path` is `ARRIVAL_STORE`. Do not
move that file after minting; witness/location binding requires a separate
relocation ceremony that this plan does not invoke. After migration verifies S,
use `edit_vertex_store_clause` on the *candidate* to change only the textual
location to the absolute path resolving to `outcome.target_path`, retaining the
exact lineage. That call takes the candidate's exact pre-edit bytes and
re-parses the result, so it refuses a concurrent candidate change or a
non-store-field change. Re-run report verification and
`verify_target(..., through=S)` against the same physical store and rewritten
candidate before adoption.

The supported migration primitive is `migrate.sidecar.run_migration`, with the
prepared source, candidate vertex, the final durable store directory, the
approved custodian signer, and the identity transform. The preparation utility
has already performed the only allowed observer rewrite. It returns
`MigrationOutcome(target_path, lineage, head, report_path, exceptions)`.
Require zero dropped units, then pin `S = outcome.head` as lineage, ordinal and
record hash. Verify, before adoption:

```python
from migrate.sidecar import verify_migration_report
from sdk import verify_target

assert verify_migration_report(
    outcome.report_path,
    custodian_public_key,
    verify=report_signature_verifier,
    target_path=ARRIVAL_STORE,
)
assert verify_target(candidate_vertex, through=outcome.head).verified_through == outcome.head
```

`report_signature_verifier` is the explicitly supplied public verifier for the
report's signing domain. Save the report hash and the verified S coordinates
before any later append. Then run the provenance command above with those pins.
The source hash must still equal the fresh source snapshot at each gate.

Create or confirm the selected mapped binding in `CUTOVER_BINDINGS` before
adoption. Its FACT and Arrival requests must resolve to one captured public key
for the adoption observer. The SDK independently verifies both signatures; a
provider-local permissive verifier is not sufficient.

```python
from sdk import MappedCredentialProvider, adopt_arrival

provider = MappedCredentialProvider(
    CUTOVER_BINDINGS,
    namespace=CUTOVER_NAMESPACE,
    receipt_observer=CUTOVER_OBSERVER,
)
# Use exactly one reviewed binding operation, recorded with its token:
# provider.bind_existing_ref(...) or provider.import_legacy(...)

adopted = adopt_arrival(
    candidate_vertex,
    selected_head=outcome.head,
    reviewed_text=reviewed_vertex_text,
    reviewed_sha256=reviewed_vertex_sha256,
    declaration_text=candidate_vertex.read_text(encoding="utf-8"),
    observer=CUTOVER_OBSERVER,
    credentials=provider,
    runtime_epoch="fresh",
)
```

Require `adopted.commit.before == S`, `adopted.head == adopted.commit.after`,
`adopted.runtime_epoch == "fresh"`, `adopted.phase` published, and a caught-up
projection. If apply reports a retained intent, preserve it and use
`recover_arrival_adoption(intent_path)` with the dedicated public SDK verifier
configuration. Do not retry adoption with new signatures. A provably
superseded intent is stale evidence; preserve it and prepare a fresh candidate
only after recording the disposition.

At A, use the SDK to require all of the following from the candidate:

- `verify_target(..., through=A)` succeeds and `sync_target` is current at A.
- `inspect_declaration` reports the Arrival-backed effective declaration.
- `read_summary`, `read_facts`, and `read_ticks` retain the inventory history.
- `read_state` reports `runtime_epoch == {"mode": "fresh", "anchor_ordinal": A.ordinal}`
  and matches the reviewed declaration's initial fold sections.
- `export_target(..., through=A)` writes an exclusive exact export. Store its
  manifest and SHA-256 in the receipt.

Re-run `verify_legacy_provenance.py` at A with the same independent original,
manifest and S pins, writing a second exclusive `legacy-provenance-at-A.json`
receipt. Require its `arrival.captured_head` to equal A in all three fields and
retain its `arrival.sha256` as the post-adoption store hash used by rollback.
This binds the pre-publication Arrival state, including the adoption anchor,
to the audited transformation; it is not substituted for the signed
migration-report verification at S.

No rehearsal-only fact is written to production. The first post-cutover fact is
a separately authorized business operation.

## Publication and writer handoff

There are two distinct publication points:

1. Migration and adoption make durable records in `ARRIVAL_STORE`, while only
   `CANDIDATE_VERTEX` names them. This is pre-live evidence and does not change
   `LIVE_VERTEX`.
2. The final descriptor replacement makes the candidate declaration live. It
   must be an atomic same-directory replace that first confirms the live vertex
   still equals the pinned original bytes and then fsyncs the directory. Save
   a separately named prepublication backup under `ARCHIVE_ORIGINAL` (for
   example `project.vertex.prepublish`); do not overwrite it on a retry.

Prepare the final replacement file in `LIVE_VERTEX.parent` so the final
`os.replace` is same-directory. Under the already-held quiescence lock, a small
one-shot publication procedure must do the following in order:

1. Read `LIVE_VERTEX` and `CANDIDATE_VERTEX`; require their SHA-256 values to
   equal the recorded original and candidate pins. Re-parse the candidate and
   require its descriptor to name the final absolute `ARRIVAL_STORE`, the
   pinned lineage, and authority role.
2. Create and `fsync` the separately named prepublication backup exclusively,
   or, on a retry, require its existing hash to equal the original pin. Then
   create `LIVE_VERTEX.parent / ".<name>.arrival-cutover"` exclusively with
   the candidate bytes, `fsync` it, reread/hash it, and require the candidate
   hash again. An existing stage path refuses.
3. Reread and hash `LIVE_VERTEX` one final time. If it no longer equals the
   original pin, remove only the uninstalled stage file and refuse.
4. Call `os.replace(stage_path, LIVE_VERTEX)`, then open and `fsync` the parent
   directory. Reread/hash the new live vertex and require the candidate pin.

This is an atomic same-directory replacement under quiescence; it is not an
atomic compare-and-swap. Quiescence is the guarantee against a concurrent
editor; the two live-byte checks detect drift observed before replacement. The
procedure's receipt binds the old and candidate hashes, A, stable Arrival path,
backup hash, and replacement result.

```python
def publish_vertex(live: Path, candidate: Path, backup: Path) -> tuple[str, str]:
    old = live.read_bytes()
    replacement = candidate.read_bytes()
    old_hash = hashlib.sha256(old).hexdigest()
    replacement_hash = hashlib.sha256(replacement).hexdigest()
    if old_hash != ORIGINAL_VERTEX_SHA256 or replacement_hash != CANDIDATE_VERTEX_SHA256:
        raise RuntimeError("cutover input hash changed")
    stage = live.parent / f".{live.name}.arrival-cutover"
    if backup.exists():
        if hashlib.sha256(backup.read_bytes()).hexdigest() != old_hash:
            raise RuntimeError("existing prepublication backup hash mismatch")
    else:
        _write_exclusive_and_fsync(backup, old)
    if hashlib.sha256(backup.read_bytes()).hexdigest() != old_hash:
        raise RuntimeError("original backup hash mismatch")
    if stage.exists():
        raise RuntimeError("exclusive live-directory stage already exists")
    _write_exclusive_and_fsync(stage, replacement)
    if hashlib.sha256(stage.read_bytes()).hexdigest() != replacement_hash:
        raise RuntimeError("staged candidate changed")
    if live.read_bytes() != old:  # quiescence check immediately before replace
        stage.unlink(missing_ok=True)
        raise RuntimeError("live vertex changed during publication")
    os.replace(stage, live)
    _fsync_directory(live.parent)
    if hashlib.sha256(live.read_bytes()).hexdigest() != replacement_hash:
        raise RuntimeError("published vertex hash mismatch")
    return old_hash, replacement_hash
```

This is illustrative algorithm text, not an implemented cutover command.
`_write_exclusive_and_fsync` opens with exclusive creation, writes, flushes and
calls `os.fsync`; `_fsync_directory` opens the directory read-only and calls
`os.fsync`. Before use, the cutover transcript must add the step-1 descriptor
reparse and receipt serialization, then record a disposable-directory rehearsal
of the exact fragment.

Keep writers stopped through the replacement, reopen the descriptor only with
the SDK operations above, and repeat `verify_target`, `sync_target`,
`inspect_declaration`, `read_summary`, and `read_state` against `LIVE_VERTEX`.
Run `preview_emission` for the separately approved first business payload with
the production mapped provider against `LIVE_VERTEX`; require
`read_path == "arrival"` and `captured_head == A`, with no append. Record the
explicit `CUTOVER_BINDINGS` and `CUTOVER_STATE` paths used by that process and
confirm no binding or head-journal material was resolved from the candidate or
from a default-state root.
Only then hand each inventoried writer to a descriptor-first SDK integration:

- interactive/API fact writer: `preview_emission` then `emit_fact` with the
  production mapped provider;
- batch ingest: `emit_batch` with the same mapped provider and captured
  result/commit evidence;
- declaration management: `edit_declaration` and its recovery API;
- source/cadence jobs: `run_sources` with the production collector factory,
  dispatcher, observer, mapped provider, and `CUTOVER_STATE` environment;
- CLI-only workflows: remain disabled until they have a reviewed adapter to
  those descriptor-first SDK calls.

The handoff receipt names every enabled writer and its SDK version, plus how
each excluded legacy command or scheduled job was disabled. No legacy or raw
JSONL/SQLite writer is re-enabled.

## Failure disposition and rollback

Before final descriptor replacement, any failed migration, provenance, report,
adoption, projection or read gate leaves `LIVE_VERTEX` and `LIVE_SOURCE`
unchanged. Preserve the candidate Arrival file, report, intent and receipts as
evidence; do not truncate, delete, reuse, or append a second anchor. Resume is
allowed only through the documented migration/adoption recovery paths when
their exact input pins still hold.

After descriptor replacement but before any post-A business write, legacy
routing may be restored only when all of the following are recorded while
writers and source jobs are stopped:

- `verify_target(LIVE_VERTEX)` captures a head exactly equal to A in lineage,
  ordinal, and record hash; the Arrival file SHA-256 equals the recorded
  post-adoption A pin.
- `LIVE_VERTEX` SHA-256 equals the candidate pin, and `LIVE_SOURCE` SHA-256
  still equals its original snapshot pin.
- The exclusive same-directory restore stage is written from the separately
  named prepublication backup, fsynced and rehashed against the original vertex
  pin before `os.replace`; after replace, fsync the directory and require the
  live vertex hash to equal that original pin.

If any condition fails, restoration is forbidden and disposition is forward
only. When it succeeds, retain the candidate Arrival lineage and adoption
anchor; this is a service-routing reversal, never a history deletion.

After the first post-A write, do not restore the legacy vertex as a writable
fallback. It would conceal new authoritative facts. Stop writers, retain the
Arrival descriptor, head journal, mapped-binding root, original archive and
exact export, then recover or correct forward on the Arrival lineage. If
service must be limited during that work, use descriptor-first read-only SDK
access at the recorded head; do not drop or replay new facts into the legacy
source.

## Remaining blockers and decisions

1. Provenance implementation, review and the loops-copy pass are complete. A
   new production snapshot still requires its own independently pinned receipt.
2. The illustrative same-directory publication algorithm needs its descriptor
   reparse, receipt serialization, and disposable-directory rehearsal completed
   before use. The existing migration publisher cannot replace a distinct live
   vertex.
3. Every production writer must either have a descriptor-first SDK handoff or
   remain disabled. `run_sources` is available for source jobs, but the current
   CLI emit/sync/source workflows have no supported Arrival-v2 adapter today.
   Refusal behavior for legacy CLI commands, including `store absorb`, is
   unverified; disablement is the safety gate, not an assumed refusal.
4. The maintenance owner must complete the real writer inventory and obtain a
   quiescence record. A new source hash after snapshot requires a new candidate
   rather than a policy choice.

The selected policy decisions are already fixed: use the audited
`legacy/unattributed` preparation, fresh runtime epoch, preserved historical
boundaries with audited transformation, and no legacy writable fallback after
an Arrival write. The four items above are integration gates, not decisions to
defer to the cutover window.
