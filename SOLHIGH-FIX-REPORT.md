# SOL-HIGH Fix Report: Resolution of Five Total-Completion Findings

**Branch**: `slice/D-solhigh-r1`  
**Base**: `feat/arrival-libs` (full Slice D merged)  
**Working Directory**: `/private/tmp/claude-501/-Users-kaygee-Code-loops/46177474-a70b-40c7-b5c8-95ac89e78641/scratchpad/wt-solhigh`  
**Date**: 2026-08-22  

---

## 1. Executive Summary & Arbiter Rulings Implementation

All five sol-HIGH total-completion findings have been resolved in strict accordance with the arbiter rulings:

1. **SOL-HIGH-01** ([`sqlite_store.py`](libs/engine/src/engine/sqlite_store.py)): In `mode="arrival"`, a structurally-complete but unmarked index does not earn the `coordinate_axis` stamp on structure alone. Its coordinates are validated against the provider via temporary staging join checks. Any coordinate mismatch or unresolvable log state refuses toward `rederive_projections`.
2. **SOL-HIGH-02** ([`sqlite_store.py`](libs/engine/src/engine/sqlite_store.py)): Replaced every raw string interpolation of table, view, index, and trigger identifiers in `_verify_coordinate_schema`, staging validation, and `_rebuild_table` with `_quote_ident(ident)` using SQLite standard double-quote escaping (`""`).
3. **SOL-HIGH-03** ([`store_reader.py`](libs/engine/src/engine/store_reader.py)): `query_facts` `LIMIT` is treated as a floor. After fetching `limit` rows, if the last row belongs to a multi-row arrival record (`arrival_ordinal`), the page is extended with all remaining rows of that `arrival_ordinal` (`arrival_seq > last_seq` for oldest, `arrival_seq < last_seq` for newest). Truncation probes for records strictly beyond `last_ord`.
4. **SOL-HIGH-04** ([`canonical_audit.py`](libs/engine/src/engine/canonical_audit.py)): `_check_counts_arrival` validates the arrival coordinate as the pair `(arrival_ordinal, arrival_seq)`. Rows with `arrival_ordinal IS NULL` or `arrival_seq IS NULL` fail the counts check and name the specific table and column.
5. **SOL-HIGH-05** ([`canonical_audit.py`](libs/engine/src/engine/canonical_audit.py), [`test_audit_rebase_d3.py`](libs/engine/tests/test_audit_rebase_d3.py)): Scope-the-claim applied: docstrings and comments updated to specify the exact bound of `1 + N` records verified (1 anchor record during L1 base audit + N records during full log walk). G-D3-2 deep audit test asserts `counts["anchor"] == 1`, `counts["walk"] == expected_n`, and `total_verified == 1 + expected_n`. Receipted deviation from r6 gate text.

---

## 2. Detailed Implementation Notes

### SOL-HIGH-01: Provider Validation for Unmarked Structurally-Complete Arrival Indices
- **Files Modified**: `libs/engine/src/engine/sqlite_store.py`
- **Logic**:
  - In `migrate_coordinate_schema`, if `already_migrated` is True, it stamps and exits early only when `mode == "mirrored"` or `not validate` or `all_empty`.
  - When `mode == "arrival"` and `validate=True` with non-empty tables, it stages the provider's coordinates in `_coordinate_staging` and validates:
    1. Staging count matches index count for all existing tables.
    2. Zero missing IDs in staging (`SELECT id FROM table EXCEPT SELECT row_id FROM staging`).
    3. Coordinate values match existing columns (`JOIN _coordinate_staging s ON s.table_name = ? AND s.row_id = t.id WHERE t.arrival_ordinal != s.arrival_ordinal OR t.arrival_seq != s.arrival_seq`).
  - If coordinates disagree, raises `ArrivalCanonicalUnsupported` with explicit recommendation to run `engine.arrival_projection.rederive_projections`.
  - If coordinates match, stamps `coordinate_axis = 'arrival'` without rebuilding tables (zero rebuild).

