# SOL-HIGH r3 Fix Report: Resolution of Finding 09 by Construction

**Branch**: `slice/D-solhigh-r3`  
**Base**: `feat/arrival-libs` (off Slice D r2 gate `155f5830` / r3 convergence brief `da1012c4`)  
**Working Directory**: `/private/tmp/claude-501/-Users-kaygee-Code-loops/46177474-a70b-40c7-b5c8-95ac89e78641/scratchpad/wt-solhigh3`  
**Date**: 2026-08-22  

---

## 1. Executive Summary & Arbiter Ruling Implementation

In three consecutive review rounds, individual branches of `ensure_coordinate_schema` stamped `coordinate_axis='arrival'` without provider agreement:
- **SOL-HIGH-01** (r1): `already_migrated` branch stamped arrival without provider check.
- **SOL-HIGH-07** (r2): `all_empty` branch stamped arrival without consulting the provider.
- **SOL-HIGH-09** (r3): `mismatch-correction` branch (`sqlite_store.py:541`) rewrote the marker to `'arrival'` without consulting the provider when tables were empty.

Per the arbiter ruling, this defect has been made **inexpressible by construction**:

1. **Extracted Single Arrival-Stamp Gatekeeper (`_stamp_arrival_axis`)**:
   - `_stamp_arrival_axis(conn, coordinates, *, validate=True)` is the **ONLY** code path in the entire engine allowed to write `coordinate_axis = 'arrival'` into `store_meta`.
   - When `validate=True`, it strictly runs provider-agreement verification (`_check_arrival_provider_agreement`):
     - Stages log coordinates from provider into `_coordinate_staging`.
     - Validates format, table names, and duplicate coordinates.
     - Performs staging join agreement checks against all database tables:
       - Empty index + empty provider = agreement (stamps `'arrival'`).
       - Empty index + any provider row = refusal with `ArrivalCanonicalUnsupported` advising `rederive_projections`.
       - Row count mismatch or missing row IDs = refusal toward `rederive_projections`.
       - Coordinate mismatch `(arrival_ordinal, arrival_seq)` = refusal toward `rederive_projections`.
   - `_stamp_coordinate_axis(conn, mode="mirrored")` is strictly restricted to mirrored mode (raising `ValueError` if passed `"arrival"`).

2. **Refactored All Arrival-Stamping Branches to Call the Gatekeeper**:
   - **Branch 1 (Mismatch correction on empty store)**: Calls `_stamp_arrival_axis(conn, coordinates, validate=validate)`.
   - **Branch 2 (All-empty / no existing tables)**: Calls `_stamp_arrival_axis(conn, coordinates, validate=validate)`.
   - **Branch 3 (Already-migrated schema validation)**: Calls `_stamp_arrival_axis(conn, coordinates, validate=validate)`.
   - **Branch 4 (Post-rebuild of legacy tables)**: Calls `_stamp_arrival_axis(conn, coordinates, validate=validate)` after rebuilding tables in dependency order. Step 10 was removed from `_rebuild_table`.

3. **Structural Ratchet Test Added (`test_structural_ratchet_single_arrival_stamp_in_store_meta`)**:
   - Asserts via regex and AST scanning that exactly **ONE** site in `libs/engine/src/engine/sqlite_store.py` writes literal `'arrival'` into `store_meta` (inside `_stamp_arrival_axis`).
   - Accompanied by a shrink-only residue locator claim.

4. **Behavioral Test Suite Added (`TestSolHigh09ArrivalStampGatekeeperByConstruction`)**:
   - `test_sol_r3_reproduction_empty_index_with_flipped_marker_refuses`: Sol's reproduction (populated log, index rows deleted, marker flipped to `'mirrored'`, resume mark retained) refuses with `ArrivalCanonicalUnsupported` advising `rederive_projections`.
   - `test_all_four_arrival_stamping_branches_refuse_on_provider_mismatch`: Proves all four branches refuse when provider disagrees with index.
   - `test_all_four_arrival_stamping_branches_succeed_when_provider_agrees`: Proves all four branches succeed when provider and index agree.
   - All r2 06, 07, 08 test fixtures continue to pass unchanged.

---

## 2. Code Changes

