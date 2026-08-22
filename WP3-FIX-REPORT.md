# WP-3 Gate-Fix Report: Findings W3-1, W3-2, W3-3

**Work Package**: WP-3 Gate-Fix Round  
**Branch**: `slice/D-wp3`  
**Working Directory**: `/private/tmp/claude-501/-Users-kaygee-Code-loops/46177474-a70b-40c7-b5c8-95ac89e78641/scratchpad/wt-wp3`  
**Status**: COMPLETE / ALL GATES PASSING  

---

## 1. Executive Summary & Findings Addressed

This gate-fix round addresses the three findings identified in WP-3 review:

1. **W3-1 (MODERATE — Behavioral Gate Discrimination over Regex Detection)**:
   - **Finding**: The D2 gates could not distinguish an arrival-axis implementation from one re-keying to SQLite's `rowid` synonym `oid`, as the G-D2-5 text ratchet only matched `\browid\b` and G-D2-4's harness did not test live chain-head selection or assert arrival vs rowid-divergent counts.
   - **Ruled Fix**: In accordance with the rule of construction over detection (not teaching regex more SQL synonyms), strengthened behavioral gate G-D2-4 (`test_permuted_insert_verify_chain_identical`) to assert values where the rowid and arrival axes disagree:
     - `verify_chain` per-tick window counts and cursor ordering under permutation (`t-1` covers 2 facts on arrival vs 4 on rowid; `t-2` covers 2 facts on arrival vs 0 on rowid).
     - Chain-head selection (`store.current_chain_head()` returning arrival-axis head `t-2` rather than rowid/oid head `t-1`).
     - Live predecessor-tick selection via `append_tick()` (asserting `t3_row[6] == t2_row_hash` and `t3_row[7] == "f-3"`, which rowid/oid selects as `t1_row_hash` / `"f-1"`).
     - Live newest-fact edge via `append_tick()` (asserting `t4_row[8] == "f-5"`, whereas rowid/oid selects `f-4`).
   - **Scope-the-Claim**: Narrowed G-D2-5's docstring to state clearly that it is a residue locator for the literal spelling, not proof of axis correctness; the behavioral gate owns the verdict.

2. **W3-2 (MINOR — Allowlist Shrink)**:
   - **Finding**: G-D2-5's allowlist named non-existent `_rebuild_table_with_coordinates` alongside real function `_rebuild_table`.
   - **Fix**: Dropped the stale `_rebuild_table_with_coordinates` entry, leaving the allowlist shrunk to only actual rowid-containing functions.

3. **W3-3 (MINOR — Projection Pair-Cursor Guard at Vertex Boundary Reconciliation)**:
   - **Finding**: `Projection.cursor` is `tuple[int, int] | int`, and `vertex.py:981` performed integer comparisons/modulo for loop boundary reconciliation, risking `TypeError` on tuple cursors.
   - **Ruled Fix**: Added an explicit typed guard in `vertex.py` raising `NotImplementedError("loop boundary accounting is count-based; pair-cursor projections are not yet supported here")`. Added a unit test in `test_vertex.py` pinning this error. (Cursor type unification deferred as a candidate for the simplify pass).

---

## 2. Mutation Demonstration (W3-1 Proof)

To prove that G-D2-4 now discriminates the chain-head axis behaviorally against `oid` / `rowid` mutations:

### Mutation Applied
In `libs/engine/src/engine/sqlite_store.py` (`append_tick_attested`), mutated predecessor selection from arrival coordinates to SQLite's `oid` synonym:
```python
# Mutated:
prev_row = self._conn.execute(
    f"SELECT {_TICK_ROW_SQL} FROM ticks "
    "ORDER BY oid DESC LIMIT 1"
).fetchone()
```