### SOL-HIGH-02: SQLite Identifier Quoting in Index Migration & Rebuild
- **Files Modified**: `libs/engine/src/engine/sqlite_store.py`
- **Logic**:
  - Added helper `_quote_ident(ident: str) -> str`:
    ```python
    def _quote_ident(ident: str) -> str:
        """Quote a SQLite identifier using double quotes, escaping embedded quotes."""
        return '"' + ident.replace('"', '""') + '"'
    ```
  - Quoted all dynamically interpolated identifiers at 15 distinct dynamic SQL sites across `_verify_coordinate_schema`, staging validation, and `_rebuild_table` (`DROP TRIGGER`, `DROP VIEW`, `DROP INDEX`, `CREATE TABLE`, `DROP TABLE`, `ALTER TABLE ... RENAME TO`, and `PRAGMA table_info/index_list/index_info`).

### SOL-HIGH-03: Atomic Multi-Row Record Page Extension in `query_facts`
- **Files Modified**: `libs/engine/src/engine/store_reader.py`
- **Logic**:
  - Updated `StoreReader.query_facts`:
    - After executing query with `LIMIT ?` (`limit`), if `len(rows) == limit`, reads `last_ord = rows[-1][6]` and `last_seq = rows[-1][7]`.
    - Extends `rows` with any remaining rows for that record:
      - For `order == "oldest"`: `WHERE ... arrival_ordinal = ? AND arrival_seq > ? ORDER BY arrival_seq ASC` with `(last_ord, last_seq)`.
      - For `order == "newest"`: `WHERE ... arrival_ordinal = ? AND arrival_seq < ? ORDER BY arrival_seq DESC` with `(last_ord, last_seq)`.
    - Probes `truncated` by querying if any rows exist strictly beyond `last_ord`:
      - For `order == "oldest"`: `SELECT 1 FROM facts WHERE ... arrival_ordinal > ? LIMIT 1` with `(last_ord,)`.
      - For `order == "newest"`: `SELECT 1 FROM facts WHERE ... arrival_ordinal < ? LIMIT 1` with `(last_ord,)`.
    - Preserves cursor contract: `next` position is resolved from the last item of the extended page.
- **Enumeration of Limit-Paginated Arrival Queries in `store_reader.py`**:
  - A systematic audit of all methods in `StoreReader` was conducted:
    1. `query_facts(limit=...)`: Limit-paginated cursor query returning `FactPage` (`WitnessPosition` cursor). **Updated with atomic page extension.**
    2. `facts_between(start_ts, end_ts, ...)`: Interval scan by timestamp; no `limit` or cursor pagination.
    3. `facts_since_id(fact_id, ...)`: Full suffix scan by rowid / arrival position; no `limit` pagination.
    4. `query_ticks(...)` / `ticks_between(...)`: No limit-paginated arrival cursor pagination.
    5. `vertex_reader.vertex_query_facts(...)`: Delegates directly to `StoreReader.query_facts`.
  - Conclusion: `query_facts` is the only limit-paginated arrival-cursor query in `store_reader.py`.

### SOL-HIGH-04: Full Coordinate Pair Validation in `_check_counts_arrival`
- **Files Modified**: `libs/engine/src/engine/canonical_audit.py`
- **Logic**:
  - In `_check_counts_arrival`:
    ```python
    null_ord_facts = conn.execute("SELECT COUNT(*) FROM facts WHERE arrival_ordinal IS NULL").fetchone()[0]
    null_ord_ticks = conn.execute("SELECT COUNT(*) FROM ticks WHERE arrival_ordinal IS NULL").fetchone()[0]
    if null_ord_facts > 0 or null_ord_ticks > 0:
        tbl = "facts" if null_ord_facts > 0 else "ticks"
        return Check(
            "counts",
            False,
            f"this index holds a row carrying no arrival coordinate ({tbl} has NULL arrival_ordinal)",
        )

    null_seq_facts = conn.execute("SELECT COUNT(*) FROM facts WHERE arrival_seq IS NULL").fetchone()[0]
    null_seq_ticks = conn.execute("SELECT COUNT(*) FROM ticks WHERE arrival_seq IS NULL").fetchone()[0]
    if null_seq_facts > 0 or null_seq_ticks > 0:
        tbl = "facts" if null_seq_facts > 0 else "ticks"
        return Check(
            "counts",
            False,
            f"this index holds a row carrying no arrival coordinate ({tbl} has NULL arrival_seq)",
        )
    ```

