# Arrival source execution stage — 2026-09-05

Status: implementation and local verification complete; Fable review queued for the reported 21:20 CDT quota reset.

## Result

`engine.arrival_sources` provides a captured, tier-atomic source coordinator for one Arrival Authority. `prepare_source_invocation` first earns registry Authority access and a CURRENT runtime capture, freezes cadence evidence and source dependency tiers, assigns stable invocation/lifecycle identities, and preflights the explicit lifecycle observer, declared source observers, known lifecycle facts, and any pending signed-era boundaries before external collection begins.

Each dependency tier collects concurrently while retaining source-list order. Yielded facts survive a later `SourceError`; an invalid object, admission refusal, or packed atomic-limit refusal prevents the entire tier append. Async streams are explicitly closed after an invalid yield. `prepare_collected_tier` requires the collected basis to equal its runtime capture and plans from that same immutable evidence. A tier executes one exact-head batch append followed by explicit projection catch-up.

Later tiers take a fresh CURRENT capture using the invocation's frozen locator ingress and require the original bounded declaration documents to remain equal before running another collector. The initial source configuration and qualification do not drift. The first tier includes captured pending boundaries before collected facts; a no-qualified invocation records pending boundaries and the accumulated overall `_sync` lifecycle in one bounded commit.

Results separate known uncommitted collection, unknown append durability, witnessed and unwitnessed actual commits, projection failure, and dispatch failure. Terminal plans retain all prepared fact/tick identities without leaking them into an uncommitted claim. No failure path reruns a collector. Run-clause dispatch intents are built before append from captured commands and exact planned tick payload/chain evidence, retained on every durable tier even when no callback is supplied, then attempted once only after a successful witnessed tier outcome. Dispatch failure retains the actual commit and all prior tier receipts.

## Acceptance coverage

Real temporary Arrival fixtures and fake collector counters cover event-time elapsed/trigger cadence, fixed dependency tiers, concurrent deterministic collection, explicit lifecycle admission, yielded output before `SourceError`, invalid-stream closure, collected-basis mismatch, collected fact admission refusal, packed atomic limits, exact-head stale CAS, declaration change before a later collector, lifecycle-only and lifecycle-plus-pending invocations, pending signed-era preflight, pending-first commit and captured run command, append-unknown versus unwitnessed identity, projection failure, and postcommit dispatch failure.

Validation at freeze:

- Source execution tests: `18 passed`.
- Source plus capture/ordinary/batch runtime tests after final hardening: `69 passed`.
- Full engine suite before the final focused hardening: `2,465 passed, 1 skipped`; all affected suites then passed in the `69`-test run.
- Ruff and ty over `arrival_sources`, `runtime_write`, and the source tests: passed.
- Architecture suite after concurrent aggregate/declaration repairs: `101 passed`.

## Review queue

The static Fable 5.1 packet is `/tmp/loops-arrival-review/source-execution-prompt.txt`. It requests at most eight concrete findings and 1,500 words, with severity, reproduction, smallest correction, and limitations. It has not been invoked before the quota reset.

## Deliberate limits

This stage does not expose SDK or CLI source execution, run the legacy `Executor`/`VertexProgram` path, retry collectors or dispatch, or claim cross-lineage atomicity. Delivery has one recorded attempt after a successful tier; it has no exactly-once or automatic retry guarantee.
