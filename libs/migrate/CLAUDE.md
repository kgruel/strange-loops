# migrate — offline migration sidecar

One-way offline migration of legacy JSONL and SQLite stores into append-only Arrival logs. Start at Level 0. Only escalate when you hit a trigger.

**You are here** in the abstraction chain:

```
legacy stores (JSONL / SQLite)  →  migrate (offline sidecar)  →  arrival log (.arrival)
SourceInventory, LegacySource       run_migration, verify         ArrivalLog, HeadJournal
```

Below: `libs/engine/` provides `ArrivalLog`, arrival record formats, and head journal attestation; `libs/lang/` provides `effective_store_clause` and AST validation.
Above: `apps/loops/` provides the `loops store migrate` CLI command (importing `migrate.refusals` for typed CLI error handling).

---

## Architectural Rules

1. **Quarantine Rule**: The migration sidecar runs strictly offline outside the running loops engine/daemon. migrate imports no legacy modules and has no write path into a live store. The frozen legacy copies are `legacy_jsonl.py` (decode surface), `legacy_sqlite.py` (read spine), and `legacy_ids.py` (transform primitives) — `legacy_source.py` (validated row stream) and `inventory.py` (inventory pass) are live code; an AST quarantine ratchet (enforced in `libs/migrate/tests/test_quarantine.py`) guards against forbidden legacy imports until its ruled slice-5 dissolution when legacy modules are removed. Staging logs are lineage-named directly at `<store_dir>/<lineage>.arrival` (there is no `.staging.arrival` suffix; staging IS the lineage-named target before `.vertex` descriptor publication).
2. **Injection Rule**: The sidecar never reads private keys directly from disk or key stores, and `migrate/src` never imports `custody` or `sign` (which are declared in `dev` only for tests). Callers MUST inject an Ed25519 signer callback (`(observer, digest) -> signature | None`).
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

# Verify an existing migration report beside target (for auditors/external verification)
is_valid = verify_migration_report(
    report_path=Path("data/<lineage>.migration-report.json"),
    public_key=custodian_public_key,
    verify=ed25519_verify,
)
# returns bool (re-verifies report signature and target head claim)
```

---

## Level 1 — The 9 Pipeline Stages (§A–§I)

1. **Stage 1 (§A) Legacy Source & Inventory**: Open legacy JSONL or SQLite source via `LegacySource`, scan and compute `SourceInventory` (fact counts, tick counts, observer census, first/last timestamps). Empty sources are refused.
2. **Stage 2 (§B) Descriptor Resolution**: Mint the lineage identifier (random ULID) and derive target path (`<store_dir>/<lineage>.arrival`). Determinism belongs to the transform.
3. **Stage 3 (§C) Transform Pipeline**: Apply deterministic transforms (e.g. `ulid_migration()`). Whole-unit drops are recorded in `TransformExceptions`; partial-batch drops are refused upstream.
4. **Stage 4 (§D) Target Initialization & Preflight**: Pre-flight head journal permissions (`preflight_journal()`). Check for existing valid targets or resume staging logs safely (divergent logs are refused with no in-place repair).
5. **Stage 5 (§E) Genesis & Key Introductions**: Mint ordinal 0 genesis introducing founding public key under arrival domain (`loops-arrival-v1`), followed by key introduction records for all declared observers.
6. **Stage 6 (§F) Sequential Append**: Build outer-unsigned record drafts (`batch`, `fact`, `tick`) with deterministic SHA-256 hash chaining and append them sequentially.
7. **Stage 7 (§G) Signed Migration Report**: Compile the comprehensive migration report (`<store_dir>/<lineage>.migration-report.json` beside target) containing source fingerprints, target head, and exceptions; verify that the injected signer returned a non-None signature. (`verify_migration_report` exists separately for external auditor verification).
8. **Stage 8 (§H) Inventory Equality**: Assert exact inventory equality between source inventory and target projection across all kinds and observers (accounting for whole-unit drops; record count comparison is deliberately excluded).
9. **Stage 9 (§I) Atomic Descriptor Publish**: Verify the five code-level publish preconditions:
   - `target_verify_full`: Target log verifies `Full(through=head)`
   - `source_unchanged` (`SourceChangedRefused`): Legacy source content hash unchanged since snapshot
   - `equivalence_rerun`: Re-derived expected rows match target records logical row-by-row
   - `inventory_equality`: Target projection matches source inventory
   - `journal_first_entry_mint`: First journal entry for lineage is `bootstrap`/`MINT`
   (Note: The already-migrated guard is an apps-layer pre-flight in `loops/commands/store.py` (`_run_migrate`'s already-on-arrival pre-flight), not a `libs/migrate` precondition).
   Then surgically update `.vertex` store clause using `lang.effective_store_clause` with verification-by-re-parse.

---

## Level 2 — Design Facts (F1–F7)

For full architectural rationale and normative rulings, see `docs/architecture/arrival/protocol.html` §09, `backend-contract.html` §11, and `docs/scratch/arrival-break/slice4-design-proposal.md`:
- **F1**: Lineage-named staging (`<store_dir>/<lineage>.arrival`) and resume idempotence
- **F2**: Verification-by-re-parse for surgical `.vertex` descriptor edits
- **F3**: Arrival custody domain separation (`loops-arrival-v1`)
- **F4**: Outer-unsigned migrated records (content preserved verbatim, sealed by hash chain)
- **F5**: Signed migration report stored beside target (`<store_dir>/<lineage>.migration-report.json`)
- **F6**: 5 code-level publish preconditions (`target_verify_full`, `source_unchanged`, `equivalence_rerun`, `inventory_equality`, `journal_first_entry_mint`) and apps-layer already-migrated guard
- **F7**: Typed domain refusals for all failure modes
