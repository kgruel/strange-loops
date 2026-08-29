# Slice 2 / WP3 impl brief — admission extraction

Arc: `design:arrival-break-implementation`. Slice contract:
`design:arrival-break-slice2-backend-contract` @ `01M177MHWHD5HM574VSTDE17X8` (ratified).
Full design: `docs/scratch/arrival-break/slice2-design-proposal.md`. **Your sections:
§C (all — C.1's SD-1 ruling bounds you), §D.3.** Read WP1's landed
`arrival_contract.py` (RecordDraft is yours to construct toward) and its report's
design point 1.2 (bare-int refusal is ArrivalError so merge won't retry-spin) and
deviation D1 (the F1 caller in merge.py already widened). Deviations are reportable
(finding fact + report), never silent.

## Scope (proposal §C.3, exactly)

Into `engine/admission.py` (GROWS — no new module):
1. The admission op: §04 steps 1–8 orchestration extracted from
   `store/merge.py` `_merge_into_arrival` — the `append_marked_many` + `AppendRejected`
   retry loop IS the op. **Extraction stops at delegation**: `_merge_into_arrival`
   delegates to the op; NO merge arm is deleted (spine constraint 3 satisfied by
   ordering).
2. `MergeDivergence` / `_comparable` / `_refuse_divergence` trio — FORCED move (Rule 4:
   engine cannot import store).
3. `_verify_admitted_rows` / `_source_registry` (admission policy, §04 step 4).
4. `_entry_for` → `RecordDraft` constructor (its tick-chain nulling is the admission
   marker). Note: `_entry_for` carries slice-1's destination-genesis tick observer —
   preserve that semantics exactly (test_a_merged_tick_names_the_TARGETS_custodian
   pins it).
5. `fact_commitment_hash` + `_canonical_bytes` from `sqlite_store.py` — the sqlite
   spelling moves and `sqlite_store.py` imports it back for its five internal callers.
   **Do NOT mint a third `_canonical_bytes`; do NOT touch `arrival.py`'s spelling**
   (consolidation is slice 5's, named in the design).

SD-1 ruling bounds you: `_stage_arrival_coordinates` / `_check_arrival_provider_agreement`
/ `_stamp_arrival_axis` are PROJECTION — they stay in `sqlite_store.py` untouched.

Rule 18: `admission.py` joins `_SCAN_TARGETS` in the same change (custody moved into
it — the rule's stated trigger); the WP1 completeness ratchet does not cover it (it
is not `arrival*.py`-named), so the join is yours to remember — that asymmetry is by
design (scope-the-claim).

## Non-goals

No merge-arm deletions. No canonical_mode/residence changes. No projection or
coordinate-machinery moves (SD-1). No replicate/export (WP2). No KDL/registry (WP4).
Store's public surface unchanged: existing importers of the moved names keep working
(re-export from their old homes if needed — name the choice in the report).

## Oracle (the gate re-runs from scratch)

1. `test_arrival_merge.py` and `test_admission_verification.py` green UNMODIFIED in
   intent.
2. Rule 4 green — no engine→store import introduced (the trio moved instead).
3. Rule 18 green with `admission.py` scanned.
4. Mutation demo: revert the delegation (restore the inline loop bypassing the op) →
   merge admission tests still pass is a FINDING; the demo must show the op is on the
   live path — e.g. break the op's refusal → the admission tests fail; restore, diff
   clean.
5. Full engine + store suites green; counts reconciled, every delta accounted.
6. `git ls-files` clean on all changes.

## Mechanics

- Worktree: `git -C /Users/kaygee/Code/loops worktree add ~/Code/loops-s2wp3 -b slice2/wp3-admission 0d38c969`
  (branch off the wave branch tip in your launch message; step 0 verify merge-base).
- Report AS YOU GO: `docs/scratch/arrival-break/slice2-wp3-report.md` on your branch.
  Loops emissions from MAIN checkout cwd, payload
  `agent=s2wp3-impl slice=2 wp=3 role=implementer`; facts only; never stage `.loops/`.
- Commits conventional, trailer:
  `Claude-Session: https://claude.ai/code/session_01JpCUT3bF3dukDk5xjDejRM`
- Finish: SendMessage to parent — tip, files, counts with deltas, mutation results,
  design choices one line each, deviations.
