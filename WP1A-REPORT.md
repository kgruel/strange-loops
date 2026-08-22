# WP-1a Final Implementation Report
**Projected Arrival Coordinate (D0), Mirrored Mode + Write-Site Closure**

---

## 1. Executive Summary

WP-1a implements the projected arrival coordinate schema (`arrival_ordinal`, `arrival_seq`), the mirrored-mode legacy coordinate allocator, the full fixed-point dependency closure table rebuild migration mechanism, and write-site closure across all store formats (`SqliteStore`, `JsonlStore`, `ArrivalStore`, `ArrivalProjection`, `libs/store` merge/slice/rebirth).

All database schema invariants are enforced directly at the table definition level (`INTEGER NOT NULL` and `UNIQUE (arrival_ordinal, arrival_seq)` on both `facts` and `ticks`). Existing legacy databases are migrated via atomic table rebuilds that preserve `rowid` identity, FTS5 index/watermark state, triggers, indexes, and full dependency closures of views and `INSTEAD OF` triggers.

All core package suites (`atoms`, `engine`, `sdk`, `lang`, `store`, `tests/architecture`) pass 100% green. A dedicated Gate test suite (`libs/engine/tests/test_arrival_coordinate_d0.py`) exercises all target gates, and each gate has been verified through deliberate mutation testing with captured failures.

---

## 2. Deliverables & Fence Inventory

### Allowed Fence Files Modified:
1. `libs/engine/src/engine/sqlite_store.py`:
   - `_SCHEMA_STMTS`: declared `arrival_ordinal INTEGER NOT NULL`, `arrival_seq INTEGER NOT NULL`, `UNIQUE (arrival_ordinal, arrival_seq)` on `facts` and `ticks`.
   - Column constants: `FACT_CONTENT_COLUMNS`, `TICK_CONTENT_COLUMNS`, `FACT_COLUMNS = FACT_CONTENT_COLUMNS`, `TICK_COLUMNS = TICK_CONTENT_COLUMNS`, `FACT_ALL_COLUMNS`, `TICK_ALL_COLUMNS`.
   - `FACT_INSERT_SQL` and `TICK_INSERT_SQL`: expanded to include the two coordinate columns.
   - `ensure_coordinate_schema`: atomic table rebuild migration preserving `rowid`, FTS state, and fixed-point view/trigger closure; stamps `coordinate_axis` in `store_meta`; refuses mirrored migration on arrival-canonical databases.
   - `_allocate_ceremony_coordinates`: transaction-safe batch coordinate allocation for multi-row ceremonies.
   - Closed write sites: `append_attested`, `append_tick_attested`, `absorb_genesis`, `absorb_edit`.
2. `libs/engine/src/engine/jsonl_store.py`:
   - Pre-write coordinate schema check on writable index connection.
   - Coordinate allocation on write and index reconstruction.
   - Coordinate stripping before `.jsonl` payload serialization in `_ceremony_persist`.
3. `libs/engine/src/engine/arrival_store.py`:
   - Overrode `_ensure_coordinate_schema` (no-op on arrival-canonical stores).
   - Overrode `_allocate_ceremony_coordinates` to preserve arrival log coordinates during ceremonies.
   - `_index_record`: persists log coordinates directly into index rows.
4. `libs/engine/src/engine/arrival_projection.py`:
   - `rederive_projections`: persists native arrival log coordinates on rederivation.
5. `libs/store/src/store/merge.py`:
   - Upgrades destination schema via `ensure_coordinate_schema(mode="mirrored")` and writes explicit coordinates on row insertion.
6. `libs/store/src/store/slice.py`:
   - Upgrades target schema via `ensure_coordinate_schema(mode="mirrored")` and allocates coordinates on copy.
7. `libs/store/src/store/rebirth.py`:
   - Upgrades target schema via `ensure_coordinate_schema(mode="mirrored")` and allocates coordinates on rebirth.
8. `libs/engine/tests/**` & `libs/store/tests/**`:
   - Updated raw SQLite fixture inserts to provide explicit arrival coordinates.
   - Added comprehensive D0 gate suite: `libs/engine/tests/test_arrival_coordinate_d0.py`.

---

## 3. Gates Verification Table

