**Verdict: REVISE.** No P1 found. The core ceremony holds: CAS at S, fact-ID and overlay scan, registry verification, mapped-only signing, and signature-authenticated recovery all trace correctly. Five P2 correctness gaps remain, mostly in recovery and error reporting.

## Blockers

1. **P2. Apply never independently verifies the anchor signatures; recovery does.** `libs/engine/src/engine/arrival_adoption.py:361-365` calls the builder without `fact_verify`/`arrival_verify`, and `libs/sdk/src/sdk/adopt.py:195-206` passes only the ARRIVAL verifier, used solely for the registry walk. The only check on the new signatures is `credentials.signature_verifier`, which the caller supplies (`credentials.py:268`). Recovery instead uses public verifiers at `arrival_adoption.py:654-657`.
   - Trigger: custom mapped `WriteCredentials` whose resolver returns a `sign_digest` producing junk and whose verifier returns `True`.
   - Consequence: an anchor with unverifiable FACT/ARRIVAL signatures is durably appended. If apply then fails post-append, recovery of its own intent refuses with "reserved FACT signature does not verify", so the committed anchor can never be reconciled through the API. Apply and recovery disagree on what is a valid adoption.
   - Fix: add `fact_verify` to `prepare_arrival_adoption`, pass both verifiers into `build_declaration_anchor_draft`, and use the binding's public key from session evidence rather than `valid[0]`. SDK passes `_domain_verifier(FACT_DOMAIN)` too.
   - Repro: engine test with resolver `sign_digest=lambda d: "x"` and `signature_verifier=lambda *a: True`; expect `AdoptionPreparationRefused`, currently a commit lands.

2. **P2. Reconciled-recovery failures report a pre-append phase for a known commit.** In the already-appended branch `arrival_adoption.py:726-745`, `data["phase"]` is never updated before `_finish`, and `_finish` raises `AdoptionCommittedIncomplete(phase=data["phase"])` at `:433-437`.
   - Trigger: process dies after `ledger.append` but before the `"appended"` phase write (`:502-504`), or after an `append-unknown` write. Recovery matches the record at S+1, then sync fails.
   - Consequence: error carries `commit` plus `phase="prepared"` or `"append-unknown"`, and the SDK serializes outcome `committed-incomplete` with a pre-append phase. Contradictory reconciliation evidence.
   - Fix: set `data["phase"] = "appended"` and `_replace_json` in the else branch before `_finish`.
   - Repro: run apply with a hook that `os._exit`s at `after-append` using a registry whose maintenance opener raises; recover; assert `phase == "appended"`.

3. **P2. Recovery retains a provably dead intent, blocking all future adoption.** `arrival_adoption.py:727-730` raises `AdoptionStale` when record S+1 is not the draft, and `:701-702` on CAS refusal, without removing the intent. Apply's equivalent branch removes it (`:476-478`, `:484-486`).
   - Trigger: interrupt at `after-intent`, append any ordinary record, recover.
   - Consequence: because both append paths CAS against S, the anchor can never land anywhere. Recovery raises Stale forever and every new `apply_arrival_adoption` refuses with "unfinished adoption intent exists" (`:456-457`). Only a manual file delete unblocks, with no API stating that is safe.
   - Fix: `_remove_intent` on the "absent at its expected ordinal" branch under the lock, and on pre-append `ContractRefusal`.
   - Repro: engine test extending `test_reserved_adoption_recovers_without_resigning` with an interleaved append, then prepare/apply again; expect success.

4. **P2. Malformed intent escapes the documented error family.** `_plan_from_intent` at `:521` calls `data.get` on unvalidated JSON, and `_descriptor_from` at `arrival_declarations.py:316-317` does the same. `recover_arrival_adoption:675` catches only `OSError, ValueError, KeyError, TypeError`. Also `_drafts_from_exact` raises `DeclarationApplyError` (`arrival_declarations.py:418,432`), not `AdoptionApplyError`.
   - Trigger: intent file containing `[]`, or `"descriptor": "x"`, or `drafts` edited without updating `exact_drafts`. The tampering tests deliberately keep both consistent (`test_arrival_adoption.py:194-203`), so this branch is untested.
   - Consequence: raw `AttributeError` propagates through the SDK unchanged (`errors.py:445,537`), or a declaration-editing error type leaks from adoption; engine callers catching `AdoptionApplyError` miss it.
   - Fix: `isinstance(data, dict)` and mapping checks in `_plan_from_intent`; catch `AttributeError` and `DeclarationApplyError` in the read block and rewrap.
   - Repro: write `[]` to the intent path, call `recover_arrival_adoption`, expect `AdoptionApplyError`.

5. **P2. A backend without projection maintenance always ends in an unrecoverable committed-incomplete.** Prepare checks `max_atomic_records` (`:337-338`) but not maintenance support; `_finish` calls `sync_projection` which raises `NotSupported` via `arrival_registry.py:438-443` after the append is durable.
   - Trigger: `registry.register("custom", opener)` with no `maintenance_opener`, role authority, then adopt.
   - Consequence: durable anchor, intent retained, and recovery hits the same `NotSupported` every time. Contradicts the backend-neutral claim.
   - Fix: probe `registry._maintenance_for(descriptor).capabilities().catch_up` in prepare and refuse before signing.
   - Repro: engine test with a custom registry lacking maintenance; expect `AdoptionPreparationRefused`.

## Optional suggestions

- `ArrivalAdoptionResult.basis` reports `captured_head=S` and `projected_through=None` after a successful sync through A (`:372`, `:407`). Reporting A and the projected head would match what reads then return.
- In the reconciled branch, a Full-verification failure of a present, matched anchor is reported as `AdoptionStale` (`:734-735`), which the SDK maps to outcome `refused`. `CommittedIncomplete` fits better.
- Coverage gaps: `AdoptionOutcomeUnknown` and `AdoptionUnwitnessed` classification, apply-time `_require_cache` drift after prepare, post-sync cache drift, recovery with later appends and `observed_head`, projection already ahead. The `after-append` hook tests are seam evidence for the `_replace_json` failure branch, not proof.
- `test_recovery_does_not_resolve_or_resign_credentials` in the SDK suite proves only that two callables are forwarded to a fake. The real evidence is the integration test's monkeypatched provider.
- `edit_declaration` and adoption use separate intent files with no cross-check, so a declaration edit can rewrite the cache while an adoption intent is still pending, leaving that intent permanently at cache mismatch.

## Unresolved questions

- The intent's binding of the draft to S is unauthenticated: signatures cover content, not coordinate. An edited `captured_head` naming a later legitimate head with an unchanged tip causes recovery to append the draft at S'+1 after all S' checks pass. Whether that is in the threat model needs a decision.
- Does `vertex_to_documents` include the vertex name? If not, reviewed and published may differ in name and still pass.
- Do readers or the projection verify `_decl.genesis` signatures? That decides the downstream blast radius of finding 1.

## Missing source context

`vertex_to_documents`, `rows_of_body`, `MappedCredentialProvider.resolve` and its no-create claim, the file backend's append and maintenance provider, and the diff removing the old `_draft` from initialization. Error-family preservation for existing initializer callers could not be confirmed.
