# WP-4: Audit Re-base (D3) — Final Slice-D Package Implementation Report

## Summary

This report documents the implementation and verification of **WP-4 (audit re-base / D3)**, completing the final package of **Slice D** per `docs/scratch/arrival-sliceD/design-proposal.md` §D3 and `docs/scratch/arrival-sliceD-impl/sites-e4.md`.

---

## 1. Scope & Implementation Details

### A. `libs/engine/src/engine/arrival.py`
- Added public method `ArrivalLog.anchor(self, mark: ResumeMark | None) -> dict | None`:
  - Delegates to `self._anchor_for(mark)` and returns the validated anchor record dictionary on success, or `None` on rejection.
  - Ensures verification only trusts the seek hint in `mark.arrival_offset` after shape, lineage, ordinal, and authority validation pass on the anchor record.

### B. `libs/engine/src/engine/arrival_projection.py`
- Upgraded `_derived_digests` and `audit_derived_log` to use `collections.Counter` (multisets of 32-byte sha256 digests).
- Order-insensitive and multiplicity-preserving:
  - Permuted lines in `.jsonl` agree cleanly with the canonical `.arrival` log.
  - Duplicated or removed lines are detected with exact `missing` and `extra` cardinalities.
  - Retains flat memory bound in record count and linear in largest single record size.

### C. `libs/engine/src/engine/canonical_audit.py`
- Implemented arrival-native L1 and `--deep` audits per the §D3 specification:
  - **Check Dataclass**: `name`, `ok`, `detail`, `behind_by: int = 0`, `at_ordinal: int = -1`, plus backward-compatible `beyond_offset` property.
  - **AgreementReport.index_behind**: Implemented as a location claim: `bool(d) and all(c.behind_by > 0 for c in d)`.
  - **L1 `audit_agreement` (5 checks)**:
    1. `index`: Derived SQLite index exists and is readable.
    2. `consumed`: Stamped `ResumeMark` vs log head ordinal (suffix count via `walk_marked` — bounded $O(K)$ where $K$ is records behind).
    3. `rewound`: Structural SQLite query detecting any index row with `arrival_ordinal > consumed_ordinal`.
    4. `counts`: Stamped counters vs `COUNT(*)`, plus `arrival_ordinal IS NULL` backstop claim (`"this index holds a row carrying no arrival coordinate"`).
    5. `consumed_edge`: Anchor record at consumed ordinal read via `ArrivalLog.anchor(mark)`, decoded via `rows_of_record`, and compared via `row_matches`.
    - **Invariant**: L1 never calls `ArrivalLog.read()` or `ArrivalLog.walk()`.
  - **`--deep` `audit_deep`**:
    1. Runs L1 checks first.
    2. Streams entire arrival log with `ArrivalLog.walk()` comparing every record field-for-field in coordinate order `(arrival_ordinal, arrival_seq)`.
    3. Re-derives tick hash chain (`prev_hash`, `window_start`, `window_hash`) directly from canonical log content.
    4. Runs multiset derived log audit `audit_derived_log` if `.jsonl` projection exists.
  - **Legacy JSONL Dispatch**: Seamlessly dispatches based on `canonical_mode(canonical)`, preserving JSONL store audit compatibility.

### D. `libs/engine/src/engine/preflight.py`
- Docstring truth-up (line 384): Updated single sentence from `"Arrival-canonical: the agreement audit for this mode is a later cut."` to `"Arrival-canonical: agreement audit lives in canonical_audit, not preflight."`.
- Runtime behavior is byte-identical; exact 1-sentence diff preserved.

### E. `apps/loops/src/loops/commands/store.py`
- Added the arrival dispatch arm in `canonical_agreement` (lines 122–165):
  - Checks `mode = canonical_mode(canonical)`.
  - For `mode == "arrival"`: ensures index with `ensure_arrival_index(canonical)` if absent.
  - Routes to `audit_deep(canonical)` or `audit_agreement(canonical)`.

---

## 2. Gate Verification & Test Suites

### Gate Verification Suite (`libs/engine/tests/test_audit_rebase_d3.py`)
- **`G-D3-1`** (`TestGateD3_1_DetectionCoordinates`):
  - Index behind arrival: reports `index_behind=True`, `behind_by=2`, `at_ordinal=3`.
  - Out-of-band insert: reports `counts` check failure with coordinate backstop claim.
  - Edit to last consumed row: reports `consumed_edge` check failure with coordinate and id.
  - Rewound marker: reports `rewound` check failure with offending ordinal and consumed ordinal.
- **`G-D3-2`** (`TestGateD3_2_BoundedWorkInstrumentation`):
  - Healthy N-record store: verifies exactly 1 anchor record + 0 suffix records.
  - K-behind store: verifies exactly 1 anchor record + K suffix records ($1 + K$).
  - `--deep` audit: verifies full $N$ records.
  - Confirmed `ArrivalLog.read` and `ArrivalLog.walk` are never invoked in L1.
- **`G-D3-3`** (`TestGateD3_3_TornArrivalTail`):
  - Torn arrival tail reports `index_behind=True` ("behind"), never "tampered".
