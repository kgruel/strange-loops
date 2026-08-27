# WP4-SOL-FIX-REPORT: SOL-WP4-01 & SOL-WP4-02 Fix & Verification Report

- **Worktree:** `/private/tmp/claude-501/-Users-kaygee-Code-loops/46177474-a70b-40c7-b5c8-95ac89e78641/scratchpad/wt-wp4`
- **Branch:** `slice/D-wp4`
- **Defects Fixed:** `SOL-WP4-01` (Major), `SOL-WP4-02` (Minor)
- **Status:** **RESOLVED, VERIFIED, PINNED, COMMITTED**

---

## 1. SOL-WP4-01 Fix: Dissolution of `beyond_offset` Without Shim

### Defect Description
`Check` in `libs/engine/src/engine/canonical_audit.py` retained a backward-compatibility `@property def beyond_offset(self) -> bool` and published `"beyond_offset"` in `as_dict()`. The ratified Slice D architecture dissolves `beyond_offset` into the coordinate pair `(behind_by, at_ordinal)` with no compatibility shims.

### Implementation Details
1. **`libs/engine/src/engine/canonical_audit.py`**:
   - Removed `@property def beyond_offset(self) -> bool`.
   - Removed `"beyond_offset": self.beyond_offset` from `Check.as_dict()`.
   - Published dict now strictly contains `{"check", "ok", "detail", "behind_by", "at_ordinal"}`.
2. **`libs/engine/src/engine/probe.py`**:
   - Updated docstring reference from `canonical_audit.Check.beyond_offset` to `canonical_audit.Check.behind_by`.
3. **`apps/loops/src/loops/commands/store.py`**:
   - Removed comment reference to `Check.beyond_offset`.

---

## 2. Residue Sweep: Grep Before & After

### Raw BEFORE Grep (`git grep -n "beyond_offset" -- ':!docs' ':!*.log'`)
```
WP4-REPORT.md:25:  - **Check Dataclass**: `name`, `ok`, `detail`, `behind_by: int = 0`, `at_ordinal: int = -1`, plus backward-compatible `beyond_offset` property.
apps/loops/src/loops/commands/store.py:394:            # engine.canonical_audit.Check.beyond_offset. That is where an
apps/loops/tests/test_store_command.py:1027:        assert offset["beyond_offset"] is True
libs/engine/src/engine/canonical_audit.py:108:    def beyond_offset(self) -> bool:
libs/engine/src/engine/canonical_audit.py:119:            "beyond_offset": self.beyond_offset,
libs/engine/src/engine/probe.py:124:    ``canonical_audit.Check.beyond_offset``). This is one stamped-offset
libs/engine/tests/test_canonical_audit.py:376:def test_deep_never_stamps_beyond_offset_on_a_line_behind_a_rewound_offset(tmp_path):
libs/engine/tests/test_canonical_audit.py:381:    assert not any(c.beyond_offset for c in deep.checks), deep.as_dict()
```

### Raw AFTER Grep (`git grep -n "beyond_offset" -- ':!docs' ':!*.log' ':!WP4-REPORT.md'`)
```
apps/loops/tests/test_store_command.py:1028:        assert "beyond_offset" not in offset
apps/loops/tests/test_store_command.py:1562:        assert "beyond_offset" not in consumed
libs/engine/tests/test_audit_rebase_d3.py:465:# G-D3-5: SOL-WP4-01: beyond_offset dissolved without shim
libs/engine/tests/test_audit_rebase_d3.py:470:    """SOL-WP4-01: Check dissolves beyond_offset into behind_by/at_ordinal — no shim."""
libs/engine/tests/test_audit_rebase_d3.py:472:    def test_check_has_no_beyond_offset_attribute_and_as_dict_has_no_such_key(self):
libs/engine/tests/test_audit_rebase_d3.py:475:            _ = c.beyond_offset  # type: ignore[attr-defined]
libs/engine/tests/test_audit_rebase_d3.py:477:            _ = getattr(c, "beyond_offset")
libs/engine/tests/test_audit_rebase_d3.py:479:        assert "beyond_offset" not in d
libs/engine/tests/test_audit_rebase_d3.py:488:    def test_agreement_reports_checks_contain_no_beyond_offset(self, tmp_path: Path):
libs/engine/tests/test_audit_rebase_d3.py:494:                _ = c.beyond_offset  # type: ignore[attr-defined]
libs/engine/tests/test_audit_rebase_d3.py:495:            assert "beyond_offset" not in c.as_dict()
libs/engine/tests/test_audit_rebase_d3.py:500:            assert "beyond_offset" not in cd
libs/engine/tests/test_canonical_audit.py:384:        assert "beyond_offset" not in c.as_dict()
libs/engine/tests/test_canonical_audit.py:387:def test_check_has_no_beyond_offset_and_as_dict_has_no_such_key():
libs/engine/tests/test_canonical_audit.py:390:        _ = getattr(c, "beyond_offset")
libs/engine/tests/test_canonical_audit.py:392:        _ = c.beyond_offset  # type: ignore[attr-defined]
libs/engine/tests/test_canonical_audit.py:394:    assert "beyond_offset" not in d
```
*Note: Every hit in the AFTER grep is an explicit negative test assertion pinning `AttributeError` or key absence.*

