# Public SDK conformance: captured export and restore-forward

Status: complete, natively validated, and accepted by Fable-low and primary
review on `arrival/finish`, based on
`3152e810`. This is the fourth bounded public workload-conformance slice before
C9. No commit or push is part of this pass.

## Contract under test

An exported prefix is bounded by its selected full head, even if the source
has advanced. The export result distinguishes the head captured when opening
the source from the selected head represented by the artifact. Selection does
not lower the local witness floor.

Restore-forward opens explicit source and receiver descriptors; it does not
consume an export artifact. The receiver must already contain an exact source
prefix. Its proposed restored head must reach the witnessed floor. Selecting
an older, otherwise valid source prefix can therefore export successfully but
refuse restoration with `HeadRollback`. A fresh restoration through the source
head appends the missing suffix without replacing prior history.

Restoration preserves the receiver's role and leaves its projection at its
existing version. Structural verification can succeed while a CURRENT read
still refuses. Explicit synchronization then catches the projection up, and
public reads must agree with the restored custody and retain all prior rows.

## Scope and executable evidence

Sol implements the workflow; Terra audits contracts and SDK guidance; Luna
validates the integrated suites; root checks causal assertions and triages a
frozen Fable 5.1 LOW adversarial review. Every test process isolates XDG state,
XDG config and `LOOPS_HOME`; mapped keys and stores are disposable.

The [workflow](../../../libs/sdk/tests/test_arrival_transfer_workload.py) uses
public initialization, emission, export, restoration, verification, sync and
fact reads. Receiver installation uses public export to write the initial exact prefix,
followed by an explicit replica descriptor as test fixture setup. That is not
a public import API.
Empty-receiver import remains separate work.

The workflow distinguishes retained selected export bytes from the later live
source used for successful restoration. The later source observations belong
in the restored receiver but not in the historical exported artifact. These
are deterministic sequential operations, not a concurrent writer or crash
test. Existing transfer tests retain stream-lifetime, races, unknown receipt,
committed-incomplete, projection contradiction and publication fault coverage.

Full verification establishes grammar, density, lineage and hash chain. It
excludes signature authorship, external key trust and projection verification;
the workflow separately compares exact artifact/custody bytes and public rows.
No trust reset, witness deletion or implicit projection repair is involved.

## Validation and review

Final focused SDK transfer/export/restore validation: **16 passed** /0.49s.
Full SDK: **583 passed** /20.96s. Architecture: **101 passed** /5.67s.
Engine transfer/restore regressions: **55 passed** /0.38s. Scoped Ruff and
whitespace checks pass. Fable 5.1 LOW and primary verdicts: **ACCEPT**, no
blockers or source corrections. All validation
commands use `uv run --no-sync` with isolated process roots; test, SDK guidance
and production-context hashes were unchanged across the full suite run.
The executable SHA-256 is
`5103a21f0bf0cabb65b3e3a3b3d95426619ec8f0f1022b6958f205fd58746d83`.
No production code changed. See the
[review](reviews/sdk-conformance-captured-transfer-final-2026-09-06/final-findings.md)
and [primary triage](reviews/sdk-conformance-captured-transfer-final-2026-09-06/primary-triage.md).
All frozen source hashes matched at closure; only maintained status/handoff
prose changed afterward. No test or SDK-guidance edits followed review and no
jobs remain. The slice is ready to checkpoint.

## Next

The four agreed public workflow slices lead into C9: inventory the supported
SDK/minimal-CLI surface and remaining legacy callers, choose a bounded first
transition, and retire competing authority paths with their consumers covered.
Projection preserve/rebuild recovery, empty-receiver exact import, foreign
admission, descriptor adoption and live-store migration remain separate work;
this conformance pass does not implement or authorize those operations.
