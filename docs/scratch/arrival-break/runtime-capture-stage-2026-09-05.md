# Arrival completion runtime capture stage — 2026-09-05

Status: implementation and local verification complete; Fable review queued for the reported 21:20 CDT quota reset.

## Result

`capture_runtime` now acquires an attested Authority ledger and CURRENT projection before any source collector can run. It retains the exact captured head/basis, physical custodian, backend atomic limit, bounded declaration documents and anchor, exact fact/tick evidence, compiled source configuration, and a detached runtime construction recipe. All ledger/query/snapshot handles close before the value returns.

The capture owns a minimal copy of locator residence and inline-source ingress. Public declaration, documents, facts, ticks, sources, and pending-boundary accessors return reconstructed or copied values. Planning always copies the private runtime template. Caller mutation of its original locator, returned evidence, or one plan cannot change a later plan.

`plan_batch_from_capture` never reopens the registry. Existing ordinary and batch preparation now compose capture plus planning while retaining their public behavior. Source-mode captures evaluate eligible externally pending boundaries once against bounded facts/ticks and save both pre-evaluation and post-evaluation candidate state. Including the boundary prelude starts subsequent item planning from the post-boundary state, including reset and period bookkeeping even if evaluation emitted no tick.

Pending boundary ticks appear before tier facts, retain exact chain/window/signature evidence, and have independent `pending_tick_ids` and `pending_tick_names` on plans, commits, and postcommit/unknown failures. Empty boundary-only planning is supported only when a pending tick exists. Recorded ticks suppress re-emission, and count boundaries remain ingress-driven.

Effective source construction uses bounded declaration documents, reattaches inline env values with the existing occurrence/count rules, validates source and params pins without opening a declaration store, compiles dependency sources, and merges template-generated loop specs. `effective_declaration_from_documents` exposes the same store-free bounded reconstruction for later consumers.

## Acceptance coverage

The real temporary Arrival tests cover stale CAS after a declaration append, repeated-plan isolation, caller locator/env mutation, source/template pinning and captured behavior after later drift, boundary-only commits, recorded versus pending boundaries, post-boundary reset state before new facts, vertex period state when no prelude tick fires, two pending ticks with exact projected chain/window evidence, signed-era refusal, and count non-invention.

Validation at freeze:

- Capture, ordinary, and batch runtime tests: `51 passed`.
- Engine suite before the final two focused freeze corrections: `2,423 passed, 1 skipped`; the corrected affected suite then passed `51`.
- SDK emit/preview regression set: included in `158 passed` with the runtime suites.
- Full SDK: `416 passed`, with two unrelated concurrent initializer/legacy kind failures recorded to root; no FoldCollect copy failures remain.
- Architecture: `101 passed`.
- Lang document/loader: `413 passed`; compiler/declaration resolver: `157 passed`.
- Ruff and ty over the new runtime capture module surface/tests: passed; `git diff --check`: passed.

## Review queue

The static Fable 5.1 packet is `/tmp/loops-arrival-review/runtime-capture-prompt.txt`. The queued command requests at most eight concrete findings and 1,500 words, with severity, reproduction, smallest correction, and limitations. It has not been invoked before the quota reset.