### SOL-HIGH-05: Scope-the-Claim 1+N Bound for Deep Audit
- **Files Modified**: `libs/engine/src/engine/canonical_audit.py`, `libs/engine/tests/test_audit_rebase_d3.py`
- **Logic**:
  - Updated module docstrings and function docstrings in `canonical_audit.py` to specify the exact bound of `1 + N` records verified (1 anchor record during L1 agreement check + N records during full log walk).
  - Updated test docstrings in `TestGateD3_2_BoundedWorkInstrumentation` in `test_audit_rebase_d3.py`.
  - Updated `test_deep_audit_verifies_full_n_records` to assert:
    ```python
    assert report.ok
    assert counts["anchor"] == 1
    assert counts["walk"] == expected_n
    total_verified = counts["anchor"] + counts["walk"]
    assert total_verified == 1 + expected_n
    ```
  - **Receipted Deviation**: This is a receipted deviation from the original r6 gate text which stated N records; the claim now accurately states `1 + N` records.

---

## 3. Mutation Proofs

### Mutation 01: Re-allow Structure-Only Stamping for Unmarked Arrival Index
- **Mutation Applied**: Removed provider validation branch for unmarked structurally-complete index in `sqlite_store.py` (stamping `coordinate_axis` based on column structure alone).
- **Target Test**: `libs/engine/tests/test_arrival_coordinate_d0.py::TestSolHigh01UnmarkedStructurallyCompleteValidation`
- **Execution Command**:
  ```bash
  uv run --package loops pytest libs/engine/tests/test_arrival_coordinate_d0.py::TestSolHigh01UnmarkedStructurallyCompleteValidation -q
  ```
- **Output**:
  ```
  F.                                                                       [100%]
  =================================== FAILURES ===================================
  _ TestSolHigh01UnmarkedStructurallyCompleteValidation.test_unmarked_structurally_complete_shifted_coordinates_refuses_rederive _
  ...
  >       with pytest.raises(ArrivalCanonicalUnsupported) as exc_info:
  E       Failed: DID NOT RAISE ArrivalCanonicalUnsupported

  libs/engine/tests/test_arrival_coordinate_d0.py:1935: Failed
  =========================== short test summary info ============================
  FAILED libs/engine/tests/test_arrival_coordinate_d0.py::TestSolHigh01UnmarkedStructurallyCompleteValidation::test_unmarked_structurally_complete_shifted_coordinates_refuses_rederive
  1 failed, 1 passed in 0.13s
  ```
- **Result**: Mutation successfully caught.

---

### Mutation 03: Remove Page Extension in `query_facts`
- **Mutation Applied**: Reverted `query_facts` in `store_reader.py` to simple row slicing (`rows[:limit]`) without checking or extending remaining rows of the same `arrival_ordinal`.
- **Target Test**: `libs/engine/tests/test_query_facts.py::TestSolHigh03AtomicRecordPageExtension`
- **Execution Command**:
  ```bash
  uv run --package loops pytest libs/engine/tests/test_query_facts.py::TestSolHigh03AtomicRecordPageExtension -q
  ```
