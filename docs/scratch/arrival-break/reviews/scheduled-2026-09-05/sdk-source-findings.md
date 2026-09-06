# sdk-source — Fable review

Effort: low. Finished: 2026-09-06T02:54:03.413066+00:00.
Packet SHA-256: `428898fde1345cd6f2557cf748c0f45aa1315dc289b7ab2b9acccddadd3cdf57`.

Static reviewer output; findings still require primary triage.

**Verdict: no blocking findings.** The implemented behavior matches the stated design on the four outcome families, zero implicit dispatcher, and absence of exactly-once delivery claims. Five non-blocking findings follow, ordered by severity. None concern deferred legacy cutover or empty-receiver import.

**1. Medium: terminal category and tier outcome disagree for `NotWitnessed` without a commit.**
Location: `engine/arrival_sources.py` `execute_source_invocation`, `except NotWitnessed` branch; `sdk/sources.py` `_terminal_result` and `_tier_result`.
Trigger: the head seam raises `NotWitnessed` with `commit is None` during `ledger.append`.
Consequence: the engine files the tier as `collected_uncommitted`, so the SDK tier outcome is `uncommitted` and `known_uncommitted` is populated. The SDK terminal category for the same event is `unwitnessed`, not `refused` or `failed`. `execute_batch_write`'s docstring states `NotWitnessed` "already carries the durable commit", so a commit-less instance is outside the documented contract, yet the code treats it as proof of no append. If the seam can raise it after the append reached the backend, "known uncommitted" invites an unsafe rerun. Either refuse the commit-less form as unknown, or document that the seam guarantees no append occurred when `commit` is None.

**2. Low: execution-time refusals collapse to category `failed`.**
Location: `sdk/sources.py` `_terminal_result`; generic `except Exception` in `execute_source_invocation` after `execute_batch_write`.
Trigger: a stale head CAS (`RuntimeWriteRefused("captured head changed before batch append")`) or any `ContractRefusal` propagated from `ledger.append`.
Consequence: preparation refusals get `refused`, `admission-refused`, or `invalid-output`, but the most common safe-to-rerun execution refusal is reported as `failed` with only `source_type` distinguishing it. `normalize_exception` already classifies these types for raised errors, so the two taxonomies diverge for the same engine exception. Operators must inspect type names rather than the category the result is designed around.

**3. Low: dispatch attempt evidence is tier-granular, presented per intent.**
Location: `sdk/sources.py` `_dispatch_result`; `execute_source_invocation` dispatcher call.
Trigger: a dispatcher receives several intents, runs some commands, then raises.
Consequence: every `SourceDispatchResult` reports `attempted=True, succeeded=False`, including intents whose command never started. The design correctly makes no delivery guarantee, and `DispatchFailed` keeps the commit, but the result cannot say which run clauses executed. Consider documenting that `attempted` and `succeeded` are copies of the tier-level outcome, or accept a per-intent receipt from the dispatcher.

**4. Low: SDK tests do not exercise several mapped paths.**
Location: `sdk/tests/test_arrival_sources.py`.
Untested at the SDK layer: a durable earlier tier followed by a later-tier failure (the design's central "tiers 0 and 1 durable, tier 2 fails" case), the `declaration-changed` terminal with `initial_basis`/`observed_basis` detail serialization, `dispatch_status="withheld"` (dispatcher supplied, tier unwitnessed or projection-failed), and the no-qualifying-source lifecycle-only commit with a pending boundary. `_unplanned_fact_ids` last-index logic and `_committed_outcome` branch order are only reached through these paths. Engine coverage may exist, but the SDK mapping is the deliverable under review.

**5. Low: preparation error mapping loses type and head evidence.**
Location: `sdk/sources.py` `_raise_preparation`; `run_sources` `except SourcePreparationRefused`.
Trigger: empty `observer` raises a bare `ValueError` in `prepare_source_invocation`, or admission is refused during preflight.
Consequence: the `ValueError` becomes `ArrivalRefusal(source_type="ValueError")` rather than `SdkValueError`, unlike the emit path's `InvalidEmissionRequest`. For preflight admission refusals, `exc.cause` is passed and the wrapper's `capture.basis` is dropped, so the raised error lacks the captured head unless the cause itself carries one. `details["phase"]` is only set on the fallback branch, not on normalized errors.

**Confirmed as implemented correctly:** `dispatcher` defaults to `None` with intents exposed as `not-requested`; `BatchWriteCommitUnknown` is never filed as uncommitted and retains all planned identities; unwitnessed and projection-failed tiers retain the actual commit; `SourceRunResult` carries no `RuntimeCapture`, drafts, or record bodies; payload serialization avoids `default=str`; later tiers recapture and refuse on declaration document change; pending boundaries are planned once at the initial capture and appended only in tier 0.