| Gate | Description | Status | Test Reference |
|---|---|---|---|
| **G-D0-1** | Permuted-insert harness: rowid vs arrival ordinal independence | **PASSED** | `test_arrival_coordinate_d0.py::TestPermutedInsertHarness::test_permuted_insert_coordinates_and_rowids` |
| **G-D0-2** | Deliberately rebuilt index: rowid preservation & coordinate backfill | **PASSED** | `test_arrival_coordinate_d0.py::TestRebuildIndex::test_rebuild_preserves_rowids_and_reads` |
| **G-D0-4** | Interrupted migration: crash recovery & atomic rollback | **PASSED** | `test_arrival_coordinate_d0.py::TestInterruptedMigration::test_interrupted_migration_is_atomic_or_recoverable` |
| **G-D0-5** | Table-enforced invariants: NOT NULL, UNIQUE, and monotonic legacy allocation | **PASSED** | `test_arrival_coordinate_d0.py::TestTableEnforcedInvariants::*` (3 tests) |
| **G-D0-6** | Ordinary legacy opens migrate: SQLite & JSONL canonical stores | **PASSED** | `test_arrival_coordinate_d0.py::TestOrdinaryLegacyOpensMigrate::*` (2 tests) |
| **G-D0-9** | Trigger survival: AFTER INSERT trigger survives rebuild and fires | **PASSED** | `test_arrival_coordinate_d0.py::TestTriggerSurvival::test_after_insert_trigger_survives_migration_and_fires` |
| **G-D0-10** | FTS / rowid survival: FTS5 index & watermark state preserved across rebuild | **PASSED** | `test_arrival_coordinate_d0.py::TestFtsRowidSurvival::test_fts_and_watermark_survive_rebuild` |
| **G-D0-11** | Mis-mode refusal: mirrored migration refused on arrival-canonical store | **PASSED** | `test_arrival_coordinate_d0.py::TestMisModeRefusal::test_mirrored_mode_refuses_arrival_canonical_index` |
| **G-D0-13** | Dependent-view survival closure-deep: v1 over facts, v2 over v1, INSTEAD OF trigger | **PASSED** | `test_arrival_coordinate_d0.py::TestDependentViewSurvivalClosureDeep::test_v1_over_facts_v2_over_v1_and_instead_of_trigger_survive` |

---

## 4. Deliberate Mutation Log

Each gate test was verified against deliberate code mutation to confirm test sensitivity and error specificity:

### 1. Gate G-D0-1 (Permuted-Insert Allocator)
- **Target**: `libs/engine/src/engine/sqlite_store.py:1039` (`_write_fact_row`)
- **Mutation**: Mutated ordinal allocation to hardcoded `0`: `row = (*row, 0, 0)`.
- **Observed Failure**: `sqlite3.IntegrityError: UNIQUE constraint failed: facts.arrival_ordinal, facts.arrival_seq` at `libs/engine/src/engine/sqlite_store.py:1040`.
- **Restoration**: Restored `row = (*row, ord_val, 0)`. Test returned to green.

### 2. Gate G-D0-2 (Deliberately Rebuilt Index)
- **Target**: `libs/engine/src/engine/sqlite_store.py:549` (`_rebuild_table_mirrored`)
- **Mutation**: Mutated rowid copy to alter ids during rebuild: `SELECT 999 + rowid, kind, ...`.
- **Observed Failure**: `AssertionError: assert '1000' == 'fact-000'` at `libs/engine/tests/test_arrival_coordinate_d0.py:179`.
- **Restoration**: Restored `SELECT rowid, id, kind, ...`. Test returned to green.

### 3. Gate G-D0-4 (Interrupted Migration Recovery)
- **Target**: `libs/engine/src/engine/sqlite_store.py:607` (`_rebuild_table_mirrored`)
- **Mutation**: Commented out `store_meta` stamping of `coordinate_axis`.
- **Observed Failure**: `sqlite3.OperationalError: no such table: store_meta` at `libs/engine/tests/test_arrival_coordinate_d0.py:232`.
- **Restoration**: Restored `store_meta` stamping. Test returned to green.

### 4. Gate G-D0-5 (Table-Enforced Invariants)
- **Target**: `libs/engine/src/engine/sqlite_store.py:324` (`_SCHEMA_STMTS`)
- **Mutation**: Removed `NOT NULL` from `arrival_ordinal INTEGER`.
- **Observed Failure**: `Failed: DID NOT RAISE IntegrityError` on inserting `NULL` coordinate at `libs/engine/tests/test_arrival_coordinate_d0.py:262`.
- **Restoration**: Restored `arrival_ordinal INTEGER NOT NULL`. Test returned to green.

