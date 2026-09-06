# Arrival completion stage 3M — explicit projection catch-up

Date: 2026-09-05  
Status: implementation and adversarial review complete

## Result

`engine.arrival_maintenance.sync_projection` is the sole supported public
maintenance entry. It opens the descriptor through `BackendRegistry` first,
requires the returned attested ledger comparison, captures or validates a full
target `Head`, and only then obtains the registry's private adapter maintenance
provider. `ArrivalQuery` and `QuerySnapshot` remain read-only, and the existing
backend opener tuple is unchanged.

The first file-adapter slice performs catch-up only. It takes a SQLite write
transaction, revalidates the existing projection watermark and identity under
that lock, inserts deterministic fact/tick expansions through the requested
head, and stamps the resume mark in the same transaction as those rows. A
concurrent ledger append is outside the captured bound. A concurrent
maintainer is reobserved after the projection lock. When the projection already
covers an earlier requested head, maintenance validates and reports its actual
newer prefix without moving it backward.

Physically absent or zero-schema derived state can materialize. Existing rows
without a complete mark, partial or non-Arrival marks, a watermark outside the
physical log, a foreign `own_lineage`, and conflicting rows all refuse without
rewriting their evidence. `rebuild=True` is explicit and refused; deliberate
repair/rebuild remains a separate future recovery path.

`ProjectionSyncResult` distinguishes the custody head captured on open, the
requested target, the projection observed before and after the locked work,
the derived-view generation, and whether anything changed. A
`ProjectionSyncError` retains the target, known prefix before the attempt, an
attested observed prefix after failure when one can be established, and the
original cause. File row/watermark changes roll back together; the physical
Arrival log is never modified.

The existing SDK `sync_target` name now dispatches explicit Arrival descriptors
to this coordinator and returns `loops.sdk/sync-result/v2`. Arrival results
carry `read_path="arrival"`, the store descriptor, captured/target/before/after
heads, view generation, changed status, and no invented fact count. Legacy
targets use the same result shape with Arrival fields unset and retain their
transitional reindex/preflight behavior. Descriptor aggregates still refuse
before legacy probing.

## Contract basis

- `docs/architecture/arrival/backend-contract.html` §06 requires verification
  to avoid projection mutation and separates absent materialization and named
  rebuild from verification.
- The same document §07 makes the projection watermark explicit, requires
  deterministic batch expansion, and assigns custody `head_at` the job of
  completing a projection coordinate into a verified head.
- `docs/architecture/arrival/protocol.html` §08 defines custody as truth and
  requires query answers to state their captured and projected prefixes.
- `docs/scratch/arrival-break/query-consumer-design-2026-09-05.md` ratifies a
  separate serialized maintenance protocol after head attestation, with no
  read-time materialization or repair and honest post-commit failure identity.

## Acceptance coverage

Focused tests cover missing, behind, and current projections; an earlier target
against a newer projection; prefix cutoff during a concurrent append;
interleaved maintenance; rebuild refusal; rows without a watermark; foreign
identity preservation; transactional row/watermark rollback and retry; physical
log immutability; and a real SDK sync followed by a CURRENT read from the same
attested projection.

Validation at handoff:

- Engine Arrival contract/consumer/registry/maintenance/projection/store:
  **136 passed**
- Focused maintenance file: **16 passed**
- SDK suite: **351 passed**; final real Arrival sync acceptance: **1 passed**
- Architecture suite: **101 passed**
- Ruff, changed-source `ty check`, and `git diff --check`: passed

Claude Fable 5.1 identified target-hash and concurrent-maintainer result races
plus interrupt and lock-wait handling. Those were corrected with regressions;
the supplement verdict is **APPROVE**. The review receipt is
`reviews/projection-maintenance-fable-2026-09-05.md`.
