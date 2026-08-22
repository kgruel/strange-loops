# Work Package 1b Report — Arrival-Canonical Migration Mode (D0 Completion)

**Branch**: `slice/D-wp1`  
**Repository**: `strange-loops` (`libs/engine`)  
**Design Proposal Reference**: `docs/scratch/arrival-sliceD/design-proposal.md` (§D0)

---

## 1. Executive Summary

Work Package 1b completes the D0 arrival coordinate migration engine by delivering the **arrival-canonical migration mode** (`mode="arrival"`) with coordinate staging, provider validation, composite-key join rebuilding, and full route wiring across `ArrivalStore` and `arrival_projection.py`.

### Key Deliverables Implemented:
1. **`ensure_coordinate_schema(conn, *, mode, coordinates=None)`**:
   - Accepts `mode="arrival"` with required `coordinates` provider (`Callable[[], Iterator[tuple[str, str, int, int]]]`) yielding `(table, row_id, arrival_ordinal, arrival_seq)`.
   - Populates temporary staging table `_coordinate_staging` with composite primary key `(table_name, row_id)` to prevent cross-table ID collisions.
   - Strictly enforces provider-index agreement (row counts, missing rows, extraneous rows, table name validity, coordinate uniqueness), raising `ArrivalCanonicalUnsupported` with directions to `engine.arrival_projection.rederive_projections` upon any mismatch.
2. **Coordinate-Aware Table Rebuilding**:
   - Reuses rowid-preserving temporary table staging, trigger/index/view replay from WP-1a.
   - For `mode="arrival"`, populates tables via `JOIN _coordinate_staging` matching on `(table_name, row_id)`.
   - Stamps `coordinate_axis = 'arrival'` in `store_meta`.
3. **Route Wiring**:
   - **Route 3 (`ArrivalStore.__init__`)**: Immediately after assigning `self._log`, sets `self._coordinate_mode = "arrival"` and `self._coordinate_provider` (closure walking `self._log` up to stamped resume mark ordinal), then invokes `self._ensure_coordinate_schema()`.
   - **Route 4 (`arrival_projection.rederive_projections` & `_ensure_index_schema`)**: `_ensure_index_schema` delegates to `ensure_coordinate_schema(conn, mode="arrival", coordinates=_provider)` with log-walking provider.
4. **All Gates Verified**:
   - G-D0-1 through G-D0-13 and provider-mismatch refusal verified and passing.

---

## 2. Gate Verification Summary

| Gate ID | Description | Test Case | Status |
|---|---|---|---|
| **G-D0-1** | Permuted-insert coordinate & read equivalence | `TestPermutedInsertHarness` (`test_permuted_insert_coordinates_and_rowids`, `test_permuted_vs_ordered_index_reads_equivalence`) | **PASS** |
| **G-D0-2** | Rebuild preserves rowids & read results | `TestRebuildIndex::test_rebuild_preserves_rowids_and_reads` | **PASS** |
| **G-D0-3** | Batch-bearing arrival-canonical migration (ordinal != rowid, subsequent catch-up succeeds) | `TestBatchBearingArrivalMigration::test_batch_bearing_arrival_canonical_index_migration` | **PASS** |
| **G-D0-4** | Interrupted migration is atomic & recoverable | `TestInterruptedMigration::test_interrupted_migration_is_atomic_or_recoverable` | **PASS** |
| **G-D0-5** | NOT NULL & UNIQUE table-enforced invariants | `TestTableEnforcedInvariants` (fresh, migrated, monotonic allocator) | **PASS** |
| **G-D0-6** | Ordinary legacy opens migrate (sqlite & jsonl) | `TestOrdinaryLegacyOpensMigrate` (sqlite, jsonl) | **PASS** |
| **G-D0-7** | Unmigrated batch-bearing index opens via `ArrivalStore` public constructor | `TestArrivalStorePublicOpenMigration::test_unmigrated_batch_bearing_index_opens_via_arrival_store` | **PASS** |
| **G-D0-8** | Unmigrated fixture through `rederive_projections` matches G-D0-7 | `TestRederiveProjectionsMigrationEquivalence::test_rederive_projections_matches_arrival_store_migration` | **PASS** |
| **G-D0-9** | AFTER INSERT trigger survival across rebuild | `TestTriggerSurvival::test_after_insert_trigger_survives_migration_and_fires` | **PASS** |
| **G-D0-10** | FTS & watermark state survival across rebuild | `TestFtsRowidSurvival::test_fts_and_watermark_survive_rebuild` | **PASS** |
| **G-D0-11** | Mis-mode refusal (`mode="mirrored"` on arrival index) | `TestMisModeRefusal::test_mirrored_mode_refuses_arrival_canonical_index` | **PASS** |
| **G-D0-12** | Cross-table ID collision disambiguation (fact & tick same ID) | `TestCrossTableIdCollision::test_cross_table_id_collision_assigned_distinct_coordinates` | **PASS** |
| **G-D0-13** | Deep view & INSTEAD OF trigger closure survival | `TestDependentViewSurvivalClosureDeep::test_v1_over_facts_v2_over_v1_and_instead_of_trigger_survive` | **PASS** |
| **Refusal** | Provider walk mismatch with index content | `TestProviderMismatchRefusal` (fewer rows, more rows, differing ID) | **PASS** |

