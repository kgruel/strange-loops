# SOL-HIGH r5 Fix Report: Resolution of Finding SOL-HIGH-11

**Branch**: `slice/D-solhigh-r5`  
**Base**: `feat/arrival-libs`  
**Working Directory**: `/private/tmp/claude-501/-Users-kaygee-Code-loops/46177474-a70b-40c7-b5c8-95ac89e78641/scratchpad/wt-solhigh5`  
**Date**: 2026-08-22  

---

## 1. Executive Summary & Defect Resolution

### Defect (SOL-HIGH-11)
In [`canonical_audit.py`](libs/engine/src/engine/canonical_audit.py) (~lines 562 & 620), the `--deep` audit's row-by-row index-vs-log comparison ordered SQLite rows by `(arrival_ordinal, arrival_seq)` but selected and compared only content fields (`FACT_COLUMNS`/`TICK_COLUMNS`). The stored coordinates `(arrival_ordinal, arrival_seq)` were never verified against the log walk's true coordinates `(record["ord"], seq)`.

**Reproduction**: On facts at `(1,0)`, `(2,0)`, `(3,0)`, updating the interior row `(2,0)` to `(1,1)` preserves row order, `NOT NULL`, and `UNIQUE` constraints. Because the shift is below the mark (`3`), L1's `rewound` check does not fire, and previous `--deep` content comparisons passed because content payloads were unchanged, even though witness prefix queries (e.g., `<= ordinal 1`) changed behavior.

