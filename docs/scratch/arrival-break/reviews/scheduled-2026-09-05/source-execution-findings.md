# source-execution — Fable review

Effort: low. Finished: 2026-09-06T02:51:58.650284+00:00.
Packet SHA-256: `10c8b541f14dd93d690c63cf42a82c5bd0714ea554f3cd47427f142b5154b0bc`.

Static reviewer output; findings still require primary triage.

**Verdict: no blocking findings.** The implemented tier-atomic flow matches the stated design on the reviewed points: qualification and tiers are frozen before collection, each tier plans against the capture it was collected under and CASes on that exact head, yielded facts survive a `SourceError`, invalid output and admission refusals refuse the whole tier before any append, and the unknown-append path is labeled unknown rather than uncommitted. The five items below are non-blocking.

**1. Medium — unguarded code after the collector `try` in `_collect_one` can abort the whole invocation.**
Location: `libs/engine/src/engine/arrival_sources.py`, `_collect_one`, the payload and `CollectedSource` construction after the `try/except`.
Trigger: `source.command`, `source.observer`, `source.kind` or `clock()` raising for one source. The module itself anticipates sources without `.observer` (`_source_observers` uses `getattr(source, "observer", "")` and recurses into `.sources`), yet `_collect_one` reads `source.observer` and `source.command` unconditionally.
Consequence: the exception escapes `asyncio.gather`, `collect_source_tier` and `execute_source_invocation`, so the caller gets no `SourceInvocationResult`. Every other collector in the tier has already run externally and its retained output, error evidence and lifecycle facts are lost, and earlier durable tier receipts are not reported. This defeats the "retain collection on failure" guarantee for that class of fault. Preflight partially mitigates this because it also reads `.kind` and `.command` and would wrap the error in `SourcePreparationRefused`, but `.observer` is not touched there.

**2. Medium — in-tier source-list order is not enforced in this module.**
Location: `prepare_source_invocation`, `tiers = tuple(tuple(tier) for tier in _toposort_tiers(set(qualifying), deps))`.
Trigger: `_toposort_tiers` is not in the snapshot. If it yields sets or set-derived lists, `tuple(tier)` preserves set iteration order. For ints that is deterministic but not ascending once indices exceed the hash-table width (for example, indices 1 and 8 iterate as 8, 1).
Consequence: batch record order, lifecycle order and the "deterministic source-list ordering" claim depend on an external helper's iteration order. The existing test covers only two sources. Sorting each tier locally would make the claim hold by construction regardless of the helper.

**3. Low — a fully-already-present tier yields a `None` commit that `TierCommitted.commit` asserts against.**
Location: `execute_batch_write` returns `CommittedBatchWrite(None, ...)` when `plan.drafts` is empty; `TierCommitted.commit` does `assert self.outcome.commit is not None`.
Trigger: re-preparing a retained `CollectedTier` whose lifecycle ids and fixed lifecycle timestamps already landed (for example, operator reconciliation after `BatchWriteCommitUnknown` re-running the same tier). Every item is then `already_present`, drafts are empty, and the tier is recorded as durable with no commit.
Consequence: `dispatcher(committed.commit, intents)` raises `AssertionError`, which is caught and then re-raised from inside `DispatchFailed.__init__` through the same property, escaping the coroutine. Not reachable in the first-pass flow; reachable through the reconciliation path this stage explicitly invites.

**4. Low — dispatch is skipped on two durable outcomes.**
Location: `execute_source_invocation`, the `NotWitnessed` and `BatchPostCommitProjectionFailed` branches return before the dispatcher block.
Trigger: run-clause ticks in a tier whose append committed but whose journal write or projection catch-up failed.
Consequence: custody holds a tick with a run clause that is never dispatched; the result records `dispatch_succeeded=None` with intents retained. The design says dispatch happens "once only after run-clause ticks appear in a durable tier Commit", while the stage note says "after a successful witnessed tier outcome". The code implements the narrower rule. Acceptable if intended, but the two documents disagree and consumers reconciling a `NotWitnessed` result need to know dispatch is theirs to perform.

**5. Low (design, not a bug) — tier-0 has no re-plan path for independent appends.**
Location: `execute_source_invocation`, tier 0 uses `invocation.initial_capture` for planning; `execute_batch_write` refuses on `comparison.presented != plan.captured_head`.
Trigger: any ordinary SDK emission between `prepare_source_invocation` and the tier-0 append. Collection has no custody dependence, so the window spans the full external collector runtime.
Consequence: collectors run their external commands, then the tier is refused as `RuntimeWriteRefused` and dropped. Because no `_sync.<kind>` success lands, elapsed cadence re-qualifies the source on the next invocation, so the practical effect is a re-run of external effects at the scheduler's cadence rather than true "no retry". Re-planning collected output against a fresh capture (with the same declaration-equality check used between tiers) would remove most of this loss without re-collecting. This is a liveness trade-off the design accepts; flagging it because the current test suite pins the refusal but nothing measures the drop rate on a live store.

**Deferred and out of scope, not counted as defects:** the unused `locator` parameter on `execute_source_invocation` (the frozen ingress copy is used instead, which is correct); later-tier captures omitting `source_mode=True` (harmless since pending boundaries are tier-0 only); the `_interval is None` `TypeError` in elapsed cadence escaping unwrapped (depends on the cadence type, not in snapshot); legacy `Executor` cutover and empty-receiver import.
