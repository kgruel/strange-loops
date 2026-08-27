# WP-3 Implementation & Gate Report: Seal Re-base (D2) and W2-1 Cursor Semantics Ruling

**Work package**: WP-3 (Slice D §D2 Seal Re-base + W2-1 Cursor Axis Ruling)  
**Branch**: `slice/D-wp3`  
**Base Commit**: `b4fc82aaac4d457881c6fe6cce6cff6dcb17ef9e`  
**Implementation Commit**: `8f800ccfc0d8930c7b9650b025e15edc20da340b`  
**Status**: COMPLETE / ALL GATES PASSING

---

## 1. Executive Summary & Contract

WP-3 implements the complete re-basing of tick seal hash chains, fact-window commitments, and verification routines from store-local SQLite `rowid`s onto dense arrival coordinates `(arrival_ordinal, arrival_seq)` as specified in `docs/scratch/arrival-sliceD/design-proposal.md` §D2.

In addition, WP-3 resolves the **W2-1 Cursor Semantics Ruling** (`decision:design/sliceD-w2-1-cursor-axis-ruling`):
- Re-keyed `since`, `since_raw`, `replay_cursor`, and `ticks_since` to arrival coordinate pair cursors `(arrival_ordinal, arrival_seq)`.
- Avoided the known **W2-1 trap** where naive ordinal-only filtering (`WHERE arrival_ordinal > ?`) silently drops mid-batch rows sharing an ordinal.
- Added additive method `since_with_cursor(cursor)` returning `list[tuple[Fact, tuple[int, int]]]` to preserve exact coordinate state across incremental advances without breaking backward compatibility of `since()`.
- Updated downstream consumers (`Projection.advance`, `replay`) to stream and track coordinate pair cursors.

### Signed Bytes Law Invariant
- `_tick_envelope` format and canonical JCS byte representation remain **completely untouched**.
- `window_start` and `fact_cursor` remain explicit Fact IDs (ULIDs / Crockford strings).
- All historical sealed fixtures and signed ticks continue to verify identically without cryptographic degradation or re-signing.

---

## 2. Inventory of Sites & Changes

### `libs/engine/src/engine/sqlite_store.py`
1. **Cursor Resolution**:
   - Replaced `_cursor_rowid(fact_id)` with `_cursor_ordinal(fact_id) -> tuple[int, int] | None`.
   - Sentinels: `""` (start of store) resolves to `(-1, 0)`; missing fact ID resolves to `None`.
2. **Window Commitments (`_window_hash`)**:
   - Re-keyed query:
     ```sql
     SELECT {cols} FROM facts
     WHERE (arrival_ordinal, arrival_seq) > (?, ?)
       AND (arrival_ordinal, arrival_seq) <= (?, ?)
     ORDER BY arrival_ordinal, arrival_seq
     ```
3. **Chain Append & Chain Head (`append_tick_attested`, `current_chain_head`, `_genesis_payload`, `last_tick_ts`)**:
   - Re-keyed prev_row and edge_row queries to `ORDER BY arrival_ordinal DESC, arrival_seq DESC LIMIT 1`.
4. **Re-anchor Scans & Updates (`reanchor`)**:
   - Re-keyed Pass 1 fact scan to `SELECT rowid, ... FROM facts WHERE signature IS NOT NULL ORDER BY arrival_ordinal, arrival_seq`.
   - Re-keyed Pass 2 tick scan to `SELECT rowid, ... FROM ticks ORDER BY arrival_ordinal, arrival_seq`.
   - Preserved `UPDATE ... WHERE rowid = ?` for physical row address writes.
5. **Chain Verification (`verify_chain`)**:
   - Re-keyed tick rows scan to `SELECT ... FROM ticks ORDER BY arrival_ordinal, arrival_seq`.
   - Re-keyed `window_facts` and `covered` fact counts to coordinate ranges:
     ```sql
     SELECT COUNT(*) FROM facts
     WHERE (arrival_ordinal, arrival_seq) > (?, ?)
       AND (arrival_ordinal, arrival_seq) <= (?, ?)
     ```
6. **W2-1 Cursor Queries (`since`, `since_with_cursor`, `since_raw`, `replay_cursor`, `ticks_since`)**:
   - Accepts both `tuple[int, int]` coordinate pairs (defaulting to `(-1, 0)`) and integer cursors (normalizing `n <= 0 -> (-1, 0)` or `(n, 0)`).
   - Added `since_with_cursor(cursor)` for incremental folding without dropping mid-batch rows.

### `libs/engine/src/engine/projection.py`
- Updated `Projection.cursor` type annotation to `tuple[int, int] | int = (-1, 0)`.
- Updated `Projection.advance(store)` to call `store.since_with_cursor(self.cursor)` when available, capturing the exact `(ord, seq)` of each delivered event so multi-row batch records never drop subsequent rows upon step-by-step advance.

### `libs/engine/src/engine/replay.py`
- Updated `replay()` to consume `store.since_with_cursor()` when available, tracking and returning the final coordinate pair cursor.

### `libs/engine/src/engine/jsonl_store.py`
- Rewrote `_rebuild` docstring to reflect that window commitments and witness positions are defined structurally on arrival coordinates rather than rowid reproduction.

### `libs/engine/tests/test_tick_chain.py`
- Updated `test_displaced_fact_breaks_window` to mutate `arrival_ordinal = 1000` (tampering with coordinate sequence) instead of physical `rowid`.

### `libs/engine/tests/test_seal_rebase_d2.py`
- Created dedicated test suite covering gates G-D2-1 through G-D2-5 and W2-1 Equivalence.

---

## 3. Gate Results

