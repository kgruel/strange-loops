# SOL-HIGH r2 Fix Report: Resolution of Findings 06, 07, 08

**Branch**: `slice/D-solhigh-r2`  
**Base**: `feat/arrival-libs` (off Slice D r1 remediation `7c248673`)  
**Working Directory**: `/private/tmp/claude-501/-Users-kaygee-Code-loops/46177474-a70b-40c7-b5c8-95ac89e78641/scratchpad/wt-solhigh2`  
**Date**: 2026-08-22  

---

## 1. Executive Summary & Arbiter Rulings Implementation

All three sol-HIGH r2 findings (06, 07, 08) regarding marker and stamp logic in the coordinate schema migration and ArrivalStore construction have been fixed strictly according to the arbiter rulings:

1. **SOL-HIGH-06 (MAJOR)** ([`sqlite_store.py`](libs/engine/src/engine/sqlite_store.py), [`arrival_store.py`](libs/engine/src/engine/arrival_store.py)):
   - **Ruling**:
     (a) Fast path compares `store_meta.coordinate_axis` marker value against requested `mode` — a mismatch never silently passes. If all existing tables have zero rows (fresh-store case), the marker is corrected to the requested mode; if any rows are present, it refuses with `ArrivalCanonicalUnsupported` with a location claim naming both modes.
     (b) A freshly constructed `ArrivalStore` has `coordinate_axis = 'arrival'`; a fresh `SqliteStore` has `coordinate_axis = 'mirrored'`.
   - **Resolution**:
     - Updated `ensure_coordinate_schema`'s fast path: when `axis_row` is present, it compares `axis_row[0] == mode`. If matched, structurally verifies existing tables and returns immediately. If mismatched, checks whether all tables are empty: if empty, verifies structure, corrects marker via `_stamp_coordinate_axis(conn, mode)`, and commits; if non-empty, raises `ArrivalCanonicalUnsupported(f"coordinate_axis marker {axis_row[0]!r} disagrees with requested mode {mode!r} on non-empty store")`.
     - In `ArrivalStore.__init__`, `self._ensure_meta_table()` and `self._ensure_coordinate_schema()` run in `mode='arrival'`. A fresh `ArrivalStore` now ends up stamped `coordinate_axis = 'arrival'`, and a fresh `SqliteStore` ends up stamped `'mirrored'`.

