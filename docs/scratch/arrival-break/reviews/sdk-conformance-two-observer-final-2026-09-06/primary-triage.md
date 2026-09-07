# Primary triage: two-observer conformance

Fable 5.1 LOW: **REVISE**. Primary initial verdict: **REVISE**.
Correction is complete and accepted by the
[focused follow-up](../sdk-conformance-two-observer-followup-2026-09-06/primary-triage.md).
Packet SHA-256: `48dd3dfa74f8f5bb2d2aec2ae3590719928aa98200dc62fa1c8fc63037d2d59d`.
The reviewer performed static analysis; native test results came from the team.

## Accepted blocker

The wrong-namespace assertion accepts any `CredentialBindingRefused` carrying
the captured head. Root independently replaced the other namespace's resolver
with a function that always raises before resolving a key: the frozen workflow
still passed. That is a conformance false positive, not a production failure.
The correction must identify the specific captured-authorization refusal and
the complete public request, and establish that the alternative binding carries
a distinct public key.

## Optional findings

- Case-distinct `Alice` is refused by declaration admission before signer
  selection. The workload also resolves its distinct persisted binding directly.
  Clarify those two observations in the report; another granted author workflow
  is unnecessary for this bounded slice.
- Assert each accepted write advances the ordinal without changing lineage.
  This makes the transition claim explicit with little additional test cost.
- Do not add an assertion about a `.loops` directory at the moved descriptor:
  that introduces private file-layout assumptions into a public application
  test. Existing store descriptor identity and exact head/read equality cover
  the specified unchanged absolute residence.
- The individual admission error's smaller evidence surface is existing API
  behavior. The report deliberately says available typed evidence; no new error
  API is needed here.

Frozen initial review evidence is retained. The focused correction suite passed
13 tests and Ruff. The follow-up Fable-low and primary verdicts are ACCEPT;
all findings here are now triaged and closed.
