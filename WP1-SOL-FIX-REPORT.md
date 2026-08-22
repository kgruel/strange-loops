# SOL-WP1-01 Fix Report: Structural Coordinate Schema Verification & Refusal on Marked Incomplete Stores

## 1. Defect Analysis (SOL-WP1-01)
Prior to this fix, `ensure_coordinate_schema` in `libs/engine/src/engine/sqlite_store.py` had two critical vulnerabilities:
1. **Uninspected Marker Early Return**: When `store_meta.coordinate_axis` was present, the function returned immediately without verifying that the underlying `facts` and `ticks` tables conformed to the required arrival coordinate schema. An out-of-band stamped or incomplete database was accepted unconditionally.
2. **Weak Column-Existence Heuristic**: In the absence of a marker (or during per-table rebuild iteration), a table was treated as migrated if `arrival_ordinal` merely existed in `PRAGMA table_info`. It never verified:
   - Presence of `arrival_seq` column
   - `NOT NULL` constraints on `arrival_ordinal` and `arrival_seq`
   - Table-level or index-level `UNIQUE (arrival_ordinal, arrival_seq)` constraint

As a consequence, foreign or partially-migrated schemas could be stamped as valid and accepted into operation without the required invariants.

---

## 2. Ratified Fix Implementation

### Structural Verifier (`_verify_coordinate_schema`)
Implemented `_verify_coordinate_schema(conn, table)` in `libs/engine/src/engine/sqlite_store.py`:
- Inspects `PRAGMA table_info({table})` to verify:
  - `arrival_ordinal` is present with `notnull=1`
  - `arrival_seq` is present with `notnull=1`
- Inspects `PRAGMA index_list({table})` and `PRAGMA index_info({index})` (with fallback to `sqlite_schema` table DDL) to verify active enforcement of the `UNIQUE (arrival_ordinal, arrival_seq)` constraint (covering both table-level auto-indexes with origin `'u'` and explicit unique indexes).
- Returns `(True, None)` on compliance, or `(False, defect_description)` specifying the exact missing column or constraint.

### Marker Present Path
- Structural verification is executed on all existing tables (`facts`, `ticks`).
- **Pass**: Returns immediately (fast path, two PRAGMAs).
- **Fail**: Raises `ArrivalCanonicalUnsupported` with a location claim:
  `"{defect} — coordinate_axis marker disagrees with table structure (out-of-band interference)"`
- Leaves the store strictly unmodified without attempting automatic rebuild.

### Marker Absent Path
- The old column-exists shortcut (`"arrival_ordinal" in cols`) is completely replaced by `_verify_coordinate_schema`.
- Tables passing verification are skipped; non-conforming or legacy tables are rebuilt in dependency-closed order via `_rebuild_table`.
- Covers crash-between-tables idempotently.

### Ordering & Docstrings
- Mis-mode `ARRIVAL_LINEAGE_KEY` refusal remains first, preserving Gate F-6 ordering.
- `ensure_coordinate_schema` docstring updated to explicitly document the structural verification rules, fast path, and out-of-band interference refusal posture.

---

## 3. Required Tests (`test_arrival_coordinate_d0.py`)

Added `TestSolWp101StructuralVerification` covering:
1. `test_foreign_partial_schema_no_marker_rebuilt_correctly`:
   - Foreign database with nullable `arrival_ordinal` and no `arrival_seq`/`UNIQUE` constraints.
   - Opened via `SqliteStore` public constructor and appended to.
   - Verified that table is rebuilt with `arrival_ordinal NOT NULL`, `arrival_seq NOT NULL`, and `UNIQUE (arrival_ordinal, arrival_seq)`, existing rowids/coordinates preserved, and subsequent constraint violations are rejected.
2. `test_marker_present_structure_incomplete_refuses_loudly`:
   - Legacy store with `coordinate_axis = 'mirrored'` stamped by hand.
   - Verified that direct `ensure_coordinate_schema` and `SqliteStore.append` raise `ArrivalCanonicalUnsupported` naming `facts lacks arrival_ordinal column` and citing `out-of-band interference`.
   - Verified store remains unmodified.
3. `test_marker_present_structure_complete_fast_path`:
   - Fully migrated store with stamped marker.
   - Reopened with `_rebuild_table` monkeypatched to fail if called.
   - Verified fast path executes without rebuild and appends succeed cleanly.

---

## 4. Break / Restore Proof

### Mutation Target
`libs/engine/src/engine/sqlite_store.py` (`ensure_coordinate_schema` marker-present branch)

### Mutation Applied
Weakened marker-present check back to the legacy uninspected early return:
```python
    if meta_table_exists:
        axis_row = conn.execute(
            "SELECT value FROM store_meta WHERE key = 'coordinate_axis'"
        ).fetchone()
        if axis_row is not None and axis_row[0]:
            return  # Weakened old behavior
```

### Break Proof Output
```
FAILED libs/engine/tests/test_arrival_coordinate_d0.py::TestSolWp101StructuralVerification::test_marker_present_structure_incomplete_refuses_loudly
E       Failed: DID NOT RAISE ArrivalCanonicalUnsupported
======================= 1 failed, 25 deselected in 0.12s =======================
```

### Restoration
Restored structural verification loop.

### Restored Output
```
libs/engine/tests/test_arrival_coordinate_d0.py .                        [100%]
======================= 1 passed, 25 deselected in 0.08s =======================
```

---

## 5. Test Suites Verification

All test suites truthfully reported:

| Suite | Status | Details |
|---|---|---|
| **engine** | PASSED | 1836 passed, 1 skipped (1837 collected) |
| **store** | PASSED | 157 passed |
| **apps/loops** | PASSED | 2525 passed, 1 xfailed (2526 collected) |
| **atoms** | PASSED | 517 passed |
| **sdk** | PASSED | 324 passed |
| **arch** | PASSED | 98 passed (`tests/architecture`) |

---

## 6. Fence & Git Status

- **Fenced Files**:
  - `libs/engine/src/engine/sqlite_store.py`
  - `libs/engine/tests/test_arrival_coordinate_d0.py`
  - `WP1-SOL-FIX-REPORT.md` (report)
- **Branch**: `slice/D-wp1`
- **Git Status**: Clean, changes committed.