### `libs/engine/src/engine/sqlite_store.py`
- Extracted `_stage_arrival_coordinates` to stage provider records into temporary staging table `_coordinate_staging` and perform structural integrity validations.
- Extracted `_check_arrival_provider_agreement` to perform full counts, set-difference, and coordinate tuple join checks between staging and existing tables.
- Extracted `_stamp_arrival_axis(conn, coordinates, *, validate=True)` as the sole gatekeeper writing `coordinate_axis = 'arrival'`.
- Restricted `_stamp_coordinate_axis(conn, mode="mirrored")` to disallow `"arrival"`.
- Refactored all 4 arrival-stamping branches in `ensure_coordinate_schema` to route through `_stamp_arrival_axis`.
- Removed `is_final` and internal marker-stamping step from `_rebuild_table`, moving the post-rebuild stamp to the end of `ensure_coordinate_schema` under the gatekeeper.

### `libs/engine/tests/test_arrival_coordinate_d0.py`
- Added class `TestSolHigh09ArrivalStampGatekeeperByConstruction`:
  - `test_structural_ratchet_single_arrival_stamp_in_store_meta`
  - `test_sol_r3_reproduction_empty_index_with_flipped_marker_refuses`
  - `test_all_four_arrival_stamping_branches_refuse_on_provider_mismatch`
  - `test_all_four_arrival_stamping_branches_succeed_when_provider_agrees`

---

## 3. Mutation Proofs

### Mutation Applied: Direct Stamp Bypassing the Gatekeeper on Mismatch-Correction Branch
**Mutation code in `ensure_coordinate_schema`**:
```python
            if mode == "arrival":
                conn.execute(
                    "INSERT OR REPLACE INTO store_meta (key, value) VALUES ('coordinate_axis', 'arrival')"
                )
            else:
                _stamp_coordinate_axis(conn, mode)
            conn.commit()
            return
```

### Mutation Test Execution:
```
$ uv run pytest libs/engine/tests/test_arrival_coordinate_d0.py -k TestSolHigh09ArrivalStampGatekeeperByConstruction

============================= test session starts ==============================
collected 44 items / 40 deselected / 4 selected

libs/engine/tests/test_arrival_coordinate_d0.py FFF.                     [100%]

=================================== FAILURES ===================================
_ TestSolHigh09ArrivalStampGatekeeperByConstruction.test_structural_ratchet_single_arrival_stamp_in_store_meta _
>       assert len(arrival_meta_writes) == 1
E       AssertionError: Expected exactly 1 SQL write of 'arrival' into store_meta, found 2

_ TestSolHigh09ArrivalStampGatekeeperByConstruction.test_sol_r3_reproduction_empty_index_with_flipped_marker_refuses _
>       with pytest.raises(ArrivalCanonicalUnsupported) as exc_info:
E       Failed: DID NOT RAISE ArrivalCanonicalUnsupported

_ TestSolHigh09ArrivalStampGatekeeperByConstruction.test_all_four_arrival_stamping_branches_refuse_on_provider_mismatch _
>       with pytest.raises(ArrivalCanonicalUnsupported) as exc1:
E       Failed: DID NOT RAISE ArrivalCanonicalUnsupported

================== 3 failed, 1 passed, 40 deselected in 0.18s ==================
```
**Result**: Mutation killed. Both the structural ratchet test AND the r3 behavioral reproduction tests immediately failed when the gatekeeper was bypassed.

---

## 4. Test Suite Execution & Truthful Baselines

All package test suites pass cleanly with new tests:

| Package | Command | Baseline Target | Result | Duration |
|---|---|---|---|---|
| **atoms** | `uv run pytest libs/atoms` | 517 | **517 passed** | 8.75s |
| **engine** | `uv run pytest libs/engine/tests` | 1906 + 1 skip | **1910 passed, 1 skipped** (+4 new tests) | 54.66s |
| **sdk** | `uv run pytest libs/sdk` | 324 | **324 passed** | 13.00s |
| **lang** | `uv run pytest libs/lang` | ~655 | **655 passed** | 3.75s |
| **store** | `uv run pytest libs/store` | 176 | **176 passed** | 11.35s |
| **arch** | `uv run pytest tests/architecture` / `./dev check` | 98 | **98 passed** | 3.20s |
| **apps** | `uv run pytest apps/loops` | 2530 + 1 xfail | **2530 passed, 1 xfailed** | 10.94s |

---

## 5. Git Status & Commit History

- Initial fix commit: `bc5ee83b` (`fix(engine): fix SOL-HIGH-09 by construction — extract arrival-stamp gatekeeper`)
- Scope strictly confined to fenced files:
  - `libs/engine/src/engine/sqlite_store.py`
  - `libs/engine/tests/test_arrival_coordinate_d0.py`
- Working tree clean upon committing report.