---

## 3. Deliberate Mutation Testing Log

Each new test was committed, deliberately broken in production code, verified to FAIL at the exact expected assertion, restored, and verified green.

### Mutation 1: Gate G-D0-3 (`test_batch_bearing_arrival_canonical_index_migration`)
- **Target**: `libs/engine/src/engine/sqlite_store.py` (`_rebuild_table`)
- **Breakage Applied**: For arrival mode facts insertion, substituted staging join with mirrored rowid backfill (`SELECT f.rowid, ..., f.rowid, 0 FROM facts f`).
- **Failure Observed**:
  ```text
  FAILED libs/engine/tests/test_arrival_coordinate_d0.py::TestBatchBearingArrivalMigration::test_batch_bearing_arrival_canonical_index_migration
  > assert fact_rows[2] == (3, "f-002-b", 2, 1)
  E AssertionError: assert (3, 'f-002-b', 3, 0) == (3, 'f-002-b', 2, 1)
  E At index 2 diff: 3 != 2
  libs/engine/tests/test_arrival_coordinate_d0.py:761: AssertionError
  ```
- **Restoration**: `git restore libs/engine/src/engine/sqlite_store.py` -> **1 passed** in 0.19s.

### Mutation 2: Gate G-D0-7 (`test_unmigrated_batch_bearing_index_opens_via_arrival_store`)
- **Target**: `libs/engine/src/engine/arrival_store.py` (`ArrivalStore.__init__`)
- **Breakage Applied**: Commented out `self._ensure_coordinate_schema()` call during `ArrivalStore` initialization.
- **Failure Observed**:
  ```text
  FAILED libs/engine/tests/test_arrival_coordinate_d0.py::TestArrivalStorePublicOpenMigration::test_unmigrated_batch_bearing_index_opens_via_arrival_store
  > fact_rows = conn.execute("SELECT rowid, id, arrival_ordinal, arrival_seq FROM facts ORDER BY rowid").fetchall()
  E sqlite3.OperationalError: no such column: arrival_ordinal
  libs/engine/tests/test_arrival_coordinate_d0.py:893: OperationalError
  ```
- **Restoration**: `git restore libs/engine/src/engine/arrival_store.py` -> **1 passed** in 0.13s.

### Mutation 3: Gate G-D0-8 (`test_rederive_projections_matches_arrival_store_migration`)
- **Target**: `libs/engine/src/engine/arrival_projection.py` (`rederive_projections`)
- **Breakage Applied**: Mutated re-derivation coordinate sequence generation to hardcode `(*row, ord_val, 999)`.
- **Failure Observed**:
  ```text
  FAILED libs/engine/tests/test_arrival_coordinate_d0.py::TestRederiveProjectionsMigrationEquivalence::test_rederive_projections_matches_arrival_store_migration
  > conn.execute(FACT_INSERT_SQL if t == "fact" else TICK_INSERT_SQL, (*row, ord_val, 999))
  E sqlite3.IntegrityError: UNIQUE constraint failed: facts.arrival_ordinal, facts.arrival_seq
  libs/engine/src/engine/arrival_projection.py:504: IntegrityError
  ```