2. **SOL-HIGH-07 (MAJOR)** ([`sqlite_store.py`](libs/engine/src/engine/sqlite_store.py)):
   - **Ruling**: In `mode="arrival"`, an empty index must never unconditionally stamp without consulting the provider. It must consult `coordinates()`: if the provider yields zero rows, it stamps; if the provider yields any rows, disagreement refuses toward `rederive_projections`.
   - **Resolution**: Removed the unconditional `all_empty` early stamp bypasses from `ensure_coordinate_schema`. In `mode="arrival"` with `validate=True`, empty tables now proceed to stage coordinates from the provider. If the arrival log has rows while the index is empty (sol's reproduction), the staging count mismatch check triggers and raises `ArrivalCanonicalUnsupported` with a recommendation to run `rederive_projections`. If the log is also empty (0 rows), staging has 0 rows, mismatch check passes (0 == 0), and migration stamps `'arrival'`.

3. **SOL-HIGH-08 (MAJOR)** ([`sqlite_store.py`](libs/engine/src/engine/sqlite_store.py)):
   - **Ruling**: Fix keyword-only call to `_rebuild_table` and add a test fixture opening an empty legacy arrival index through the public `ArrivalStore` constructor to ensure it migrates, stamps, and supports appends.
   - **Resolution**: Eliminated the buggy positional call `_rebuild_table(conn, t, "arrival", validate=False)` (which was part of the removed `all_empty` bypass). Empty legacy tables now flow through the standard dependency-closed rebuild loop which calls `_rebuild_table(conn, table, is_final=is_final, mode=mode, validate=validate)` with all required keyword arguments. Added `test_empty_legacy_arrival_index_migrates_stamps_and_appends` covering public constructor opening, table rebuild, marker stamping, and subsequent append.

---

## 2. Code Changes

### `libs/engine/src/engine/sqlite_store.py`
- Updated `ensure_coordinate_schema`:
  - Compared `axis_row[0] == mode` in marker check.
  - Allowed stamp correction on empty store (`all_empty`); raised `ArrivalCanonicalUnsupported` naming both modes on non-empty store.
  - Removed unconditional `all_empty` short-circuits so `mode="arrival"` validation always stages and verifies provider coordinates.
  - Made `_meta_get` handle `sqlite3.OperationalError` gracefully if `store_meta` table does not exist.
  - Added imports for `ArrivalCorrupt, GenesisRefused`.

### `libs/engine/src/engine/arrival_store.py`
- In `ArrivalStore.__init__`, ensured `self._ensure_meta_table()` is called before `self._ensure_coordinate_schema()`.

### `libs/engine/tests/test_arrival_coordinate_d0.py`
- Added 3 new test classes:
  - `TestSolHigh06CoordinateAxisModeMismatch`:
    - `test_fresh_arrival_store_stamped_arrival`: verifies fresh `ArrivalStore` marker is `'arrival'`.
    - `test_fresh_sqlite_store_stamped_mirrored`: verifies fresh `SqliteStore` marker is `'mirrored'`.
    - `test_hand_stamped_mismatch_non_empty_store_refuses_loudly`: verifies hand-stamped mismatches on non-empty stores refuse with both modes named.
    - `test_empty_store_mode_mismatch_corrected`: verifies empty store marker correction.
  - `TestSolHigh07EmptyIndexConsultsProvider`:
    - `test_empty_index_with_populated_log_refuses_rederive`: sol's reproduction (projected rows deleted, marker deleted, resume mark retained) refuses toward `rederive_projections`.
  - `TestSolHigh08EmptyLegacyIndexPublicConstructor`:
    - `test_empty_legacy_arrival_index_migrates_stamps_and_appends`: empty legacy database with minted log opens cleanly via `ArrivalStore(...)`, migrates schema, stamps `'arrival'`, and successfully appends new facts.

---

## 3. Mutation Proofs

### Mutation Proof 06: Fast path reverted to truthy-check without mode comparison
**Mutation applied**:
```python
        if axis_row is not None and axis_row[0]:
            from .arrival_store import ArrivalCanonicalUnsupported
            for t in existing_tables:
                valid, defect = _verify_coordinate_schema(conn, t)
                if not valid:
                    raise ArrivalCanonicalUnsupported(...)
            return  # Fast path: marker present and structure complete (no mode check)
```

**Test execution**:
```
$ uv run --package engine pytest libs/engine/tests/test_arrival_coordinate_d0.py -k TestSolHigh06CoordinateAxisModeMismatch

============================= test session starts ==============================
collected 40 items / 36 deselected / 4 selected

libs/engine/tests/test_arrival_coordinate_d0.py F.FF                     [100%]

=================================== FAILURES ===================================
_ TestSolHigh06CoordinateAxisModeMismatch.test_fresh_arrival_store_stamped_arrival _
>       assert meta == ("arrival",)
E       AssertionError: assert ('mirrored',) == ('arrival',)
E         At index 0 diff: 'mirrored' != 'arrival'

_ TestSolHigh06CoordinateAxisModeMismatch.test_hand_stamped_mismatch_non_empty_store_refuses_loudly _
>       with pytest.raises(ArrivalCanonicalUnsupported) as exc_info:
E       Failed: DID NOT RAISE ArrivalCanonicalUnsupported

_ TestSolHigh06CoordinateAxisModeMismatch.test_empty_store_mode_mismatch_corrected _
>       assert meta == ("arrival",)
E       AssertionError: assert ('mirrored',) == ('arrival',)
E         At index 0 diff: 'mirrored' != 'arrival'

================== 3 failed, 1 passed, 36 deselected in 0.15s ==================
```
**Result**: Mutation killed. Mismatch tests fail when mode comparison is omitted.

---

### Mutation Proof 07: Unconditional `all_empty` stamp restored
**Mutation applied**:
```python
    all_empty = all(
        conn.execute(f"SELECT COUNT(*) FROM {_quote_ident(t)}").fetchone()[0] == 0
        for t in existing_tables
    )
    if all_empty:
        _stamp_coordinate_axis(conn, mode)
        conn.commit()
        return
```

**Test execution**:
```
$ uv run --package engine pytest libs/engine/tests/test_arrival_coordinate_d0.py -k TestSolHigh07EmptyIndexConsultsProvider

============================= test session starts ==============================
collected 40 items / 39 deselected / 1 selected

libs/engine/tests/test_arrival_coordinate_d0.py F                        [100%]

=================================== FAILURES ===================================
_ TestSolHigh07EmptyIndexConsultsProvider.test_empty_index_with_populated_log_refuses_rederive _
>       with pytest.raises(ArrivalCanonicalUnsupported) as exc_info:
E       Failed: DID NOT RAISE ArrivalCanonicalUnsupported

======================= 1 failed, 39 deselected in 0.69s =======================
```
**Result**: Mutation killed. Reproduction test fails when empty index unconditionally stamps without provider validation.

---

## 4. Test Suite Execution & Baselines

All package test suites pass cleanly:

| Package | Baseline Target | Result | Duration |
|---|---|---|---|
| **atoms** | 517 | **517 passed** | 8.32s |
| **engine** | 1900 + 1 skip | **1906 passed, 1 skipped** (+6 new tests) | 52.16s |
| **sdk** | 324 | **324 passed** | 16.09s |
| **lang** | ~655 | **655 passed** | 3.20s |
| **store** | 176 | **176 passed** | 11.04s |
| **arch** | 98 | **98 passed** | 2.99s |
| **apps** | 2530 + 1 xfail | **2530 passed, 1 xfailed** | 9.75s |

### Verification Outputs

#### `uv run --package atoms pytest libs/atoms`
```
============================= 517 passed in 8.32s ==============================
```

#### `uv run --package engine pytest libs/engine`
```
======================= 1906 passed, 1 skipped in 52.16s =======================
```

#### `uv run --package sdk pytest libs/sdk`
```
============================= 324 passed in 16.09s =============================
```

#### `uv run --package lang pytest libs/lang`
```
============================= 655 passed in 3.20s ==============================
```

#### `uv run --package store pytest libs/store`
```
============================= 176 passed in 11.04s =============================
```

#### `uv run --package loops pytest tests/architecture`
```
============================== 98 passed in 2.99s ==============================
```

#### `uv run --package loops pytest apps/loops`
```
======================= 2530 passed, 1 xfailed in 9.75s ========================
```

---

## 5. Git Status & Commit History

- Remediation commit: `a925c697` (`fix(engine): sol-HIGH r2 findings 06/07/08 — coordinate axis marker and stamp remediation`)
- Scope confined strictly to fenced files:
  - `libs/engine/src/engine/sqlite_store.py`
  - `libs/engine/src/engine/arrival_store.py`
  - `libs/engine/tests/test_arrival_coordinate_d0.py`
- Working tree clean upon committing report.
