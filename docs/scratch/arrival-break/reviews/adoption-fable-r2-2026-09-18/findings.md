**Verdict: REVISE.** One narrow P2 remains, the unfinished half of F5. No P1 found. F1–F4 are resolved in source. This is a static review only; I ran nothing.

## Prior findings

1. **F1: resolved.**
   - `arrival_adoption.py:391-410` verifies FACT and ARRIVAL against `bindings[0].public_key`, the key the session actually resolved, not `valid[0]`.
   - FACT-then-ARRIVAL order is guaranteed by the builder's call order and checked at `:383-390`.
   - The digests match the builder's and those in `_revalidate_reserved`, so apply and recovery now agree on validity.
   - A refusal leaves no intent and no append.
   - Initializer behavior: `public_key` is always passed, so `arrival_initialization.py:299-315` behaves as before. A verifier supplied without a key fails closed.
2. **F2: resolved.**
   - `:844-852` sets and persists `appended` before `_finish`.
   - Both the save-failure and sync-failure paths carry Commit(S,A) with phase `appended`.
   - Side effect: an intent already at `synced` or `published` is rewritten to `appended` on re-recovery. This is harmless, because `_finish` is idempotent.
3. **F3: resolved.**
   - Retirement at `:828-833` happens only after four checks pass:
     - `head_at(S)` equals the captured head.
     - `_revalidate_reserved` passes.
     - Full(S+1) verifies.
     - The record at S+1 does not match the reserved draft.
   - The proof is sound because both append sites compare-and-swap (CAS) against S.
   - CAS refusal, open failure and verification failure all retain the intent.
4. **F4: resolved.**
   - `_plan_from_intent` validates shapes and wraps all helper exceptions as `AdoptionApplyError` (`:644-647`).
   - An unhashable `phase` raises `TypeError` before the `try`, and `:768` catches it.
   - Cosmetic: the wrapped message still says "declaration intent draft bytes".
5. **F5: resolved for prepare, incomplete overall.**
   - The preflight at `:352-357` runs before the credential session is created.
   - It is attested and makes no `catch_up` or snapshot call.
   - Handles close on every path (`arrival_maintenance.py:200-202`, `:223-227`).
   - The gap is the new blocker below.

## Blocker

**P2 (narrow): recovery's append path has no maintenance preflight.**
- **Location:** `libs/engine/src/engine/arrival_adoption.py:787-790`. The `current == predecessor` branch runs `_require_cache`, then `ledger.append`.
- **Trigger:**
  - An intent is reserved before any append: `after-intent`, `AdoptionRecoveryRequired`, or a retained stale or CAS refusal whose head is still S.
  - `recover_arrival_adoption(intent, registry=R)` is then called, where R opens the backend but registers no maintenance opener, or one without `catch_up`.
  - This is reachable through the public SDK `registry=` parameter. Recovery is a separate process, so a differently built registry is plausible. R is the same registry primary used for the original F5 reproduction.
- **Consequence:**
  - Recovery durably appends the anchor.
  - `_finish` then raises `AdoptionCommittedIncomplete` caused by `NotSupported`.
  - That is the state F5 exists to prevent, and it breaks "absent capabilities known before append must refuse".
  - It is recoverable once a proper registry is supplied, as before.
- **Minimum correction:**
  - In that branch, call `preflight_projection_maintenance(registry, plan.descriptor, through=predecessor)` before `ledger.append`.
  - On failure, raise a pre-append `AdoptionApplyError`, retain the intent and append nothing. This needs no private registry access.
  - Optionally add the same call before `:523` in apply, which accepts a registry independent of the one prepare checked.
- **Reproduction sketch:**
  - Use `_fixture`, prepare with the builtin registry, then `_reserve`.
  - Build `bad = BackendRegistry()` and register `"file"` with `_open_file_backend` and `binding_provider=_file_binding`, omitting the maintenance opener.
  - Call `recover_arrival_adoption(bad, intent, **_recovery_kwargs())`.
  - Expect a refusal that is not `CommittedIncomplete`, `_record_count == 1`, and the intent still present. Today the count is 2 and the error is committed-incomplete.
  - Then recover with the builtin registry and expect success with count 2.

## Optional suggestions

- **Retirement uses a plan parsed outside the lock.**
  - The intent is read at `:765-767` before the lock at `:774`. `_remove_intent` at `:829` then deletes by path.
  - Race: R2 parses the old intent, R1 retires it, a fresh adoption at S' leaves a new intent at the same path, and R2 deletes the new intent.
  - If the new intent was post-append, the adoption-recovery API can no longer reconcile that commit.
  - Fix: re-read the intent under the lock and require identical bytes before `_replace_json` or `_remove_intent`.
  - I left it optional because the window is narrow, it needs three concurrent actors, and no live coordinator is claimed.
- **Apply's pre-append stale-head branch (`:517-521`) retains an intent it provably need not.**
  - That call created the intent exclusively, holds the lock, and never entered append.
  - `AdoptionStale` also carries no `intent_path`, so the SDK refusal has no recovery coordinate.
  - `ADOPTION.md` does not say that a stale `adopt_arrival` leaves a blocking intent.
  - At minimum add `intent_path` and a doc sentence. Removing the intent in this one branch is a proof, not the blind cleanup triage warned against.
- **Transient failures in recovery escape both error families.**
  - A `registry.open` failure in recovery escapes as raw `OSError` through the SDK, and the new test pins this. Apply wraps the same fault as `AdoptionRecoveryRequired`.
  - Raw `HeadMismatch` from `verify` at `:825` also escapes the engine adoption family.
- **Still open from round 1, not promoted:**
  - Result `basis` still reports S and `None` after a successful sync.
  - A Full-verification failure of a matched anchor still maps to `AdoptionStale`.
  - Cross-ceremony intents are still not cross-checked.

## Questions

- **Do source documents hash files on disk?**
  - `vertex_to_documents` embeds `content_sha256` for `sources` path and template entries (`document.py:786-792`).
  - `_revalidate_reserved` re-derives documents at `:673-675` and runs before the S+1 check.
  - If `_content_sha256` reads disk, editing a referenced source file between prepare and recovery makes every recovery refuse with "anchor differs from reviewed documents". That includes recovery of an already-committed anchor.
  - It would also mean `reviewed_sha256` pins file content only as of adoption time.
  - To check: read `_content_sha256`, then test a post-append interrupt, a source edit, and recover.
- **Is every `ContractRefusal` from `AttestedLedger` or `_DescriptorLedger.append` strictly pre-commit?** Apply and recovery report it as `refused`.
- **Are intents with persistent pre-commit refusals stuck by design?**
  - A non-head `ContractRefusal`, or an `AppendRejected` classified as unknown, has no retirement path until something else occupies S+1.
  - I found no reachable trigger.

## Missing context

- The pre-change diffs of `arrival_maintenance.py` and `arrival_initialization.py`. Two things cannot be confirmed without them:
  - Whether the `rebuild=True` `TypeError` and the maintenance-before-already-current ordering in `sync_projection` are new.
  - Whether the old `_draft` error types match.
- `_DescriptorLedger`.
- `_content_sha256` and the source payload helpers.
- `custody.binding._domain_prefix`.
- The `ArrivalError` base class.
- `AttestedLedger._observe` journaling on open, needed to check the preflight's "nonmutating" claim against the witness journal.
- `ArrivalLog.append_marked_many` refusal families.
