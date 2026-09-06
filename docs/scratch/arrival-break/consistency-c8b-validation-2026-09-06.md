# C8b validation — September 6, 2026

Validation uses owning package configurations and disposable stores.

## Review follow-up validation

- Full engine: **2,540 passed, 1 skipped**, 72.97 seconds.
- Full SDK: **509 passed**, 34.98 seconds.
- Architecture: **101 passed**, 5.53 seconds. Its initial two failures were
  corrected by freezing the private state envelope and moving the SDK cases
  into the existing source test module, without dependency/allowlist changes.
- Final engine source suites: **30 passed**, including **12 C8b cases**.
  This focused run followed the last one-line preservation of the sibling
  interruption's existing explicit cause and its regression assertion;
  the full runs above preceded that final chaining correction.
- Scoped engine/SDK Ruff passes. SDK basis serialization now has an explicit
  field-by-field regression assertion; its two new cases live in
  `libs/sdk/tests/test_arrival_sources.py`.

The frozen first-round report below describes that earlier validation exactly.

## Initial review evidence

- Luna full engine suite: **2,539 passed, 1 skipped**, 114.99 seconds.
  Eleven new C8b cases cover stream ownership, distinct iterators, source error,
  cancellation identity, secondary cleanup failure, standalone cleanup failure,
  ID failure without lifecycle append, prior durable tiers, cancelled sibling
  partial pairs, and final-summary failure with known-uncommitted evidence.
- Root full SDK suite: **509 passed**, 22.21 seconds. This run preceded the last
  engine hardening for interruption during distinct-owner cleanup and final
  summary construction. The SDK source suites then passed **13 tests** on final
  production, including two new real-file SDK integration cases.
- SDK integration verifies the failed tier has no custody append, earlier
  commits remain readable, unmatched observations are absent, and paired partial
  evidence survives JSON serialization. The first-tier and later-tier cases
  exercise the same real engine path through public `run_sources`.
- Scoped production/SDK Ruff passes. Sol's existing engine and SDK source
  suites passed 29 tests; these are supporting runs, not additional unique tests.

Root review prompted preservation of primary process-control exceptions,
guarded cleanup attribute lookup, a close attempt on a distinct owner after
cleanup interruption, and retention of fully collected evidence if final
summary construction fails. Terra independently reviewed the engine/SDK evidence
path and refined the separate C2 design.

Exact full-engine and SDK stdout is retained with the review artifacts.
Fable reviews are static frozen-packet reviews; their judgments and root
dispositions are in
[primary triage](reviews/consistency-c8b-c2-2026-09-06/primary-triage.md).
There is no claim of generic adapter conformance, external-effect reversal,
subprocess termination, or a C2 implementation in these test results.