- **`G-D3-4`** (`TestGateD3_4_MultisetDerivedLogAudit`):
  - Reordered derived `.jsonl`: multiset audit agrees.
  - Duplicated line in derived `.jsonl`: detected as extra line.
  - Removed line in derived `.jsonl`: detected as missing line.

### CLI Dispatch Suite (`apps/loops/tests/test_store_command.py`)
- `TestArrivalStoreCanonicalAgreement`:
  - `test_arrival_store_audits_clean_through_cli`: `sl store verify` passes with `chain intact`.
  - `test_arrival_store_deep_audit_through_cli`: `sl store verify --deep` passes with `canonical content verified` and `chain re-derived`.
  - `test_arrival_store_canonical_agreement_helper`: `canonical_agreement` returns index path and clean report.

---

## 3. Break / Restore Demonstrations

### Break / Restore 1: `G-D3-1 (rewound)`
- **Break**: Forced `_check_rewound_arrival` to return `Check("rewound", True, ...)` ignoring index ordinals beyond `consumed_ordinal`.
  - **Output**:
    ```
    FAILED libs/engine/tests/test_audit_rebase_d3.py::TestGateD3_1_DetectionCoordinates::test_l1_detects_rewound_marker_with_coordinates
    AssertionError: assert not True
    + where True = Check(name='rewound', ok=True, detail='broken for test', behind_by=0, at_ordinal=-1).ok
    ```
- **Restore**: Restored full query `SELECT MAX(arrival_ordinal) > consumed_ord`.
  - **Output**:
    ```
    libs/engine/tests/test_audit_rebase_d3.py . [100%]
    1 passed, 10 deselected in 0.71s
    ```

### Break / Restore 2: `G-D3-2 (bounds)`
- **Break**: Injected `_ = list(log.walk())` into `_audit_agreement_arrival`.
  - **Output**:
    ```
    FAILED libs/engine/tests/test_audit_rebase_d3.py::TestGateD3_2_BoundedWorkInstrumentation::test_healthy_store_verifies_exactly_anchor_plus_zero_suffix
    AssertionError: walk() called in L1
    FAILED libs/engine/tests/test_audit_rebase_d3.py::TestGateD3_2_BoundedWorkInstrumentation::test_k_behind_store_verifies_exactly_one_anchor_plus_k_suffix
    AssertionError: walk() called in L1
    ```
- **Restore**: Removed `log.walk()`, relying strictly on `log.anchor(mark)` and `log._walk_tail()`.
  - **Output**:
    ```
    libs/engine/tests/test_audit_rebase_d3.py ... [100%]
    3 passed, 8 deselected in 0.08s
    ```

### Break / Restore 3: `G-D3-4 (duplicate)`
- **Break**: Replaced multiset differences in `audit_derived_log` with `set(derived.keys()) - set(present.keys())`.
  - **Output**:
    ```
    FAILED libs/engine/tests/test_audit_rebase_d3.py::TestGateD3_4_MultisetDerivedLogAudit::test_duplicated_line_in_derived_jsonl_is_detected
    AssertionError: assert not True
    + where True = DerivedLogAgreement(ok=True, missing=0, extra=0, ...).ok
    ```
- **Restore**: Restored `Counter` multiset arithmetic `derived - present` and `present - derived`.
  - **Output**:
    ```
    libs/engine/tests/test_audit_rebase_d3.py . [100%]
    1 passed, 10 deselected in 0.07s
    ```

---

## 4. Full Workspace Test Suite Results

All test suites executed in foreground:

| Package | Test Target | Results | Duration |
| :--- | :--- | :--- | :--- |
| **atoms** | `libs/atoms/tests` | **517 passed** | 8.07s |
| **sdk** | `libs/sdk/tests` | **324 passed** | 17.23s |
| **store** | `libs/store/tests` | **176 passed** | 10.66s |
| **architecture** | `tests/architecture` | **98 passed** | 3.00s |
| **lang** | `libs/lang/tests` | **655 passed** | 3.47s |
| **engine** | `libs/engine/tests` | **1889 passed, 1 skipped** | 56.21s |
| **loops** | `apps/loops/tests` | **2529 passed, 1 xfailed** | 10.69s |

---

## 5. `preflight.py` Git Diff

```diff
diff --git a/libs/engine/src/engine/preflight.py b/libs/engine/src/engine/preflight.py
index 6e7ff923..add1b75a 100644
--- a/libs/engine/src/engine/preflight.py
+++ b/libs/engine/src/engine/preflight.py
@@ -381,7 +381,7 @@ def _sqlite_preflight(
 def _arrival_preflight(
     canonical: Path, mode: PreflightMode, open_kwargs: dict[str, Any]
 ) -> PreflightResult:
-    """Arrival-canonical: the agreement audit for this mode is a later cut.
+    """Arrival-canonical: agreement audit lives in canonical_audit, not preflight.
 
     Scope stated rather than blurred: an arrival store HAS a log/index pair,
     so agreement is not vacuous the way sqlite's is — it is simply not
```
