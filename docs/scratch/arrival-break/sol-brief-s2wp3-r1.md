# Sol review brief — arrival-break slice 2 / WP3 (admission extraction), round 1 (per-WP, LOW)

You are the cross-family reviewer for slice-2 WP3. Review the WP diff adversarially for
correctness against the design contract. You review and report — no fixes, no commits.
Run tests/scripts to verify claims empirically (preferred over reading alone).

## 1. Anchor

- Repo checkout: this working directory (a git worktree of /Users/kaygee/Code/loops).
- Branch: `slice2/wp3-admission`, tip `e8c93295`, off wave base `0d38c969`.
- Diff spec: `git diff 0d38c969...e8c93295`. 8 files.
- Suites: per-package (`.venv/bin/python -m pytest libs/engine/tests -q`, store, and
  `tests/architecture` from the root env).

## 2. Design contract (what the code must honor)

From `design:arrival-break-slice2-backend-contract` (ratified,
`01M177MHWHD5HM574VSTDE17X8`) §C + §D.3:

1. `engine/admission.py` GROWS (no new module): the admission op extracted from
   `store/merge.py` `_merge_into_arrival` — **extraction stops at delegation**; the
   merge arm still exists and delegates; NO merge arm deleted; `merge_store` dispatch
   preserved.
2. Moves: the op orchestration; `MergeDivergence`/`_comparable`/`_refuse_divergence`
   (FORCED by Rule 4 — engine may not import store); `_verify_admitted_rows`/
   `_source_registry`; `_entry_for` → `RecordDraft` constructor (renamed `_draft_for`);
   `fact_commitment_hash` + `_canonical_bytes` (sqlite spelling; `arrival.py`'s spelling
   untouched — NO third spelling anywhere).
3. **SD-1 ruling**: `_stage_arrival_coordinates`/`_check_arrival_provider_agreement`/
   `_stamp_arrival_axis` are projection — byte-identical, untouched.
4. Slice-1's destination-genesis tick observer semantics preserved exactly in the
   draft constructor (`test_a_merged_tick_names_the_TARGETS_custodian` pins it).
5. Rule 18: `admission.py` joins `_SCAN_TARGETS`. Rule 4: no engine→store import.
6. Public surface unchanged: `store.MergeDivergence`, both `fact_commitment_hash` /
   `_fact_commitment_hash` import paths resolve to the same function object.

**NON-NEGOTIABLES**: zero test-count deltas (collection counts: engine 1990 collected,
store 180, architecture 99); `arrival.py` diff-empty; the 14 arrival test files —
`test_arrival_merge.py` carries exactly one docstring pointer, no assertion change;
`test_tick_chain.py` carries exactly the D2 dual-module monkeypatch fix.

## 3. Unverified fixes

None — no post-gate fix commits. The gate PASSed at the reviewed tip with all seven
oracle items and re-derived every baseline in a disposable worktree.

## 4. Prior review state (gate, already run — do not re-litigate; flag if unsound)

Gate PASS at e8c93295: three mutations exact (divergence refusal 3F, admitted-rows
verification 5F, source-vs-target genesis observer 1F — each travels
merge_store → _merge_into_arrival → admit_records, which is strictly stronger than a
revert-the-delegation arm); D2's severed-monkeypatch evidence reproduced bit-for-bit
including the silence (51 green over a half-JCS scenario with the fix removed); D1's
forced-move argument verified at source; SD-1 byte-identical; public surface resolves
under every historical name to the same object; line counts and lint exact. Two
report-precision findings dismissed (docstring-pointer overclaim; import-cost figure
scoping — the gate's own measurement supports the conclusion more strongly).

## 5. Seeded review targets

- The two-callback op signature (`target_state`, `rederive`): is any failure mode
  swallowed at the seam — e.g. can a caller's `rederive` raising leave the target in a
  state the retry loop then misreads?
- `AdmissionResult` → `MergeResult` mapping: four counts across — construct a case
  where a count could double or drop (retry after AppendRejected) and check invariants.
- The module-level `engine.admission` import in `merge.py` (deliberate discipline
  break): any import-cycle risk under a different first-import order (store first vs
  engine first)?
- `_entries_of` (draft→Entry seam, named slice-5 residue): confirm it cannot drift from
  `FileLedger.append`'s conversion silently — is the duplication byte-equivalent today?

## 6. Verdict format

Per §2 item: PASS/FAIL + evidence. New findings: `S2WP3-L-<n>`, file:line, severity
(BLOCKING/NON-BLOCKING), concrete failure scenario, evidence. Then one line:
**CONVERGED** or **NOT CONVERGED** (with the blocking list).
