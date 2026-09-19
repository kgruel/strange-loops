**REVISE, narrowly: four refusal tests need fixing; the verifier, receipt wording and cutover plan are accepted as they stand.** I found no P1 and could not construct a false pass.

This was a static review with no tools, and I ran no tests. `CORRECTION DIFF` arrived empty again, so I reviewed the full sources instead. I did not see or assess the modified `libs/migrate/README.md` or the rehearsal doc.

## Closure

| # | Prior finding | Status | Basis |
|---|---|---|---|
| 1 | Unchained historical tick left unverified while the receipt said `verified` | **Closed** | `verify_legacy_provenance.py:229-244` refuses an unchained tick after chaining starts, refuses any predecessor or cursor claim on one, and always refuses one post-S. The count is emitted as `unchained_historical_ticks`. My original repro now refuses at `:234`. Both placements and a direct `_TickChain` probe are tested. |
| 2 | Receipt overclaims | **Closed** | `:658-660` and `:673-679`: pins are `caller-supplied`, `pin_independence_verified` is false, the chain is `structurally-verified`, and envelope and inner signatures are disclaimed. The real-copy receipt matches. |
| 3 | Refusal coverage and engine tie | **Partial; see the P2 below** | The integration test is sound: preparer, then a real fresh `seal` rehearsal, then the verifier through the emitted tick, with input hashes and directory listing asserted unchanged. Most refusals are covered. Four never reach the check they name. |
| 4 | Legacy CLI refusal assumed | **Closed** | `plan:33-42` and blocker 3 now state that refusal is unverified and that disablement is the gate. |
| 5 | Rollback precondition uncheckable | **Closed** | `plan:358-374` requires the head to equal A in all three fields, plus Arrival-file, vertex and source hash pins. The restore runs from the pinned backup with an exclusive stage and fsync, and is forward-only otherwise. |
| – | Post-S forged key introduction | **Closed in code** | `:511-515` verifies every key introduction at any ordinal before its key joins the registry. The lookup uses the envelope observer, so a record cannot certify itself and an unknown observer refuses. Genesis is always verified (`:500-505`). A key record inside the source range refuses at `:524`. |
| – | Rehearsal tick | **Stays closed** | `attest_tick_commit` and its test show no regression. |

The real-copy counts are internally consistent. Rows and facts, ticks, windows, and the 6+4478 prefix all add up: 982+3496=4478, 4357+121=4478, 39+82+0=121, 4359=4357+2, and 122=121+1. The 9 and 29 test counts match the sources. Note that `validation.json` still lists the post-correction repository run as pending.

## P2: four refusal tests hit a neighbouring branch

These tests use a bare `pytest.raises` or a loose match, which hides the miss. Deleting any of the four named checks would fail no test today.

1. **Post-S bad window** (`review:253-265`).
   - `_prepared_tick(fixture)` defaults to index 1, which is `t1`, but the chain head at S is `t2`. The row therefore refuses at the predecessor check (`verify:249`), and `window_start="f1"` is also discontinuous. The window check at `:561-564` is never reached.
   - Round 1 asked for this case explicitly.
   - Fix: use `prior = _prepared_tick(fixture, 3)` with window `"f2"`→`"f2"` and hash `"0"*64`. Match on `post-migration tick window mismatch`.
2. **Eligible row left unmapped** (`review:130-137`).
   - The manifest entry is kept, so the refusal is `manifest claims unchanged line` (`:379`), not the eligible-row check (`:384-387`).
   - A fixture with one blank row cannot reach that check, because an empty manifest refuses earlier.
   - Fix: build a source with two blank-observer rows, leave one untransformed, and remove its manifest entry. Match on `eligible line`.
3. **Reversed window** (`review:190-209`).
   - The `"f2"` parameter breaks continuity first (`:253`), so `:259-262` is never reached.
   - Fix: keep `row[7]="f1"` and set `row[8]=""`. Match on `reversed window`.
4. **Mutated or reordered prefix row** (`review:159-176`).
   - All three mutations are caught by the walk's hash and ordinal checks. Nothing reaches `prefix row mismatch` (`:523-527`), which enforces `exact-in-order`.
   - Fix: re-mint the Arrival log with one prepared row altered, and again with two rows swapped. Re-pin S each time, as `test_refuses_arbitrary_record…` does. Match on `prefix row mismatch`.

No verifier change is needed. A follow-up diff of these tests plus the final repository run is enough.

## Optional improvements

- **Tests:**
  - Add `match=` to the remaining bare raises, including the forged-key test.
  - Add forged-key cases for a record signed by the key it introduces and for an unknown envelope observer.
  - Add one valid post-S introduction as a positive control; nothing exercises that path unless the engine migration in the integration test happens to introduce a key.
  - The `"minus"` parameter value is unused.
- **Wording:**
  - The module docstring (`verify:5-6`), `plan:133` and `doc:9` still say the pins are independent; independence is a procedure the tool cannot verify.
  - The refusal at `:444` and `:460` says "migration metadata" even for post-S records.
- **Plan:**
  - At the A re-run, require the receipt's `captured_head` to equal A, and name that receipt's `arrival.sha256` as the rollback pin.
  - Record how each legacy command was disabled in the handoff receipt.
  - Show the 982 affected-row count to the approver.
- **Verifier:**
  - `prepared_window == original_window` at `:412` can never be true.
  - Two items carry over from last round. The output path is checked only after verifying, and a dangling symlink at that path is not refused. Also, the output directory is not fsynced.
- **Unchained ticks:**
  - No engine-tied test covers an unchained tick followed by a chained one; the real copy reports 0.
  - If the production snapshot reports more than 0 or refuses, surface that to the user and do not relax the rule.
