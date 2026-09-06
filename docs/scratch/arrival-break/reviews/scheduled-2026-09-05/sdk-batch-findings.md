# sdk-batch — Fable review

Effort: low. Finished: 2026-09-06T02:55:45.341596+00:00.
Packet SHA-256: `da1a4408ec9cbbd4f5ac4b29ac8e1314ba1a2185856726c0006c4ab07947e4f6`.

Static reviewer output; findings still require primary triage.

No blocking findings. The batch path prepares everything from one capture, performs one full-head CAS append, keeps exact planned identities on unknown/unwitnessed/postcommit failures, and makes exactly one execute attempt. Findings below are non-blocking.

**1. Low — signature-inclusive idempotence makes credential changes look like content conflicts.**
Location: `libs/engine/src/engine/runtime_write.py`, `_existing_fact_plan` (tuple compare including `existing.signature` vs freshly computed `inner_signature`).
Trigger: a caller retries an `id_override`/dict `id` item after the observer's fact key was rotated, after keys were first created, or with `_UnsignedCredentials` where the stored row was signed (or vice versa).
Consequence: the retry is refused as `fact id ... already exists with different content` (ArrivalRefusal) even though kind/ts/observer/origin/payload are identical. Both `emit_batch` and `preview_emission` inherit this, so the SDK's "equal duplicate is an explicit no-op" claim is conditional on identical signer output. Not a safety bug (nothing appends), but the refusal message misattributes the cause; consider naming the signature axis in the message or documenting the constraint.

**2. Low — within-batch duplicate item receipts report `signed=True` while `stored=False`.**
Location: `libs/sdk/src/sdk/emit.py`, `emit_batch` Arrival receipts; `signed_by_id` is keyed by fact id and populated from the packed drafts.
Trigger: a batch containing the same new id twice with equal content (the `["existing","new","new"]` shape covered by `test_arrival_batch_equal_duplicates_are_explicit_item_noops`).
Consequence: the second `new` receipt says `stored=False, witnessed=None, projection="not-requested"` but `signed=True`, which is the first item's signing evidence. Pre-existing duplicates correctly get `signed=None`. Cosmetic inconsistency in the receipt; fix would be `signed=None if item_result.already_present else signed_by_id.get(...)`.

**3. Low — empty batch on a non-authority descriptor refuses instead of returning `empty-noop`.**
Location: `libs/sdk/src/sdk/emit.py`, `emit_batch`: the `Profile.AUTHORITY` check runs before the `if not prepared_items` return.
Trigger: `emit_batch(replica_vertex, [])`.
Consequence: `ArrivalRefusal(NotAuthority)` for an operation that would never open a ledger. The stage doc says empty input "never opens a store"; that still holds, but the single-fact path (`emit_fact`) only discovers role at capture time, so the two operations disagree only on this zero-item edge. Either order is defensible; noting it so the behavior is deliberate rather than accidental.

**4. Low — packed batch envelope `authored_at` is the first row's ts, not a batch-level time.**
Location: `libs/engine/src/engine/runtime_write.py`, `_pack_batch_drafts` (`authored_at=first.authored_at`, origin/observer likewise from `first`).
Trigger: same-observer items whose ts values are non-monotonic in input order (e.g. `ts=4.0` then `ts=3.0`); mixed origins in one same-observer group.
Consequence: the outer `at`/`origin` of the wire `batch` record reflects only the first row; later rows' origins are only inside `rows`. `content_commitment("batch", ...)` still covers the full body, so custody and authorship verification are unaffected. Worth a one-line doc note in the design since operators may read `at`/`origin` off the envelope.

**Verified as correct (for the record):** per-item admission uses the snapshot-effective declaration and per-observer grant; a later refusal raises `BatchWritePreparationRefused` before any ledger open for append; `execute_batch_write` re-compares the open-time head and then relies on the ledger's own full-head CAS; `AtomicLimitExceeded` is a `ContractRefusal` and is re-raised rather than wrapped as unknown; the all-duplicate plan short-circuits without opening, while the preceding `capture_runtime` open already performed the rollback/attestation comparison, so ordinary opens keep their checks; `BatchWriteCommitUnknown`, `NotWitnessed`, and `BatchPostCommitProjectionFailed` all carry `captured_head`, ordered items, and plural fact/tick ids through `normalize_exception`; synthetic ordinals in `plan_batch_from_capture` differ from post-pack real ordinals but preserve order, which is all `_window_hash` and `_current_tick_context` depend on; `WriteCredentials` has no cross-domain fallback and the batch envelope uses only `arrival_signer`.

**Out of scope / not findings:** legacy `emit_batch` remains sequential and non-atomic by design (explicit `LegacyBatchPartialFailure`); final legacy cutover and empty-receiver import are deferred stages, not defects here.
