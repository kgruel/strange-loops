# Public SDK conformance: partial source failure and a fresh invocation

Status: complete, natively validated, and accepted by Fable-low and primary
review on `arrival/finish`, based on `d75aae9e`, and included in this
checkpoint. Nothing pushed.
This is the third bounded public workload-conformance slice before C9.

## Contract under test

Source execution commits one dependency tier at a time. A collector's
`SourceError` can become durable evidence along with observations yielded
before the error. An invocation-level error does not mean its tiers rolled
back. Public tier receipts, lifecycle identities, fact reads and verification
must agree about what persisted.

Calling `run_sources` again starts a new invocation with newly evaluated
cadence and fresh fact identities. It does not resume a retained batch or
reuse the previous invocation's IDs. A successful upstream source can be
skipped while its persisted lifecycle still qualifies a failed downstream
source. A downstream error lifecycle is not a successful completion for
cadence purposes.

## Scope and executable evidence

Sol implements the public workflow; Terra audits contracts and SDK guidance;
Luna validates the integrated tests; root checks causal assertions and triages
a frozen Fable 5.1 LOW adversarial review. Test processes isolate XDG state,
XDG config and `LOOPS_HOME`; all stores and mapped bindings are disposable.

The [workflow](../../../libs/sdk/tests/test_arrival_source_resumption_workload.py)
uses public mapped initialization and declaration editing to
install an elapsed upstream source and a dependent triggered source. A forced
first invocation fixes both dependency tiers. The downstream collector fails
either before yielding or after yielding one observation. Public inspection
then accounts for the committed observations and error lifecycles. A fresh
non-forced invocation before the upstream interval expires must run only the
downstream collector.

The public SDK calls remain unchanged. A wrapper beneath `run_sources` supplies
the existing engine execution clock so lifecycle times are deterministic:
12 for the first invocation, 22 for the next, with cadence evaluations at 10
and 20. The upstream's persisted success is therefore eight seconds old at
the retry, inside its one-hour interval. This is not a process-crash test.

Both reads account for the entire internal fact-ID sequence in receipt order
and refuse unnoticed pagination. The test compares returned observations and
lifecycles with persisted bodies, checks the failed lifecycle's error and
invocation evidence, and requires all rows read after failure to remain
unchanged after the successful retry. Initial/per-tier bases, actual commit
predecessors and final verified/projected heads agree. The second invocation
uses a newly constructed mapped provider with the same root and namespace.

The before-yield case demonstrates a narrow retry that introduces no repeated
domain observation. The after-yield case deliberately collects the same
logical observation again and must retain both independently identified facts.
The store provides no automatic semantic deduplication. Retry safety still
depends on the collector's external effects and the application's handling of
already-observed data. The fixture uses in-memory collectors with no external
effects; it does not establish exactly-once collection or dispatch.

This slice covers durable source errors. Existing source tests separately
exercise known-uncommitted tiers, unknown append outcomes, unwitnessed commits,
projection failure, dispatch failure and collection bookkeeping/cleanup
interruption. Those categories do not imply the same retry decision. There
is no new resume-token API, automatic retry policy, or legacy migration here.

Full prefix verification checks grammar, density, lineage and hash chain.
It excludes signature authorship, external key trust and projection
verification; the workflow separately compares public read/projection and
custody coordinates. Existing mapped signing tests supply complementary
cryptographic coverage.

## Validation and review

The focused SDK source, mapped credential and new workload suite passes:
**28 passed** /0.99s. Final full SDK: **582 passed** /23.30s. Architecture:
**101 passed** /6.79s. Engine source/coordinator regression suites:
**30 passed** /0.78s. Scoped Ruff and maintained-file whitespace checks pass.
All commands use `uv run --no-sync` and isolated per-process state/config/home
roots. No production code changed. The final executable SHA-256 is
`ac1513bd080f907e3f7722602f9a520475f9e315b9612abe152048363f27f48e`.

The SDK guidance also narrows an existing unconditional source-error durability
claim: the completed invocation has durable error evidence; an interrupted
operation requires inspecting its actual tier commits and terminal outcome.
Fable 5.1 LOW and primary verdicts are **ACCEPT**, with no blockers or source
corrections. Optional extra lookup/dispatch assertions were triaged as redundant
for this bounded workflow. The primary triage also narrows a reviewer statement
about explicitly asserted lifecycle timestamps. See the
[review](reviews/sdk-conformance-source-resumption-final-2026-09-06/final-findings.md)
and [primary triage](reviews/sdk-conformance-source-resumption-final-2026-09-06/primary-triage.md)
for the frozen packet, native validation and source checks. All sources matched
at closure; only maintained status/handoff prose changed afterward. No jobs
remain, and no production code or SDK-guidance changes followed the review.

## Next

Captured-prefix export → restore forward → verify → explicitly sync → read.
C9 transition and retirement remain ahead, with larger maintenance, transfer
and adoption work tracked separately.
