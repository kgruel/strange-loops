# migrate — offline migration sidecar

One-way offline migration of legacy JSONL and SQLite stores into append-only Arrival logs. Start at Level 0. Only escalate when you hit a trigger.

**You are here** in the abstraction chain:

```
legacy stores (JSONL / SQLite)  →  migrate (offline sidecar)  →  arrival log (.arrival)
SourceInventory, LegacySource       run_migration, verify         ArrivalLog, HeadJournal
```

Below: `libs/engine/` provides `ArrivalLog`, arrival record formats, and head journal attestation; `libs/lang/` provides `effective_store_clause` and AST validation.
Above: `apps/loops/` provides the `loops store migrate` CLI command.

---

## Architectural Rules

1. **Quarantine Rule**: The migration sidecar runs strictly offline outside the running loops engine/daemon. It has zero write paths into active stores or running engines. It writes to a lineage-named staging log (`<lineage>.staging.arrival`), verifying all invariants before atomic publish.
2. **Injection Rule**: The sidecar never reads private keys directly from disk or key stores. Callers MUST inject an Ed25519 signer callback (`(observer, digest) -> signature | None`).
3. **Verification-by-Re-run**: Verification is an active operation, not a trust claim. The sidecar re-derives projections, re-computes inventories, and validates signed artifacts end-to-end.

---

## Level 0 — Running and Verifying Migrations

**Trigger**: I need to migrate a legacy store or verify an existing migration report.

```python
from migrate import run_migration, verify_migration_report, ulid_migration

# Run a migration with injected signer
outcome = run_migration(
    source_path=Path("data/legacy.jsonl"),
    vertex_path=Path("project.vertex"),
    store_dir=Path("data"),
    signer=custodian_signer,
    transform_rule=ulid_migration(),
)
# MigrationOutcome(target_path=..., lineage=..., head=...)

# Verify an existing migration report beside target
verification = verify_migration_report(
    report_path=Path("data/project.arrival.migration-report.json"),
    verifier=custodian_verifier,
)
# MigrationReportVerification(ok=True, lineage=..., records=...)
```

---

## Level 1 — The 9 Pipeline Stages (§A–§I)

1. **Stage 1 (§A) Legacy Source & Inventory**: Open legacy JSONL or SQLite source via `LegacySource`, scan and compute `SourceInventory` (fact counts, tick counts, observer census, first/last timestamps). Empty sources are refused.
2. **Stage 2 (§B) Descriptor Resolution**: Derive the deterministic lineage identifier and target path (`<store_dir>/<lineage>.arrival`).
3. **Stage 3 (§C) Transform Pipeline**: Apply deterministic transforms (e.g. `ulid_migration()`). Whole-unit drops are recorded in `TransformExceptions`; partial-batch drops are refused upstream.
4. **Stage 4 (§D) Target Initialization & Preflight**: Pre-flight head journal permissions (`preflight_journal()`). Check for existing valid targets or resume staging logs safely (divergent logs are refused with no in-place repair).
5. **Stage 5 (§E) Genesis & Key Introductions**: Mint ordinal 0 genesis introducing founding public key under arrival domain (`loops-arrival-v1`), followed by key introduction records for all declared observers.
6. **Stage 6 (§F) Sequential Append**: Build outer-unsigned record drafts (`batch`, `fact`, `tick`) with deterministic SHA-256 hash chaining and append them sequentially.
7. **Stage 7 (§G) Signed Migration Report**: Compile the comprehensive migration report (`.migration-report.json` beside target) containing source fingerprints, target head, exceptions, and custodian Ed25519 signature.
8. **Stage 8 (§H) Inventory Equality**: Assert exact inventory equality between source inventory and target projection across all kinds and observers (accounting for whole-unit drops; record count comparison is deliberately excluded).
9. **Stage 9 (§I) Atomic Descriptor Publish**: Verify the 5 publish preconditions (source unchanged, target openable, head match, inventory equal, report verified) + already-migrated guard, then surgically update `.vertex` store clause using `lang.effective_store_clause` with verification-by-re-parse.

---

## Level 2 — Design Facts (F1–F7)

For full architectural rationale and normative rulings, see `docs/architecture/arrival/protocol.html` §09, `backend-contract.html` §11, and `docs/scratch/arrival-break/slice4-design-proposal.md`:
- **F1**: Lineage-named staging and resume idempotence
- **F2**: Verification-by-re-parse for surgical `.vertex` descriptor edits
- **F3**: Arrival custody domain separation (`loops-arrival-v1`)
- **F4**: Outer-unsigned migrated records (content preserved verbatim, sealed by hash chain)
- **F5**: Signed migration report stored beside target (`<target>.migration-report.json`)
- **F6**: 5 publish preconditions and already-migrated guard
- **F7**: Typed domain refusals for all failure modes