- **Output**:
  ```
  FF                                                                       [100%]
  =================================== FAILURES ===================================
  _ TestSolHigh03AtomicRecordPageExtension.test_two_facts_in_batch_seen_across_pages _
  ...
  >           assert [f["id"] for f in p2.items] == ["f-002a", "f-002b"]
  E           AssertionError: assert ['f-002a'] == ['f-002a', 'f-002b']
  E             Right contains one more item: 'f-002b'

  libs/engine/tests/test_query_facts.py:422: AssertionError
  _ TestSolHigh03AtomicRecordPageExtension.test_limit_1_over_3_row_batch_returns_all_3 _
  ...
  >           assert [f["id"] for f in page.items] == ["b1", "b2", "b3"]
  E           AssertionError: assert ['b1'] == ['b1', 'b2', 'b3']
  E             Right contains 2 more items, first extra item: 'b2'

  libs/engine/tests/test_query_facts.py:483: AssertionError
  =========================== short test summary info ============================
  FAILED libs/engine/tests/test_query_facts.py::TestSolHigh03AtomicRecordPageExtension::test_two_facts_in_batch_seen_across_pages
  FAILED libs/engine/tests/test_query_facts.py::TestSolHigh03AtomicRecordPageExtension::test_limit_1_over_3_row_batch_returns_all_3
  2 failed in 0.14s
  ```
- **Result**: Mutation successfully caught.

---

### Mutation 04: Revert to Ordinal-Only Null Check in `_check_counts_arrival`
- **Mutation Applied**: Reverted `_check_counts_arrival` in `canonical_audit.py` to only query `arrival_ordinal IS NULL`, ignoring `arrival_seq IS NULL`.
- **Target Test**: `libs/engine/tests/test_audit_rebase_d3.py::TestGateD3_1_DetectionCoordinates::test_l1_detects_null_arrival_seq_with_location_claim`
- **Execution Command**:
  ```bash
  uv run --package loops pytest libs/engine/tests/test_audit_rebase_d3.py::TestGateD3_1_DetectionCoordinates::test_l1_detects_null_arrival_seq_with_location_claim -q
  ```
- **Output**:
  ```
  F                                                                        [100%]
  =================================== FAILURES ===================================
  _ TestGateD3_1_DetectionCoordinates.test_l1_detects_null_arrival_seq_with_location_claim _
  ...
          counts = next(c for c in report.checks if c.name == "counts")
  >       assert not counts.ok
  E       AssertionError: assert not True
  E        +  where True = Check(name='counts', ok=True, detail='4 fact(s), 0 tick(s) accounted for', behind_by=0, at_ordinal=-1).ok

  libs/engine/tests/test_audit_rebase_d3.py:203: AssertionError
  =========================== short test summary info ============================
  FAILED libs/engine/tests/test_audit_rebase_d3.py::TestGateD3_1_DetectionCoordinates::test_l1_detects_null_arrival_seq_with_location_claim
  1 failed in 0.49s
  ```
- **Result**: Mutation successfully caught.

---

## 4. Full Test Suite Verification

All 7 suites executed cleanly in the worktree:

| Suite | Package / Command | Baseline | Result | Status |
|---|---|---|---|---|
| **atoms** | `uv run --package atoms pytest libs/atoms/tests -q` | 517 passed | **517 passed** in 7.76s | PASSED |
| **engine** | `uv run --package loops pytest libs/engine/tests -q` | 1894 passed, 1 skipped | **1900 passed, 1 skipped** in 52.53s (+6 new tests) | PASSED |
| **sdk** | `uv run --package sdk pytest libs/sdk/tests -q` | 324 passed | **324 passed** in 15.81s | PASSED |
| **lang** | `uv run --package lang pytest libs/lang/tests -q` | 655 passed | **655 passed** in 2.96s | PASSED |
| **store** | `uv run --package store pytest libs/store/tests -q` | 176 passed | **176 passed** in 11.49s | PASSED |
| **arch** | `uv run pytest tests/architecture -q` | 98 passed | **98 passed** in 3.07s | PASSED |
| **apps** | `uv run --package loops pytest apps/loops/tests -q` | 2530 passed, 1 xfailed | **2530 passed, 1 xfailed** in 9.83s | PASSED |

---

## 5. Git Log & Status

- **Commit 1**: `7c792dfd` `fix(engine): resolve five sol-HIGH total-completion findings`
- **Commit 2**: `docs: add SOLHIGH-FIX-REPORT.md`
- **Working Tree**: Clean.
