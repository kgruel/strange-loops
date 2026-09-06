# C1: SDK registry consistency — September 6, 2026

Status: complete. Fable-low accepted; all four findings have root dispositions.
Worktree: `loops-wt/arrival-finish`, branch `arrival/finish`. This slice follows
the accepted [C3/C8a implementation](consistency-slice1-2026-09-06.md) and implements
C1 from the [consistency matrix](consistency-contract-matrix-2026-09-06.md).

## Behavior

`resolve_entity`, `read_timeline`, and `inspect_declaration` now accept optional
keyword-only `registry: BackendRegistry | None = None`. Each forwards the
supplied registry to the existing captured Arrival read. Omission retains the
built-in default. Legacy branches retain their existing behavior.

Timeline forwards the same registry through both storeless local aggregation
and aggregation discovered from a descriptor root's captured effective
declaration. The latter retains `opened_root`, so composition consumes the
already captured root rather than opening it again. Every member is resolved
through the supplied registry; this does not create a global aggregate head.

Descriptor locations remain opaque for non-file backends. Unknown backends
refuse through existing error paths without switching to legacy storage or an
alternative registry. This slice changes registry selection, not refusal
normalization, which remains C2.

Entity and declaration inspection retain their existing Arrival aggregate
restrictions. Aggregate inspection remains C7; aggregate entity semantics are
not introduced here. No engine protocol, adapter, capture policy, identity
rule, or persistence format changes are needed.

## Implementation and review

Sol owns the two production files, Terra owns SDK regressions, Luna independently
reviews routing and validates architecture, and root reviews scope and evidence.
Fable 5.1 at low effort accepted the frozen, tool-free packet with no blocking
findings. See the [review and root triage](reviews/consistency-c1-2026-09-06/primary-triage.md).
Follow-up adds three empty-registry/file-backend test cases and clarifies the
README legacy scope; production code is unchanged from the accepted review.
The reported duplicate-close concern is already handled by the existing
`OpenedRead.close` guard, confirmed by a root counting-handle probe.

## Validation

The new `test_arrival_registry_injection.py` registers an opaque adapter with
an actual `BackendRegistry` and maps exact opaque addresses to temporary file
ledger/query handles. It exercises the real registry and bounded query path;
it is not a remote-adapter or cryptographic-signature conformance test.

Coverage includes single-target entity/timeline/inspection, storeless aggregate
timeline, history-effective aggregation with exactly one root open, and
unknown-backend refusals. Explicit-registry cases poison default registry
construction; single-target cases also poison legacy probing. Temporary
`XDG_STATE_HOME` isolates attestation evidence.

Validation: **504 SDK tests passed**, **101 architecture checks passed**,
**40 focused read/inspection/aggregate tests passed**, and scoped Ruff passed.
After review, the expanded C1 file passed **10 cases** and scoped Ruff again.
The full SDK run above preceded the three added file-backend cases; it is not
a claim that a combined 507-test suite was rerun. Existing default and legacy paths remain
covered by the full SDK suite. See the
[independent validation note](consistency-c1-validation-2026-09-06.md).

All changes remain uncommitted. Test artifacts are temporary; this slice does
not run operations against live stores or credentials.

C2 still needs phase/cause/effect design before normalization. C4 credential
configuration, C8b collector ownership and the remaining identity decisions
remain on the matrix; this slice does not implement those policies.