### Fix
1. **Coordinate Selection** ([`_index_cursor_arrival`](libs/engine/src/engine/canonical_audit.py#L630-L637)):
   Included `("arrival_ordinal", "arrival_seq")` in the query alongside content columns:
   ```python
   def _index_cursor_arrival(conn: sqlite3.Connection, table: str, columns: tuple[str, ...]):
       cols = _present(conn, table, columns)
       coord_cols = _present(conn, table, ("arrival_ordinal", "arrival_seq"))
       all_cols = (*cols, *coord_cols)
       return len(cols), conn.execute(
           f"SELECT {', '.join(all_cols)} FROM {table} ORDER BY arrival_ordinal, arrival_seq"
       )
   ```
2. **True Log Coordinate Comparison** ([`_deep_checks_arrival`](libs/engine/src/engine/canonical_audit.py#L560-L602)):
   Carried each expected row's true coordinate from the log walk (`ordinal = record["ord"]` for `arrival_ordinal` and `seq` as the 0-based position in `rows_of_record(record)` for `arrival_seq`). Compared against stored index coordinates `(stored[arity], stored[arity + 1])` for both `fact` and `tick` rows.
   On mismatch, records a location claim:
   ```python
   elif (
       len(stored) >= arity + 2
       and (stored[arity], stored[arity + 1]) != (ordinal, seq)
   ):
       stored_coord = (stored[arity], stored[arity + 1])
       diverged.add(
           f"log record at ordinal {ordinal} ({t} {row[0]}) "
           f"coordinate ({ordinal}, {seq}) disagrees with index "
           f"coordinate ({stored_coord[0]}, {stored_coord[1]})",
           False,
           at_ordinal=ordinal,
       )
   ```
3. **Bounded Work Preserved**:
   No extra reads or log passes were added; `--deep` still streams $N$ records in a single pass ($1 + N$ total verification assertion in G-D3-2 holds strictly).

---

## 2. Test Coverage & Boundary Pinning

Added to [`libs/engine/tests/test_audit_rebase_d3.py`](libs/engine/tests/test_audit_rebase_d3.py):

1. `test_sol_high_11_deep_audit_detects_interior_coordinate_tamper_below_mark`:
   - Seeds facts at `(1,0)`, `(2,0)`, `(3,0)`.
   - Modifies middle row `(2,0)` to `(1,1)` in SQLite.
   - Verifies `audit_agreement(log_path).ok is True` (pinning the L1/deep boundary: below-mark content integrity is deep's claim, not L1's $O(1)$ fast-path).
   - Verifies `audit_deep(log_path).ok is False` with `content` check failing at `at_ordinal=2`, naming the row ID, stored coordinate `(1, 1)`, and log coordinate `(2, 0)`.
2. `test_sol_high_11_deep_audit_detects_tick_coordinate_tamper_below_mark`:
   - Seeds facts and ticks.
   - Modifies tick coordinate `(2,0)` to `(1,1)` in SQLite.
   - Verifies `audit_agreement(log_path).ok is True`.
   - Verifies `audit_deep(log_path).ok is False` with `content` check failing at `at_ordinal=2`, naming the tick ID, stored coordinate `(1, 1)`, and log coordinate `(2, 0)`.
3. Verified existing boundary-pin test `test_marked_open_trusts_structure_but_audit_detects_coordinate_tamper` continues to pass.

---

## 3. Mutation Proof

### Mutation
Reverted coordinate comparison in `libs/engine/src/engine/canonical_audit.py`:
```python
# Deleted elif block checking (stored[arity], stored[arity + 1]) != (ordinal, seq)
```

### Execution Under Mutation
```
$ uv run --package engine pytest libs/engine/tests/test_audit_rebase_d3.py -k test_sol_high_11
============================= test session starts ==============================
collected 18 items / 16 deselected / 2 selected

libs/engine/tests/test_audit_rebase_d3.py FF                             [100%]

=================================== FAILURES ===================================
_ TestGateD3_1_DetectionCoordinates.test_sol_high_11_deep_audit_detects_interior_coordinate_tamper_below_mark _
>       assert not deep_report.ok
E       AssertionError: assert not True

_ TestGateD3_1_DetectionCoordinates.test_sol_high_11_deep_audit_detects_tick_coordinate_tamper_below_mark _
>       assert not deep_report.ok
E       AssertionError: assert not True
======================= 2 failed, 16 deselected in 0.12s =======================
```

### Restored Green
```
$ uv run --package engine pytest libs/engine/tests/test_audit_rebase_d3.py -k test_sol_high_11
============================= test session starts ==============================
collected 18 items / 16 deselected / 2 selected

libs/engine/tests/test_audit_rebase_d3.py ..                             [100%]

======================= 2 passed, 16 deselected in 0.08s =======================
```
**Result**: Mutation killed.

---

## 4. Full Suite Acceptance Results

| Test Suite | Command | Result | Baseline |
| :--- | :--- | :--- | :--- |
| **Atoms** | `uv run --package atoms pytest libs/atoms/tests` | **517 passed** in 8.12s | 517 |
| **Engine** | `uv run --package engine pytest libs/engine/tests` | **1913 passed, 1 skipped** in 53.35s | 1911 + 1 skip (+2 new tests) |
| **SDK** | `uv run --package sdk pytest libs/sdk/tests` | **324 passed** in 15.95s | 324 |
| **Lang** | `uv run --package lang pytest libs/lang/tests` | **655 passed** in 4.22s | ~655 |
| **Store** | `uv run --package store pytest libs/store/tests` | **176 passed** in 12.26s | 176 |
| **Architecture** | `uv run pytest tests/architecture` | **98 passed** in 3.11s | 98 |
| **Apps (Loops)** | `uv run --package loops pytest apps/loops/tests` | **2530 passed, 1 xfailed** in 9.87s | 2530 + 1 xfail |

---

## 5. Git Status & Commits

- **Commit**: `11ec5c31` (`fix(engine): fix SOL-HIGH-11 — compare arrival coordinates in deep audit`)
- **Fence verification**: Strictly contained in `libs/engine/src/engine/canonical_audit.py` and `libs/engine/tests/test_audit_rebase_d3.py`.
- **Working Tree**: Clean (`git status` shows nothing to commit).