---

## 3. SOL-WP4-02 Fix: Arrival Mode User-Facing Prose

### Defect Description
In `apps/loops/src/loops/commands/store.py:392`, the `INDEX BEHIND THE LOG` callout block used byte-offset prose for all stores ("bytes the index never claimed to have consumed", first unindexed line corroboration), failing to describe arrival semantics for arrival-canonical stores.

### Implementation Details
Dispatched `INDEX BEHIND THE LOG` callout prose by `canonical_mode(resolve_canonical_path(target_path))`:
- **Arrival Mode (`mode == "arrival"`)**:
  Reworded for arrival semantics:
  > *"the derived index is behind the canonical arrival log, and every disagreement is in records beyond the consumed ordinal — consistent with a crash between the arrival fsync and the index commit, with record counts and the rewound check confirming the consumed prefix; the tick chain was NOT walked (it would attest to a partial index). Catch the index up with 'loops read {target_path.stem}', or run 'loops store verify --deep' to rule out tampering"*
- **Legacy JSONL Mode (`mode != "arrival"`)**:
  Prose is **completely unchanged**, preserving byte-offset terminology and legacy diagnostic messages.

---

## 4. Acceptance & Unrecoverability Proof

1. **`libs/engine/tests/test_canonical_audit.py`**:
   - `test_check_has_no_beyond_offset_and_as_dict_has_no_such_key`: Asserts `pytest.raises(AttributeError)` on `c.beyond_offset` and `getattr(c, "beyond_offset")`, and `"beyond_offset" not in c.as_dict()`.
   - `test_deep_never_stamps_behind_by_on_a_line_behind_a_rewound_offset`: Asserts `c.behind_by > 0` and absence of `"beyond_offset"` across deep checks.
2. **`libs/engine/tests/test_audit_rebase_d3.py`**:
   - `TestGateD3_5_CheckDissolvesBeyondOffset`:
     - `test_check_has_no_beyond_offset_attribute_and_as_dict_has_no_such_key`: Pinned `AttributeError` and exact dictionary shape.
     - `test_agreement_reports_checks_contain_no_beyond_offset`: Validates all checks emitted by `audit_agreement` have no `beyond_offset` attribute and no dict key.
3. **`apps/loops/tests/test_store_command.py`**:
   - `test_the_lag_classification_rides_the_json_shape`: Updated assertion to check `behind_by > 0` and `"beyond_offset" not in offset`.
   - `test_arrival_store_index_behind_cli_prose_and_json`: Asserts arrival CLI output contains arrival prose (`"canonical arrival log"`, `"records beyond the consumed ordinal"`, `"rewound check"`) and `--json` contains `"behind_by"`, `"at_ordinal"`, and no `"beyond_offset"`.

---

## 5. Test Suites Verification

Full monorepo verification executed via `./dev test`:

```
=== Repo-level ratchets ===
98 passed in 3.02s
--- atoms ---
517 passed in 7.13s
--- custody ---
13 passed in 0.12s
--- engine ---
1893 passed, 1 skipped in 50.38s
--- lang ---
655 passed in 3.44s
--- sdk ---
324 passed in 14.19s
--- sign ---
37 passed in 4.03s
--- store ---
176 passed in 10.38s
--- loops ---
2530 passed, 1 xfailed in 9.56s
All test suites passed.
```

| Suite | Status | Passed / Skipped / XFailed |
|---|---|---|
| **Repo Ratchets** | PASSED | 98 passed |
| **atoms** | PASSED | 517 passed |
| **custody** | PASSED | 13 passed |
| **engine** | PASSED | 1893 passed, 1 skipped |
| **lang** | PASSED | 655 passed |
| **sdk** | PASSED | 324 passed |
| **sign** | PASSED | 37 passed |
| **store** | PASSED | 176 passed |
| **loops** | PASSED | 2530 passed, 1 xfailed |
| **Total** | **ALL PASSED** | **6243 tests executed** |

---

## 6. Fence Verification & Git Status

- **Fenced Files Modified**:
  - `libs/engine/src/engine/canonical_audit.py`
  - `libs/engine/src/engine/probe.py`
  - `apps/loops/src/loops/commands/store.py`
  - `libs/engine/tests/test_canonical_audit.py`
  - `libs/engine/tests/test_audit_rebase_d3.py`
  - `apps/loops/tests/test_store_command.py`
  - `WP4-SOL-FIX-REPORT.md` (report)
- **Branch**: `slice/D-wp4`
- **Git Status**: Clean, committed.
