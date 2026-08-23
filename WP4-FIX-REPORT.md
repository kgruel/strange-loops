# WP-4 Gate-Fix Report: Finding W4-1

**Work Package**: WP-4 Gate-Fix Round  
**Branch**: `slice/D-wp4`  
**Working Directory**: `/private/tmp/claude-501/-Users-kaygee-Code-loops/46177474-a70b-40c7-b5c8-95ac89e78641/scratchpad/wt-wp4`  
**Status**: COMPLETE / ALL GATES PASSING  

---

## 1. Executive Summary & Defect Addressed

This gate-fix addresses gate finding **W4-1**:

- **Defect (`canonical_audit.py`, `_check_consumed_arrival :394/:396`)**:
  When a `ResumeMark` existed but anchor validation failed (e.g. corrupted byte offset or ordinal mismatch), `_check_consumed_arrival` called `log.walk_marked(None)`. This walked and verified the entire log from ordinal 0 (via `_walk_marked_from_zero` -> `_verify_from`), performing $O(N)$ unbounded work on a reachable L1 path. It then reported `behind_by=<total record count>`, an invented and false quantity (gate reproduced: 201 records verified, `behind_by=201`, on a store 0 behind whose sibling `counts` check truthfully reported all 200 facts accounted for).
  G-D3-2's prior test instrumentation missed this because it only instrumented `ArrivalLog._walk_tail` and guarded `ArrivalLog.read` / `ArrivalLog.walk` by name.

- **Ruled Fix**:
  1. **Branch 2 (`mark` present, anchor failed)**: Removed `log.walk_marked(None)`. The consumed check now immediately reports $O(1)$ failure with the location claim `"anchor verification failed; consumed position unverifiable at ordinal <coord>"` (coordinate included) with `behind_by=0` (no invented magnitude). Consistent with `consumed_edge` which reports the anchor failure.
  2. **Branch 1 (`mark is None` — nothing consumed)**: Kept unchanged; walking the log from zero is the designed cost for unconsumed stores.
  3. **G-D3-2 Instrumentation Re-based onto the Quantity Seam**: Record-verification counting is now re-based onto `ArrivalLog._verify_from` (the single verification loop in `arrival.py` through which both from-zero and resumed-suffix walks verify records) and `ArrivalLog.anchor` (anchor validation attempts). Exact totals asserted:
     - healthy store: 1 anchor record + 0 suffix = 1 record verified
     - $K$ behind store: 1 anchor record + $K$ suffix = $1 + K$ records verified
     - anchor-failed store: 1 anchor attempt + 0 suffix = 1 record verified (NO walk from zero)
     - `--deep` audit: $N$ records verified
  4. **New Gate Reproduction Fixture Test**: Added `test_anchor_failed_corrupted_offset_verifies_single_record_no_walk` reproducing the gate fixture (200 facts / 201 log records, current mark, offset corrupted mid-record): verifies $O(1)$ work (exact count 1 verified), `behind_by=0`, `counts` check ok (`"200 fact(s), 0 tick(s) accounted for"`), and `index_behind=False`.

---

## 2. Mutation Demonstration

To mutation-prove that the new test and quantity seam catch unbounded from-zero walks on anchor failure:

### Mutation Applied
Re-introduced `log.walk_marked(None)` in Branch 2 of `canonical_audit.py`:
```python
        resumed, pairs = log.walk_marked(None)
        suffix_count = sum(1 for _ in pairs)
        return Check(
            "consumed",
            False,
            f"index is behind arrival by {suffix_count} record(s), consumed through ordinal {mark.arrival_ordinal} — anchor verification failed",
            behind_by=suffix_count,
            at_ordinal=mark.arrival_ordinal,
        )
```