- **Restoration**: `git restore libs/engine/src/engine/arrival_projection.py` -> **1 passed** in 0.12s.

### Mutation 4: Gate G-D0-12 (`test_cross_table_id_collision_assigned_distinct_coordinates`)
- **Target**: `libs/engine/src/engine/sqlite_store.py` (`_rebuild_table`)
- **Breakage Applied**: Joined ticks staging table with `s.table_name = 'facts'` instead of `'ticks'`.
- **Failure Observed**:
  ```text
  FAILED libs/engine/tests/test_arrival_coordinate_d0.py::TestCrossTableIdCollision::test_cross_table_id_collision_assigned_distinct_coordinates
  > assert tick_coord == (shared_id, 2, 0)
  E AssertionError: assert ('shared-item-id-999', 1, 0) == ('shared-item-id-999', 2, 0)
  E At index 1 diff: 1 != 2
  libs/engine/tests/test_arrival_coordinate_d0.py:1163: AssertionError
  ```
- **Restoration**: `git restore libs/engine/src/engine/sqlite_store.py` -> **1 passed** in 0.14s.

### Mutation 5: Provider Mismatch Refusal (`TestProviderMismatchRefusal`)
- **Target**: `libs/engine/src/engine/sqlite_store.py` (`ensure_coordinate_schema`)
- **Breakage Applied**: Bypassed staging row count and row ID consistency validation loops.
- **Failure Observed**:
  ```text
  FAILED libs/engine/tests/test_arrival_coordinate_d0.py::TestProviderMismatchRefusal::test_provider_fewer_rows_refuses
  libs/engine/tests/test_arrival_coordinate_d0.py:1188: Failed: DID NOT RAISE ArrivalCanonicalUnsupported
  FAILED libs/engine/tests/test_arrival_coordinate_d0.py::TestProviderMismatchRefusal::test_provider_more_rows_refuses
  libs/engine/tests/test_arrival_coordinate_d0.py:1209: Failed: DID NOT RAISE ArrivalCanonicalUnsupported
  FAILED libs/engine/tests/test_arrival_coordinate_d0.py::TestProviderMismatchRefusal::test_provider_differing_id_refuses
  libs/engine/tests/test_arrival_coordinate_d0.py:1229: Failed: DID NOT RAISE ArrivalCanonicalUnsupported
  ```
- **Restoration**: `git restore libs/engine/src/engine/sqlite_store.py` -> **3 passed** in 0.12s.

### Mutation 6: Gate G-D0-1 Harness Extension (`TestPermutedInsertHarness`)
- **Target**: `libs/engine/src/engine/sqlite_store.py` (`_write_fact_row`)
- **Breakage Applied**: Hardcoded legacy coordinate allocator to assign `(0, 0)` instead of `(ord_val, 0)`.
- **Failure Observed**:
  ```text
  FAILED libs/engine/tests/test_arrival_coordinate_d0.py::TestPermutedInsertHarness::test_permuted_insert_coordinates_and_rowids
  > self._conn.execute(FACT_INSERT_SQL, row)
  E sqlite3.IntegrityError: UNIQUE constraint failed: facts.arrival_ordinal, facts.arrival_seq
  libs/engine/src/engine/sqlite_store.py:1177: IntegrityError
  ```
- **Restoration**: `git restore libs/engine/src/engine/sqlite_store.py` -> **2 passed** in 0.13s.

---

## 4. Test Suite Execution Results

All test suites across all packages in the repository pass cleanly:

```text
============================= test session starts ==============================
libs/engine: 1830 passed, 1 skipped in 52.96s
apps/loops:  2525 passed, 1 xfailed in 10.21s
libs/lang:   655 passed in 3.47s
libs/atoms:  517 passed in 7.74s
libs/sdk:    324 passed in 15.44s
libs/store:  157 passed in 11.15s
architecture: 98 passed in 2.90s
================================================================================
TOTAL: 6106 passed, 1 skipped, 1 xfailed (100% GREEN)
```

---

## 5. Git Commit History

```text
ac7ac6a0 feat(engine): WP-1b arrival-canonical migration mode (D0 completion)
6b2297d8 test(engine): G-D0-13 dependent-view survival closure-deep
e81de220 feat(engine): WP-1a projected arrival coordinate & mirrored migration
```
