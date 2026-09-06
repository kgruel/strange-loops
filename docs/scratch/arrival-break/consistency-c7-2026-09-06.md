# C7: bounded aggregate declaration inspection

Status: complete and accepted after Fable-low review on `arrival/finish`,
based on C6 checkpoint
`1c37ca65`. Sol owns descriptor resolution, Terra inspection/DTOs and integration
tests, Luna independently audits and validates, and root owns contract decisions
and final Fable-low review triage. C7 is checkpointed with this report; nothing pushed.

## Contract

`inspect_declaration` inspects a root declaration. For a descriptor-backed root,
it opens that root once through the supplied registry, earns a CURRENT bounded
snapshot, and reports the effective declaration from that snapshot. Its basis
is the root's H/P/G. It does not expand combine names, glob discover patterns,
open members, or claim a complete aggregate topology or global Head.

Inspection explicitly opts into local aggregate descriptor resolution and
effective aggregate declaration reconstruction. Default target resolution and
other single-store operations keep their existing restrictions. Explicit
descriptor roles remain mandatory; missing roles refuse before opening.

The v2 inspection DTO gains additive local/effective combine and discover
fields. Combine entries preserve order, names and aliases; discover retains
the literal pattern. Null and an explicitly empty combine remain distinct.
These fields describe declared references, not authenticated member evidence.
Both local-aggregate/effective-plain and local-plain/effective-aggregate roots
are valid inspection inputs; the effective fields follow captured history.

A storeless aggregate has no adopted root custody to capture. Inspection uses
one retained parsed local definition, returns `read_path="local-frozen"`, no
store or basis, and an explicitly local status. Local/effective semantic
fingerprints and shape may coincide because that frozen definition is the
only interpretation available. A semantic fingerprint does not claim exact
file bytes or a receipt history. No child availability or validity is asserted.

Existing non-storeless legacy inspection remains a compatibility path.
Ordinary descriptor attestation may advance witness evidence; inspection does
not promise zero filesystem writes or authorize projection repair.

## Native review corrections

Root and Sol identified a file-replacement race in the first storeless draft:
discarding a no-descriptor AST and parsing again could redirect inspection
through legacy probing. The shared `_arrival_definition` helper now retains
the parsed root even when it has no descriptor. Inspection uses that same AST
to choose and render the storeless path before any legacy probe. Descriptor
absence alone is insufficient: a legacy stored root also has no descriptor,
so local-frozen admission separately requires `ast.store is None`.

Storeless local/effective combine lists are independently detached so mutating
one exposed view cannot mutate the other. The DTO remains shallowly frozen,
as before; its lists are not advertised as immutable. New optional fields
follow the existing fields to preserve positional construction compatibility.

## Acceptance and scope

Focused integration tests must exercise both topology drift directions,
literal combine aliases/discover patterns, root-only registry use and closure,
storeless evidence, explicit-role refusal, and CURRENT absent/behind refusal.
Existing SDK aggregate reads, single-store readers/writers and DTO serialization
must remain compatible. Full SDK and architecture checks cover the composition
change; engine implementation is not expected to change.

This does not add recursive graph validation, aggregate entity/fact inspection,
an aggregate custody basis, credential bindings (D0/D2), or legacy retirement
(C9). A missing member can be declared and inspected successfully; opening an
aggregate read remains the operation that needs member evidence.

## Evidence

- [Inspection implementation notes](consistency-c7-inspection-notes-2026-09-06.md)
- [Resolution notes](consistency-c7-resolution-notes-2026-09-06.md)
- [Independent audit](consistency-c7-audit-notes-2026-09-06.md)
- [Validation](consistency-c7-validation-2026-09-06.md)

Focused target checks passed (23), as did inspection/DTO checks (27) and the
independent contract tests (5). Final SDK validation passed **559**, architecture
**101**, and scoped Ruff passed. Final source/test hashes match before and after
the SDK run. Engine source is unchanged.

Early independent tests omitted state isolation and created four synthetic
test witness journals plus four shared binding rows in the default user state
directory. The final tests use an autouse temporary-state fixture. The
[validation report](consistency-c7-validation-2026-09-06.md) records the artifacts;
they were preserved without rewriting the shared witness journal. No Arrival
operation was directed at real project stores.

## External review and handoff

[Fable-low accepted](reviews/consistency-c7-implementation-2026-09-06/primary-triage.md)
the frozen implementation with no blockers. Root triaged all four optional
notes. A post-review assertion refinement checks that topology-only drift
changes both local status and semantic fingerprint in both directions;
5 focused tests and scoped lint pass. Production remains identical to the
accepted packet. The reviewer did not see those later assertions.

C7 is checkpointed with this report; nothing pushed. Next
planned substantial work is D0 credential request design, then D2 persisted
binding/compatibility. A separate small follow-up can replace the older
summary/state/timeline aggregate resolver's catch-and-reparse bridge with the
new opt-in helper and test concurrent locator replacement. C9 clients should
preserve the local-only versus captured-root evidence distinction.
