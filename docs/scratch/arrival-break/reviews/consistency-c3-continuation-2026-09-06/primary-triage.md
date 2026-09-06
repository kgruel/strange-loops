# C3 continuation Fable-low primary triage — September 6, 2026

Status: complete; accepted with no blockers. No reviews or validation jobs
remain. Production and tests are unchanged after validation and review.

## Review evidence

Fable 5.1 at low effort accepted the frozen packet, finishing at
`2026-09-06T19:58:26Z`. Packet SHA-256:
`4e8101465c55c506e779583ab5f6aa91f745efe6317d1733a9c31c91663a97d4`
(96,800 bytes). The tool-free CLI runner returned exit 0 and verified
substantive Fable output. A 13-token Haiku CLI helper was auxiliary. Source
drift was empty at review start; production/test drift is empty at primary
triage. The implementation report alone receives completion wording after
review. Frozen packet, manifest,
raw findings, model usage and validation logs are retained in this directory.

The reviewer confirmed that resumed snapshot evidence uses the common custody
helper, original token H/P remain intact, contradictory heads refuse with
`HeadMismatch`, backend exceptions retain identity, and failed opens close
snapshot/query/ledger. The real SDK test demonstrates explicit projection
advance between pages without admitting later rows into the continuation.

## Optional findings

1. **Low: direct tests for P <= W < H and W < P. Deferred test coverage.**
   The new synthetic positive case uses distinct P < H and a vouched W > H;
   the negative cases exercise newly detected hash/coordinate contradictions.
   There is no new direct consumer-seam case for an intermediate watermark or
   regression below P. Those comparisons and original-token basis selection
   are unchanged, and the common helper accepts a valid coordinate below H.
   Source inspection verifies the unchanged W < P refusal before returning
   a basis. Adding those cases would strengthen future adapter conformance,
   but no present incorrect behavior was identified. This pass does not claim
   dedicated execution coverage for those two branches. The review's phrase
   suggesting indirect file-backend regression coverage is not used as proof;
   the validation note distinguishes existing tests from source tracing.

2. **Low: SDK `projected_after` omitted from the packet. Resolved by source
   and executed validation.** `sdk.types.SyncResult.projected_after` is declared
   as `Head | None` at `libs/sdk/src/sdk/types.py:890`; Arrival `sync_target`
   fills it from the maintenance result at `libs/sdk/src/sdk/read.py:1847`.
   The actual successful synchronization in the packed-batch acceptance test
   populates this field. The focused SDK file passed 21 tests and the full SDK
   suite passed 540 tests on the final bytes. This was a packet visibility
   limit, not an implementation failure; no correction or rerun is required.

One explanatory review sentence also needs precision: generation and prefix
regression checks remain after custody lookup, but projection disappearance
is handled in the earlier `watermark is None` branch, both before and after
this change. No disappearance ordering changed.

## Final state and limits

Final validation: **2,568 engine passed / 1 skipped**, **540 SDK passed**,
**101 architecture passed**, scoped engine/SDK Ruff clean. The three changed
production/test files match the before/after validation hashes and review.
Only completion documentation changes after acceptance. No follow-up review
is needed because there is no production or test revision.

Custody completion proves the reported coordinate, not every projected row's
equivalence to custody. Existing adapter generation, row bounds and token
policies remain in force. `baseline-regression-evidence.json` identifies Sol's
agent-reported pre-fix result separately from the retained final raw logs.

`status.json` is the runner's historical awaiting-triage record;
`triage-status.json` is the authoritative completed state. This implementation
remains uncommitted on `arrival/finish`, based on C5 checkpoint `bacaeb96`.
Nothing pushed or applied to live stores.
