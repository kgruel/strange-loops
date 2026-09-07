# final — Fable review

Effort: low. Finished: 2026-09-06T23:45:12.732976+00:00.
Packet SHA-256: `f5ed9983fcf7f4f733dc4fde403419d62da4943ff007dc6caf6c2dcc7ee8bb85`.

Static reviewer output; findings still require primary triage.

**Verdict: ACCEPT.** No remaining correctness blockers in the completed-slot path.

**Trace of the four required scenarios** (fixture: alice bound under `alice-token`, bob under `bob-token`, alice's binding slot rewritten to bob's key_ref/public_key, alice's pending marker retained):

- **Fresh-token create.** In `_intent_for` (`libs/custody/src/custody/binding.py:542`), `token_record` and `pending_for_token` are both None for `fresh-token`. `slot_pending` is read from the slot path independently of the token (line 565). `_validated_binding` accepts the substituted slot because bob's key really matches. Line 578 then runs `_assert_published_intent(completed, slot_pending, require_token_index=False)`, and `key_ref` mismatch raises `BindingConflict("...contradicts its retained intent")`. Nothing has been written; only `_subdir(..., create=False)` reads precede it.
- **Original-token create.** `pending_for_token` is alice's marker, equal to `slot_pending`. The slot check at line 578 fires before the `pending_for_token` branch at line 590, so `_ensure_token_index` and `_publish_completion` are never reached. Refusal is write-free.
- **Original-token recover.** `_pending_for_recovery` validates the marker and its `_pending_by_token` uniqueness. `_binding_record` is non-None, `_validated_binding` passes, and `_assert_published_intent(published, intent, require_token_index=False)` at line 878 refuses before `_ensure_token_index` at 883. `BindingConflict` is re-raised unchanged by the except clause at line 946.
- **Missing original index plus substituted slot.** `test_recovery_refuses_published_slot_substituted_with_another_valid_key` unlinks the index first. All three calls refuse at the `require_token_index=False` check, which does not consult the index, so absence of the index cannot suppress the retained-marker contradiction. The test's `not index.exists()` assertion is justified by the ordering above. The `indexed_slot is not None` guard at line 588 only strengthens the check when the index exists; it never relaxes it.

**Earlier interruption fixes still hold.**

- Pending-before-index interruption (both test files): after `Interrupted` during intents-v1 publication, the marker exists alone. Create with the same token finds `pending_for_token == slot_pending`, no completed record, token matches, restores the index via `_ensure_token_index`, and proceeds. Recover takes the `published is None` path and does the same. A later `create_binding("bob", token="one-token")` refuses at line 559 (marker owns another slot) or line 550 (index names another slot), read-only in both orders. This matches the documented "explicit recovery may repair a missing index before a later refusal."
- Intent-published hook interruption: marker and index exist; `token-two` hits `BindingRecoveryRequired` at line 624 before any write; `token-one` recover completes.
- Public-evidence contradiction on completed retry: `_validated_binding` raises `ValueError` from `_intent_for`, which sits outside the `_mutate` try block, so it surfaces as `ValueError` with no `BindingMutationIncomplete` wrapping and no writes.
- Recovery never regenerates a key named by a published binding: `_validated_binding` at line 877 raises `FileNotFoundError` before `_ensure_created_key`.

**Scope confirmation.** The patch touches only `_intent_for`'s completed branch and tests; no engine or SDK production source appears in this packet. The fresh-token path does not restore the original index, consistent with the handoff. Simultaneous replacement of private material plus every local marker/index/receipt remains outside this slice, as agreed; the README and triage already say Arrival writes check captured key history separately.

**Optional notes, not blockers.**

- `test_recovery_refuses_valid_key_that_contradicts_its_original_intent` asserts `pytest.raises(ValueError)`; `BindingConflict` subclasses `ValueError`, so it passes, but a `match="retained intent"` would pin the specific refusal as `test_binding.py` does.
- A completed slot whose pending marker is entirely absent skips the retained-intent check. That is the documented boundary, not a regression, but worth a README sentence if this path is ever hardened.
- `_mutation_lock` creates the lock file on first use; fingerprint-based tests rely on it already existing from the initial create. Fine today, fragile if a test ever fingerprints before any mutation.
