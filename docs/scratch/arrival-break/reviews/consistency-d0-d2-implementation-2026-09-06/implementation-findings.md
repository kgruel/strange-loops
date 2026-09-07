# implementation — Fable review

Effort: low. Finished: 2026-09-06T23:29:25.786164+00:00.
Packet SHA-256: `1edcdb938b9676779eefc3b9b6246ca50e4e7565cd76f619e2ca56a8c7aaaa05`.

Static reviewer output; findings still require primary triage.

**Verdict: ACCEPT**

No correctness blocker found in the final code against the amended design and triage requirements. The areas listed for focus check out as follows.

**Binding-vs-intent consistency.** `_intent_for` (binding.py) checks the token index before the slot, refuses a token that names another namespace/observer before any effect, and treats a published slot as authority. A completed slot with a retained token record that disagrees on provenance or key_ref conflicts rather than returning. `recover_binding` validates the published slot (including private-derived public) before it consults the pending marker, so a missing key under a published ref raises without regeneration. Counterexample probes for reused tokens, replacement keys, and stale candidates are covered by the recovery contract tests and match the code paths.

**Interrupted publication.** Intent, key, and binding each publish via complete temp plus no-clobber link with parent fsync. Pending marker is published before the token index, so a crash between them leaves a recoverable slot-indexed intent. Private-before-public interruption is resumable in both `_ensure_created_key` (created) and `recover_binding` (legacy-import). The `BindingMutationIncomplete` phase labels match the actual step reached.

**No replacement of published keys.** Every path that could mint reaches `ed25519.load_or_generate` only when the private file is absent under an intent-reserved ref that no published binding names. `resolve`, `_load_keypair`, and `_validated_binding` never create or repair.

**Cross-domain/ref/public coherence.** Provider returns one record for all domains; `CredentialResolutionSession.sign` refuses request mismatch, malformed evidence, unauthorized public key, and differing bindings across domains within one operation, then independently verifies each signature under its domain. Initialization checks FACT/ARRIVAL evidence equality on both public key and key_ref.

**Source recapture.** `execute_source_invocation` passes credentials to each tier's `capture_runtime`; each `plan_batch_from_capture` uses a fresh session bound to that capture's context. Preflight plans against the initial capture.

**No-fallback guards.** `WriteCredentials.__post_init__` enforces all-or-none and excludes legacy callbacks. `_author_signature`/`_tick_signature` branch solely on `mapped`. `handle.py` and `ceremony.py` refuse mapped before catch-up or intent. SDK legacy arms call `_refuse_legacy_mapped_credentials` at entry, and `grant_observer(key=None)` classifies mapped before `ensure_signing_key`.

**Honest error evidence.** `CredentialBindingRefused` retains reason, request, captured head, use position, and sanitized evidence; the provider-failure path preserves `__cause__` identity. Batch wraps it in `BatchWritePreparationRefused` with `admission_refused=False`. `_credential_binding_details` sanitizes non-string fields.

**Old init recovery.** `recover_arrival_initialization` is unchanged and signs nothing; the SDK recover branch never touches the provider.

**Receipt omission / self-introduction.** `_tick_signature` constructs no TICK request without a receipt observer and refuses only in a signed era. `_key_draft` authorizes only with keys valid at H+1 for the introducing author, so K1 may introduce K2 for the same observer and K2 cannot self-authorize.

**Notes (non-blocking):**

- `_copy_key` else-branch overwrites `source_pair` with the candidate, so its final comparison is trivially true. Source mismatch on a re-presented import is still caught earlier by `expected_public_key` in `_intent_for`, so no exposure, but the check is dead code.
- A configured `receipt_observer` whose key is not in the effective declaration's receipt set refuses even in the pre-signed era rather than producing an unsigned tick. This matches the design's "never downgrade a contradictory binding" rule but differs from legacy `tick_signer_for`, which signs regardless of declaration. Worth a README sentence.
- `_completed_key_reference` scans all binding files and raises on any malformed unrelated record, so one corrupt slot blocks every `bind_existing_ref` in the root. Acceptable as fail-closed; document it.
- Pending markers are retained after completion with `stage: pending`. Harmless because published slots take precedence, but a future maintenance operation must not interpret them as unfinished work.
- `init_vertex(recover=True, credentials=...)` silently ignores the provider. Consistent with "recovery signs nothing," but an explicit note or refusal would avoid a caller assuming drift was checked.
- Retrying `import_legacy` with the same token after a private-before-public interruption raises `BindingMutationIncomplete` again; only `recover_binding` resumes it. README already directs callers to recovery, so this is a documented limitation.
