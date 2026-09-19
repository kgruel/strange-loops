**REVISE.** I found no P1 and could not construct a false pass. Five P2s remain: two in the verifier, one in its tests, two in the cutover plan. The prior rehearsal-tick P2 is closed.

This was a static review with no tests run. The `CORRECTION DIFF` section arrived empty, and no loops-copy repeat receipt was in the packet, so I assessed neither. Git status shows only untracked files, so the core deep audit is untouched.

## What holds
- **Exact mapping:** the verifier recomputes the mapping from the raw bytes with only `observer` set (`verify_legacy_provenance.py:171-192`). The JSON round-trip preserves every parsed value, so semantic preservation holds by construction.
- **Manifest:** entries must be strictly increasing, each bound to its coordinate, id and both line hashes. Any eligible row left untransformed is refused (`:371`), and unused entries are refused.
- **S pin:** the record hash at S pins the whole prefix through `prev`, and lineage is checked on every record.
- **Prefix metadata:** only the genesis and signature-verified key introductions are allowed before the source rows. Rows must then match the prepared input exactly, in order, one per record.
- **Explained windows:** an explained mismatch requires a transformed fact in the window, an original window that verifies over the same positions, and an ordinal at or before S. The Arrival counts are cross-checked against the source counts.
- **Post-S ticks:** predecessor, cursor continuity and window are all enforced, and an unchained tick is refused.
- **Resources and side effects:** memory is O(facts) and window slicing is linear once continuity applies. The walk is lock-free and nothing is written next to the inputs.

## P2: verifier

**1. An unchained historical tick is an unverified link, yet the receipt says `original_tick_chain: verified`** (`:235-241`).
- **Repro:** the original holds `f1`, then a valid chained `t1`. Next comes `t2` with `window_hash: null` and `prev_hash: "ff…"`, then a chained `t3` with `prev_hash = tick_row_hash(t2)` and `window_start = "f1"`. This passes, although `t2`'s predecessor and cursor were never checked.
- **Fix:** in the unchained branch, refuse if `self.chained > 0` or any of `row[6..8]` is non-null. Otherwise mirror `audit_deep`'s rule exactly. Count these ticks and emit `unchained_historical_ticks` (`self.chained` is currently computed but unused). If the loops copy then refuses, surface that to the user; do not relax the check.

**2. The receipt overclaims** (`:642`, `:656-666`).
- `pins_supplied_independently: True` is hard-coded, but the tool cannot know where its arguments came from. Replace it with `"pins": "caller-supplied"` and `"pin_independence_verified": false`.
- Only historical authorship and the migration report are disclaimed today. Add `ordinary_envelope_signatures_verified: false` and `inner_fact_tick_signatures_verified: false`.
- Change `original_tick_chain` to `"structurally-verified"`. Your required wording covers signatures generally, not just historical authorship.

## P2: tests

**3. Several doc-required refusals are untested, and the chain rules are only tested against themselves.**
- `test_refuses_bad_pins_…` (`tests:190`) tests only the source pin.
- `test_refuses_post_migration_window_or_future_cursor` (`:268`) only reaches the cursor refusal.
- Add one refusal test each, as a minimum, for:
  - a wrong manifest pin
  - a wrong S hash, lineage, and ordinal off by one in each direction
  - an eligible row left unmapped
  - an extra or misordered manifest entry
  - a changed signed row
  - a mutated or reordered prefix row
  - a duplicate id
  - an original cursor discontinuity and a reversed window
  - post-S: a bad window with valid cursors, an unchained tick, a bad predecessor, and a forged key introduction
  - a torn Arrival tail
  - the four inputs' hashes and the directory listing unchanged after a pass
- The test helper `_hashes` (`tests:44`) repeats the verifier's own window formula (`:260-263`), and the post-S ticks are built by hand. Nothing ties the verifier to ticks the engine actually writes. That includes `window_start` being `None` versus `""`, and what the first tick of a fresh epoch uses as its window start.
- Add one integration test: a blank-observer fixture goes through the preparer, then a fresh rehearsal with a `seal` emit, then the verifier run through the emitted tick. Any divergence today fails closed, but it would block the loops-copy repeat.

## P2: cutover plan

**4. The legacy-CLI refusal is stated as a requirement, not as something observed** (`plan:33-40`, "must fail closed"). The previous review noted that `loops store absorb` still dispatches on a migrated Arrival store.
- Add a pre-publication gate: run each listed command against the candidate copy and require a refusal with the target hash unchanged. Record that in the receipt.
- Alternatively, state plainly that refusal is unverified and that only disabling those commands protects the store. List this as a blocker next to item 3.

**5. The rollback precondition cannot be checked as written** (`plan:337-349`). The forward-only rule after the first post-A write is correct and does preserve post-cutover writes. The plan just never says how to establish that no business write has happened yet.
- Add: stop writers, capture the head, and require it to equal A in lineage, ordinal and record hash, with the store hash equal to the recorded post-adoption hash. Forbid the restore otherwise.
- Specify the restore with the same rigour as publication: live equals the candidate pin, exclusive stage, replace, directory fsync, and `LIVE_SOURCE` still equal to its pin.

## Prior rehearsal-tick P2: closed
- `attest_tick_commit` (`arrival_rehearsal.py:261-366`) requires the physical tick to equal the Commit record. It also verifies the TICK-domain signature over `tick_commitment_hash` and checks `prev_hash` against the signature-inclusive hash of the latest prior physical tick.
- An outer Arrival signature on the tick is refused, as accepted in the design.
- The test asserts every verdict and the signed-era predecessor id. Reverting `receipt_observer` would now fail at the tick-signature check.
- P3 nit: also attest whenever `emitted.tick_id` is set, not only under `--expect-tick`.

## Optional improvements
- **Verifier:**
  - Assert that the prepared row equals the original row with only field 3 replaced.
  - Read the manifest once and hash those bytes (`:271-274`).
  - Replace `chain.fact_ids.__len__()` and `fact_evidence` with the prepared chain's `changed` list (`:526-530`).
  - Check the `--output` path before verifying, refuse a dangling symlink at the unresolved path (`:689`), and fsync the directory.
  - Refuse a signed blank observer in the source, as the preparer does.
  - Close the row and walk generators on refusal.
- **Plan:**
  - Re-run provenance at A with a second receipt; the pre-adoption run verifies zero post-S ticks.
  - Add `preview_emission` with the mapped provider against `LIVE_VERTEX` after publication. `import_legacy` took the candidate path, so confirm the binding and the head journal are not keyed by that path.
  - Publication prose (`:263-266`) and code (`:287-290`) create the stage and the backup in opposite orders. A retry should accept an existing backup only if its hash equals the old hash.
  - Record the affected-row count against the rehearsal's 982 for the approver.