| Gate | Description | Status | Evidence |
|------|-------------|--------|----------|
| **G-D2-1** | Pre-D sealed fixture verification & rowid equivalence on mirrored store | **PASS** | `TestGD2_1_PreDSealedFixture`: `verify_chain` ok=True, window hashes byte-equal to reference rowid computation |
| **G-D2-2** | Batch-bearing store seal preservation across rederivation | **PASS** | `TestGD2_2_BatchBearingStoreRederivation`: window hashes and fact coverage (7 facts) identical before and after `rederive_projections` |
| **G-D2-3** | Unresolvable cursor empty commitment | **PASS** | `TestGD2_3_UnresolvableCursor`: `_cursor_ordinal` returns None, window hashes to empty SHA-256 |
| **G-D2-4** | Verification under physical permutation | **PASS** | `TestGD2_4_VerificationUnderPermutation`: scrambled physical rowids yield identical verify_chain verdicts and counts as ordered store |
| **G-D2-5** | Rowid ratchet (shrink-only allowlist) | **PASS** | `TestGD2_5_RowidRatchet`: AST scan confirms 0 ORDER BY rowid, 0 range WHERE rowid, 0 COUNT rowid outside migration allowlist |
| **W2-1** | Incremental fold vs full replay equivalence under batches | **PASS** | `TestW2_1_IncrementalFoldEquivalence`: step-by-step projection advance matches full replay tag-for-tag across multi-row batch records |

---

## 4. Break / Restore Proofs

### Break Proof 1: G-D2-4 (Window Hash Permutation Invariance)
- **Mutation**: Mutated `_window_hash` in `sqlite_store.py` to resolve cursors via `rowid` and query `WHERE rowid > ? AND rowid <= ? ORDER BY rowid`.
- **Captured Failure**:
  ```text
  FAILED libs/engine/tests/test_seal_rebase_d2.py::TestGD2_4_VerificationUnderPermutation::test_permuted_insert_verify_chain_identical - AssertionError: Permuted store failed verify_chain: [{'tick': 't-1', 'name': 'seal', 'reason': 'window_hash mismatch — facts in window altered'}, {'tick': 't-2', 'name': 'seal', 'reason': 'window_hash mismatch — facts in window altered'}]
  assert False is True
  FAILED libs/engine/tests/test_seal_rebase_d2.py::TestGD2_5_RowidRatchet::test_no_rowid_in_ordering_range_or_count_windows - AssertionError: Found ORDER BY with rowid: ['ORDER BY rowid']
  ```
- **Restoration**: Restored coordinate range query `WHERE (arrival_ordinal, arrival_seq) > (?, ?) AND (arrival_ordinal, arrival_seq) <= (?, ?) ORDER BY arrival_ordinal, arrival_seq`.
- **Result**: `6 passed in 0.59s`.

### Break Proof 2: G-D2-2 (Batch Coordinate Window Coverage)
- **Mutation**: Mutated `_cursor_ordinal` in `sqlite_store.py` to drop `arrival_seq` (`SELECT arrival_ordinal, 0 FROM facts WHERE id = ?`).
- **Captured Failure**:
  ```text
  FAILED libs/engine/tests/test_seal_rebase_d2.py::TestGD2_2_BatchBearingStoreRederivation::test_seal_spanning_batch_record_survives_rederivation - AssertionError:
  >       assert report_before["covered_facts"] == 7
  E       assert 6 == 7
  ```
- **Restoration**: Restored `_cursor_ordinal` returning `(arrival_ordinal, arrival_seq)`.
- **Result**: `6 passed in 0.18s`.

### Break Proof 3: W2-1 Equivalence (Mid-Batch Row Retention)
- **Mutation**: Mutated `since_with_cursor` in `sqlite_store.py` to naive ordinal comparison (`WHERE arrival_ordinal > ?`).
- **Captured Failure**:
  ```text
  FAILED libs/engine/tests/test_seal_rebase_d2.py::TestW2_1_IncrementalFoldEquivalence::test_incremental_fold_equals_full_replay_on_permuted_batch_harness - AssertionError: assert ['f-2', 'f-3a', 'f-3b'] == ['f-1c', 'f-2', 'f-3a', 'f-3b']
  At index 0 diff: 'f-2' != 'f-1c'
  Right contains one more item: 'f-3b'
  ```
- **Restoration**: Restored pair comparison `WHERE (arrival_ordinal, arrival_seq) > (?, ?)`.
- **Result**: `6 passed in 0.17s`.

---

## 5. Full 7-Suite Test Results

All 7 test suites executed foreground with exact results recorded below:

| # | Suite | Command | Passed | Skipped / XFailed | Duration |
|---|-------|---------|--------|-------------------|----------|
| 1 | **Atoms** | `uv run --package atoms pytest libs/atoms/tests` | 517 | 0 | 7.80s |
| 2 | **Engine** | `uv run --package engine pytest libs/engine/tests` | 1876 | 1 skipped | 53.40s |
| 3 | **SDK** | `uv run --package sdk pytest libs/sdk/tests` | 324 | 0 | 14.25s |
| 4 | **Lang** | `uv run --package lang pytest libs/lang/tests` | 655 | 0 | 3.31s |
| 5 | **Store** | `uv run --package store pytest libs/store/tests` | 175 | 0 | 11.44s |
| 6 | **Architecture** | `uv run pytest tests/architecture` | 98 | 0 | 3.15s |
| 7 | **Apps/Loops** | `uv run --package loops pytest apps/loops/tests` | 2525 | 1 xfailed | 9.99s |
| **Total** | | | **6170** | **1 skipped, 1 xfailed** | **103.34s** |

---

## 6. Git Status & Clean Tree Verification

```text
$ git status
On branch slice/D-wp3
nothing to commit, working tree clean

$ git log -n 1 --oneline
8f800ccf feat(engine): re-base seal commitments and cursors onto arrival coordinates (WP-3)
```
