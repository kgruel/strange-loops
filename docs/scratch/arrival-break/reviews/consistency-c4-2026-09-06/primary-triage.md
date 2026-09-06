# C4 Fable-low primary triage — September 6, 2026

Status: complete. One Fable 5.1 review at low effort **accepted**, with no
blockers and three optional notes. No follow-up review is required. Production,
tests and SDK README are unchanged from the reviewed and validated bytes.

The tool-free CLI reviewed frozen packet SHA-256
`3e2feabf76d9c8a9a01a143512d337b045c00e3af17199ab7c43fba6ff36a73e`
(67,791 bytes), finishing at `2026-09-06T19:01:27Z`. The runner verified
substantive Fable output; the CLI also reported a 20-token Haiku helper, not a
replacement reviewer. Source drift was empty both at review start and primary
triage. Raw findings and model usage remain unmodified in this directory.

## Findings

1. **Low: fixture observer literal. Optional, deferred.** The test uses `"test"`
   for its self-observer signatures; `libs/sdk/tests/conftest.py:13-15` explicitly
   fixes both the locator and declaration to that identity. Using
   `sample_vertex.stem` would reduce coupling to a future fixture rename. No
   rename occurs in C4 and this does not affect the present acceptance result.
   The suggestion is a test-maintenance improvement, not a correctness blocker.

2. **Low: alleged loss of nested-observer coverage. Regression premise rejected;
   extra coverage optional.** The baseline minted an `admin` key but only checked
   that the resulting signers were callable; it never invoked either scoped
   signer for `admin`. `_scoped_signer_for` loads the observer's key lazily when
   its returned callable is invoked, so that branch was not exercised by the
   old test. The new test verifies actual signatures for all three domains.
   Direct nested observer tests remain in custody (for example
   `test_case_variant_nested_observer_does_not_poison_flat_self`); custody
   production and tests are unchanged, and that separate suite was not rerun
   for this SDK constructor-only change. Extending the SDK test to another
   observer is optional rather than restoring a lost behavioral assertion.

3. **Low: discoverability. Partly valid optional suggestion; placement claim
   rejected.** The class docstring could mention the unsupported argument for
   `help()` users; the README already states the complete compatibility rule.
   The claim that the paragraph is inside the `emit_batch` list is incorrect:
   `README.md:172-179` is unindented, separated by a blank line after the final
   API bullet, and followed by a section divider. No paragraph move is needed.
   A more extensive provider API reference is optional documentation work.

## Validation and completion

Terra's focused emission run passed 67 tests. Luna's final checks passed
528 SDK tests and 101 architecture tests, with scoped SDK Ruff clean.
Production/test hashes match before and after validation and the review packet;
`final-source-hashes.json` additionally records the SDK README. Raw full-run
logs are retained alongside this triage.

The runner's `status.json` records its historical review-awaiting-triage state;
`triage-status.json` is the final disposition. Only completion documentation
changes after the review; frozen packets are preserved. C4 remains uncommitted
on `arrival/finish`, based on `831698ff`. Nothing pushed or applied to live stores.