### 5. Gate G-D0-6 (Ordinary Legacy Opens Migrate)
- **Target**: `libs/engine/src/engine/sqlite_store.py:1830` (`_ensure_coordinate_schema`)
- **Mutation**: Disabled migration by making `_ensure_coordinate_schema` return early.
- **Observed Failure**: `sqlite3.OperationalError: no such column: arrival_ordinal` at `libs/engine/src/engine/sqlite_store.py:1036`.
- **Restoration**: Restored `_ensure_coordinate_schema` migration trigger. Test returned to green.

### 6. Gate G-D0-9 (Trigger Survival)
- **Target**: `libs/engine/src/engine/sqlite_store.py:603` (`_rebuild_table_mirrored`)
- **Mutation**: Commented out trigger restoration loop.
- **Observed Failure**: `AssertionError: assert None is not None` on querying trigger from `sqlite_schema` at `libs/engine/tests/test_arrival_coordinate_d0.py:442`.
- **Restoration**: Restored trigger replay loop. Test returned to green.

### 7. Gate G-D0-10 (FTS / Rowid Survival)
- **Target**: `libs/engine/src/engine/sqlite_store.py:549` (`_rebuild_table_mirrored`)
- **Mutation**: Offset rowid preservation during copy: `SELECT 100 + rowid, ...`.
- **Observed Failure**: `AssertionError: assert [] == [('fact-000',), ('fact-001',), ('fact-002',)]` due to FTS5 rowid dissociation at `libs/engine/tests/test_arrival_coordinate_d0.py:486`.
- **Restoration**: Restored verbatim `rowid` copy. Test returned to green.

### 8. Gate G-D0-11 (Mis-Mode Refusal)
- **Target**: `libs/engine/src/engine/sqlite_store.py:396` (`ensure_coordinate_schema`)
- **Mutation**: Commented out `ArrivalCanonicalUnsupported` refusal when `arrival_lineage` is present in `store_meta`.
- **Observed Failure**: `Failed: DID NOT RAISE ArrivalCanonicalUnsupported` at `libs/engine/tests/test_arrival_coordinate_d0.py:508`.
- **Restoration**: Restored refusal check. Test returned to green.

### 9. Gate G-D0-13 (Dependent-View Survival Closure-Deep)
- **Target**: `libs/engine/src/engine/sqlite_store.py:498` (`_rebuild_table_mirrored`)
- **Mutation**: Terminated view discovery loop after 1 iteration, omitting transitive dependent views.
- **Observed Failure**: `sqlite3.OperationalError: error in view v2_notes: no such table: main.v1_facts` during `ALTER TABLE facts_new RENAME TO facts` at `libs/engine/src/engine/sqlite_store.py:583`.
- **Restoration**: Restored fixed-point closure loop. Test returned to green.

---

## 5. Architecture & Invariant Validation

1. **Table Invariants**:
   - `arrival_ordinal` and `arrival_seq` are declared `INTEGER NOT NULL`.
   - `UNIQUE (arrival_ordinal, arrival_seq)` is declared on each table (`facts`, `ticks`).
   - Any raw SQL insert omitting coordinates or supplying duplicates is rejected by SQLite itself with `IntegrityError`.
2. **Schema Rebuild & Rowid Integrity**:
   - Rebuilding copies `rowid` verbatim into the new table (`INSERT INTO facts_new (rowid, ...) SELECT rowid, ...`).
   - FTS5 external-content tables (`facts_fts`) and watermark tables (`fts_state`) continue to resolve existing rowids without re-indexing.
3. **Fixed-Point Dependency Closure**:
   - View dependencies are discovered to a fixed point across all referencing views (`v1 -> v2 -> v3`).
   - Triggers attached to tables and views (including `INSTEAD OF` triggers) are discovered and dropped prior to table drop, then recreated in forward topological order after table rename.
4. **Write-Site Closure**:
   - `FACT_INSERT_SQL` and `TICK_INSERT_SQL` require all 9 and 13 columns respectively.
   - All insertion paths across `engine` and `store` allocate and provide coordinates explicitly.

---

## 6. Test Suite Execution Summary

```
Package: atoms
  517 passed in 1.48s (100% green)

Package: engine
  1822 passed, 1 skipped in 18.52s (100% green)

Package: sdk
  324 passed in 19.88s (100% green)

Package: lang
  655 passed in 3.37s (100% green)

Package: store
  157 passed in 11.95s (100% green)

Architecture: tests/architecture
  98 passed in 3.04s (100% green)
```
