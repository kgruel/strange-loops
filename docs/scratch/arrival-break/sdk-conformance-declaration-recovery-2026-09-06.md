# Public SDK conformance: interrupted declaration recovery

Status: complete, natively validated, and accepted by Fable-low and primary
review; included in the checkpoint on `arrival/finish`, based
on `2d4d2d0a`. This is the second bounded workload-conformance slice
preceding C9 transition and legacy retirement.

## Contract under test

A mapped public SDK declaration edit is interrupted after its append commits
and before projection synchronization and descriptor cache publication. The
SDK must preserve the committed outcome and recovery coordinates. Recovery
reconciles the retained edit against history, finishes publication without
appending the proposal again, and permits inspection and subsequent authorized
writing against the resulting declaration.

The recovery result retains the original edit's captured basis. Its final head
describes the reconciled history; it does not manufacture an original `Commit`
or a fresh read basis. Public inspection and fact reads separately establish
the current effective declaration and projected prefix. Prefix verification
checks grammar, density, lineage and the hash chain; it does not establish
signature authorship, external key trust or projection agreement.

## Scope

Sol owns the executable workflow; Terra independently audits the contracts and
updates SDK guidance; Luna checks the resulting suite; root integrates the
evidence and triages a frozen Fable 5.1 LOW review. All validation processes
isolate XDG state/config and `LOOPS_HOME`; fixtures use disposable stores and
mapped keys. No live migration or legacy retirement is involved.

The public SDK intentionally has no interruption argument. The test injects
the engine's existing `after-append` failure hook beneath `edit_declaration`;
the edit, recovery, inspection and continued write remain public SDK calls.
This is a deterministic exception-boundary test, not a process-kill, power-loss
or multi-machine durability test. The locator stays at its original path with
an absolute store location throughout recovery.

Existing declaration tests complement this workflow with pre-append/not-applied
recovery, cache-publication interruptions, competing-cache refusal and exact
suffix/predecessor validation. This slice does not replace those tests or claim
all recovery phases. Recovery is distinct from restore-forward, which belongs
to the upcoming transfer workload.

## Executable evidence

The [workflow](../../../libs/sdk/tests/test_arrival_declaration_recovery_workload.py)
initializes a strict declaration with mapped Alice credentials. A `note` fact
refuses before the new kind is declared. The interrupted public edit retains
its before/after head, phase, declaration fact IDs and public intent path.
Prefix verification reaches that durable head while the descriptor still has
its original bytes. Inspection refuses on the stale projection; another edit
reports a preparation refusal with a `ProjectionBehind` cause and custody
not entered. Neither operation advances the verified head.

Recovery runs with mapped resolution and legacy credential acquisition poisoned.
It retains the original captured basis and declaration fact IDs, reports no
original commit or changes, and publishes the proposed descriptor. The head
stays unchanged across recovery. An internal fact read checks the baseline
identities and the new `note` declaration fact exactly once. Fresh inspection
reports matching local/effective declarations and current projection evidence.
Repeating the recovered proposal is a no-op. A reconstructed mapped provider
then emits a signed `note` fact; its commit predecessor, public read basis,
projected prefix and final verification agree. SDK outcome and inspection
serialization are also checked.

## Validation and review

Focused declaration, mapped credential and new workload tests: **49 passed**
in 1.13 seconds. Full SDK: **580 passed** in 21.79 seconds. Architecture:
**101 passed** in 6.20 seconds. Scoped Ruff and whitespace checks pass.
Initial Fable-low and primary verdicts: **ACCEPT**, no blockers. Four optional
assertion refinements pin the injected hook, exact one-record advancement,
complete recovered fact-ID list and no-op head. Final focused validation after
those test-only changes: **49 passed** /1.28s, Ruff and whitespace checks pass.
The full suites precede only those assertion changes. Follow-up Fable-low and
primary verdicts are **ACCEPT**, no blockers. No production files changed.

The [initial review](reviews/sdk-conformance-declaration-recovery-final-2026-09-06/final-findings.md)
and [final primary triage](reviews/sdk-conformance-declaration-recovery-followup-2026-09-06/primary-triage.md)
retain frozen packets, raw results, native logs and source checks. The final
test matches the accepted follow-up packet; only maintained status and handoff
prose changed afterward. No jobs remain. Tests, guidance and review evidence
are included in this checkpoint; nothing pushed.

## Next

Run sources with partial failure, inspect persisted tiers, and establish what
can safely resume. Follow with captured-prefix export, restore-forward,
verification, explicit sync and read. C9 transition and retirement remain ahead.
