# recovery — Fable review

Effort: low. Finished: 2026-09-06T23:41:14.467144+00:00.
Packet SHA-256: `4e83e937df0897cd03bc4b97b2d68b9ac0a315bcea721706ad0abfbc89e77a59`.

Static reviewer output; findings still require primary triage.

**Verdict: REVISE** (one remaining blocker, narrow; the two root counterexamples are fixed as written).

## Confirmed fixed

- **Substituted published slot, same token.** Both `create_binding` and `recover_binding` reach `_assert_published_intent(..., require_token_index=False)` before any index publication or return, and the retained pending slot names Alice's original key_ref, so key_ref mismatch refuses (`binding.py:571-573`, `binding.py:861-863`). This holds in the combined case (index deleted plus slot substituted): the pending marker is the comparison source, the index check is deferred, so no index is restored and the slot is untouched. Matches the test assertions at `test_binding.py:194-201`.
- **Pending-before-index interruption.** `_pending_by_token` scans pending slots under the lock; a conflicting observer with the same token refuses at `binding.py:559-563` before any pending, key, or binding publication. After create retry or recovery, `_ensure_token_index` restores the index from the matching pending record and the index-based check at `binding.py:550-554` refuses. Create retry and recovery are symmetric here.
- **Contradictory index or completion** refuses via `_ensure_token_index` no-clobber comparison and the completion comparison in `_assert_published_intent`. Missing completion after a valid, intent-matching slot is treated as a crash window and completed. Correct distinction.
- **Luna's partial repair** (index restored, then candidate refused) is consistent with the README statement; the index content equals the already durable pending reservation, so it asserts nothing new.

## Remaining blocker

**Completed slot returned to a fresh token without comparing the slot's retained pending marker.** In `_intent_for`, when `completed is not None` and the caller's token has no pending record and no index, the code returns the published slot at `binding.py:589-595` without ever reading the slot's own pending file. The slot pending read at `binding.py:596-603` runs only when no completed binding exists.

Counterexample (same setup as `published_intent_probe.py`, one line changed):

```python
provider.create_binding('alice', token='alice-token')   # refuses, correct
provider.create_binding('alice', token='fresh-token')   # returns Bob's key_ref/public under Alice
```

Trace: `token_record` is None, `pending_for_token` is None, `completed` validates (Bob's material is self-consistent), none of the conditions at `binding.py:577-587` fire, so it returns `completed`. Yet `pending-v1/<alice slot>.json` and `intents-v1/<alice-token>.complete.json` both name Alice's original key_ref. This is contradictory content silently selected, not a conservatively reported incomplete. Fresh-token retry against a completed slot is an expected call shape (the recovery contract test at `test_binding_recovery_contract.py:45-54` uses exactly that pattern), so this is a real path, not a misuse.

Fix within stated scope: in the completed branch, always read the slot's pending marker (by slot, not by token). If present, run `_assert_published_intent(completed, slot_pending, require_token_index=False)`, then if that pending's index exists compare it too, and compare its completion receipt if present. Only skip when no slot pending exists at all (legitimate pre-intent or externally imported record). No new file writes are needed for this check.

## Notes (non-blocking)

- **Created-provenance intents pin no public material.** `expected_public_key` is None for `created`, and the completion receipt is the intent verbatim, so no retained evidence records the actual published public key. Replacing the key directory under Alice's key_ref with other valid material passes `_validated_binding` and every intent comparison. This is key-store tampering rather than slot substitution and changes the stored completion shape if fixed, so out of this follow-up's scope. Worth a tracked item.
- **`TypeError` from `_read_json` and `_pending_by_token`** is not in the re-raise allowlist at `binding.py:929-931`, so a non-object JSON record inside the recovery try becomes `BindingMutationIncomplete` rather than a typed evidence error. Conservative, not a false completion. Consider adding `TypeError` to the allowlist. Note `_pending_for_recovery` runs outside the try, so the same error there propagates raw, which is inconsistent.
- **`_intent_for` recursion on pending no-clobber loss** (`binding.py:639-645`) is bounded in practice under the lock but has no depth guard. Pre-existing, fine.
- The README sentence on partial index restoration is accurate and appropriately scoped.