### Captured Failure Output
```text
=================================== FAILURES ===================================
_ TestGD2_4_VerificationUnderPermutation.test_permuted_insert_verify_chain_identical _

self = <tests.test_seal_rebase_d2.TestGD2_4_VerificationUnderPermutation object at 0x106c60050>
tmp_path = PosixPath('/private/var/folders/kc/gvf_th792ydbdzvtns23cx580000gn/T/pytest-of-kaygee/pytest-13741/test_permuted_insert_verify_ch0')

    def test_permuted_insert_verify_chain_identical(self, tmp_path: Path) -> None:
        ...
        # Live minting under permutation: predecessor-tick selection, newest-fact edge,
        # and window_start MUST follow the arrival coordinate axis, not rowid/oid.
        t3_id = store_perm.append_tick(
            Tick(name="seal", ts=datetime.fromtimestamp(104.0, tz=UTC), payload={"n": 3}, origin="test")
        )
        t3_row = conn_perm.execute(
            f"SELECT {_TICK_ROW_SQL} FROM ticks WHERE id = ?", (t3_id,)
        ).fetchone()

        # Arrival-axis predecessor is t-2 (rowid/oid axis would pick t-1)
>       assert t3_row[6] == t2_row_hash, f"Expected prev_hash from arrival head t-2, got {t3_row[6]}"
E       AssertionError: Expected prev_hash from arrival head t-2, got 468e7fa50298d4029c7d4b6766c0471387c5962287d757474d71f97d9e95d398
E       assert '468e7fa50298...1f97d9e95d398' == '73f9ace6f3f6...d47c8362d9383'
E         
E         - 73f9ace6f3f6f4d83d649c42c68e73cd9c15098fef80a7831e6d47c8362d9383
E         + 468e7fa50298d4029c7d4b6766c0471387c5962287d757474d71f97d9e95d398

libs/engine/tests/test_seal_rebase_d2.py:370: AssertionError
=========================== short test summary info ============================
FAILED libs/engine/tests/test_seal_rebase_d2.py::TestGD2_4_VerificationUnderPermutation::test_permuted_insert_verify_chain_identical
========================= 1 failed, 5 passed in 0.12s ==========================
```

### Restoration
Restored `ORDER BY arrival_ordinal DESC, arrival_seq DESC LIMIT 1` in `sqlite_store.py`. Suite returns to clean green (`6 passed in 0.10s`).

---

## 3. Inventory of Changes & Fenced Sites

All edits are strictly within the fenced sites (`libs/engine/src/engine/{sqlite_store,vertex}.py`, `libs/engine/tests/**`):

1. `libs/engine/src/engine/vertex.py`:
   - Added `isinstance(replayed, tuple)` guard raising `NotImplementedError` in `evaluate_boundaries` / loop boundary reconciliation during `replay()`.
2. `libs/engine/tests/test_seal_rebase_d2.py`:
   - Extended `TestGD2_4_VerificationUnderPermutation` with window count discrimination, chain head validation, live mint predecessor selection, and newest-fact edge checks.
   - Narrowed `TestGD2_5_RowidRatchet` docstring to clarify scope as a residue locator.
   - Dropped `_rebuild_table_with_coordinates` from allowlist.
3. `libs/engine/tests/test_vertex.py`:
   - Added `test_replay_pair_cursor_boundary_count_not_implemented` pinning the `NotImplementedError` guard.

---

## 4. Full 7-Suite Test Results

All test suites executed foreground with exact results:

| # | Suite | Command | Passed | Skipped / XFailed | Duration |
|---|-------|---------|--------|-------------------|----------|
| 1 | **Atoms** | `uv run --package atoms pytest libs/atoms/tests` | 517 | 0 | 8.06s |
| 2 | **Engine** | `uv run --package engine pytest libs/engine/tests` | 1877 | 1 skipped | 54.05s |
| 3 | **SDK** | `uv run --package sdk pytest libs/sdk/tests` | 324 | 0 | 25.75s |
| 4 | **Lang** | `uv run --package lang pytest libs/lang/tests` | 655 | 0 | 3.41s |
| 5 | **Store** | `uv run --package store pytest libs/store/tests` | 175 | 0 | 11.85s |
| 6 | **Architecture** | `uv run pytest tests/architecture` | 98 | 0 | 3.04s |
| 7 | **Apps/Loops** | `uv run --package loops pytest apps/loops/tests` | 2525 | 1 xfailed | 10.12s |
| **Total** | | | **6171** | **1 skipped, 1 xfailed** | **116.28s** |

---

## 5. Notes for Simplify Pass

- **Cursor Type Unification**: `Projection.cursor` currently supports `tuple[int, int] | int`. In the subsequent simplify pass, cursor representations across projections and loops can be unified so that loop boundary reconciliation natively understands coordinate pair cursors or operates purely on event sequence deltas.