### Captured Failure Output
```text
=================================== FAILURES ===================================
_ TestGateD3_2_BoundedWorkInstrumentation.test_anchor_failed_corrupted_offset_verifies_single_record_no_walk _

self = <tests.test_audit_rebase_d3.TestGateD3_2_BoundedWorkInstrumentation object at 0x10adbd6e0>
tmp_path = PosixPath('/private/var/folders/kc/gvf_th792ydbdzvtns23cx580000gn/T/pytest-of-kaygee/pytest-13862/test_anchor_failed_corrupted_o0')

    def test_anchor_failed_corrupted_offset_verifies_single_record_no_walk(self, tmp_path: Path):
        """Gate W4-1 reproduction fixture: mark current, offset corrupted mid-record.
    
        Anchor validation fails => L1 verifies O(1) records (assert via quantity seam),
        consumed check reports unverifiable with NO behind_by magnitude, sibling counts check
        still truthfully reports all facts accounted for.
        """
        n_facts = 200
        log_path, db_path, store = _create_arrival_store(tmp_path, n_facts=n_facts)
    
        # Corrupt the offset in the index's store_meta table to point mid-record
        conn = sqlite3.connect(db_path)
        try:
            cur_offset = int(conn.execute(
                f"SELECT value FROM store_meta WHERE key = '{ARRIVAL_OFFSET_KEY}'"
            ).fetchone()[0])
            corrupted_offset = cur_offset - 5
            conn.execute(
                f"UPDATE store_meta SET value = ? WHERE key = '{ARRIVAL_OFFSET_KEY}'",
                (str(corrupted_offset),),
            )
            conn.commit()
        finally:
            conn.close()
    
        with _record_verification_counter() as counts:
            report = audit_agreement(log_path)
    
        assert not report.ok
        assert report.index_behind is False
    
        # Quantity seam: anchor failed => exactly 1 record verified (anchor attempt), NO walk from zero
        assert counts["anchor"] == 1
>       assert counts["walk"] == 0
E       assert 201 == 0

libs/engine/tests/test_audit_rebase_d3.py:327: AssertionError
=========================== short test summary info ============================
FAILED libs/engine/tests/test_audit_rebase_d3.py::TestGateD3_2_BoundedWorkInstrumentation::test_anchor_failed_corrupted_offset_verifies_single_record_no_walk
========================= 1 failed, 11 passed in 0.72s =========================
```

The from-zero count (`201`) is clearly visible in the failure output (`assert 201 == 0`).

### Restoration
Restored the $O(1)$ unverifiable check without walk in `canonical_audit.py`. Test suite returns to clean green (`12 passed in 0.36s`).

---

## 3. Inventory of Changes & Fenced Sites

Edits are strictly within the designated fence:

1. `libs/engine/src/engine/canonical_audit.py`:
   - Updated Branch 2 of `_check_consumed_arrival` to return `Check("consumed", False, f"anchor verification failed; consumed position unverifiable at ordinal {mark.arrival_ordinal}", at_ordinal=mark.arrival_ordinal)` without calling `walk_marked(None)`.
2. `libs/engine/tests/test_audit_rebase_d3.py`:
   - Re-based `TestGateD3_2_BoundedWorkInstrumentation` onto `_record_verification_counter` testing the quantity seam (`ArrivalLog._verify_from` + `ArrivalLog.anchor`).
   - Added `test_anchor_failed_corrupted_offset_verifies_single_record_no_walk`.

*Note on `arrival.py`:* No changes were required in `arrival.py`; the quantity seam is directly observable via existing methods `ArrivalLog._verify_from` and `ArrivalLog.anchor`.

---

## 4. Full 7-Suite Test Results

All seven test suites and root repository tests pass cleanly and truthfully:

| Suite | Command | Result |
| :--- | :--- | :--- |
| **`libs/atoms`** | `uv run pytest libs/atoms` | **517 passed** in 8.00s |
| **`libs/custody`** | `uv run pytest libs/custody` | **13 passed** in 0.11s |
| **`libs/engine`** | `uv run pytest libs/engine` | **1890 passed, 1 skipped** in 137.39s |
| **`libs/lang`** | `uv run pytest libs/lang` | **655 passed** in 3.79s |
| **`libs/sdk`** | `uv run pytest libs/sdk` | **324 passed** in 20.82s |
| **`libs/sign`** | `uv run pytest libs/sign` | **37 passed** in 3.88s |
| **`libs/store`** | `uv run pytest libs/store` | **176 passed** in 12.60s |
| **`apps/loops`** | `uv run pytest apps/loops` | **2529 passed, 1 xfailed** in 13.53s |
| **`tests` (root)** | `uv run pytest tests` | **110 passed** in 3.28s |

---

## 5. Commit Information

- **Commit**: `65e1adcb` (`fix(canonical_audit): fix gate finding W4-1 unbounded walk on anchor failure`) + report commit
- **Branch**: `slice/D-wp4`
- **Working Tree**: Clean
