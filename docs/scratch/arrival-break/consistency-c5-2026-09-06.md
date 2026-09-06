# C5 implementation — September 6, 2026

Status: complete; implemented, validated and accepted by Fable-low. Baseline:
`79696a72` on `arrival/finish`,
the C4 checkpoint. Sol owns engine implementation and tests, Terra owns SDK
acceptance tests, Luna independently audits and validates, and root integrates
SDK entrypoints, documentation and the final Fable-low review.

## Contract

The current tick profile does not distinguish a vertex period edge from a
same-named loop tick with the same origin. Arrival execution therefore reserves
the vertex name from every local loop name, including passive/reset/carry and
count/event boundary loops. The comparison uses exact labels, with no
normalization or automatic rename. This implements the bounded C5/D4 policy,
not a new wire-format or general loop-incarnation scheme.

The shared `engine.declaration.validate_arrival_runtime_identity` helper applies
that predicate while preserving each caller's existing refusal family. It also
accounts for `cite`, which materialization installs as an implicit loop even
when it is absent from the declaration. A vertex named `cite` is consequently
outside the supported execution subset.

## Boundaries

Arrival runtime construction checks the historized effective declaration before
source compilation, then the combined declared and template-generated specs
before materialization and hydration. Supported single writes, batches and
source execution share that capture path. Detached ordinary and batch planners
also check their candidate loop names before planning. Local cache edits cannot
override a collision in effective history.

Declaration preparation and fresh initialization check the proposed declaration's
explicit loop names plus implicit `cite`. They do not load external source
templates merely to decide whether a proposed declaration is admissible;
generated names are checked when runtime expansion occurs. The separate SDK
kind-mutation semantic preview invokes the same helper. The SDK initializer
always scaffolds `item`, so it rejects vertex names `item` and `cite` before
default custody key creation.

Only the proposed result must pass the declaration-edit check. A current
ambiguous declaration can be corrected with a collision-free appended edit;
prior evidence is retained. This corrects the declared configuration, not the
unknown role of an already-recorded ambiguous tick. C5 does not add a historical
boundary-role audit or prove continuity after reconfiguration; D5/C6 retain
that design question. Existing declaration/initialization recovery keeps
its reserved intent semantics rather than reinterpreting durable operations
under the new execution restriction. Subsequent execution still validates the
effective declaration.

The general language validator and declaration reconstruction remain available
to evidence consumers. Fact/tick reads, inspection and export are not routed
through this runtime restriction. Legacy runtime/materialization behavior is
unchanged. This policy does not resolve the broader removal/recreation and
boundary-continuity questions in D5.

## Validation and review

Focused engine checks cover passive/after/every/event boundaries, direct
`Loop(reset=False/True)` planning, generated loop names, implicit `cite`,
initialization before artifacts, proposed refusal before opening custody and
tick-free correction reaching the existing signer gate. The DSL boundary
types do not expose a reset field, so explicit reset/carry acceptance uses the
runtime Loop API.

SDK integration covers preview, single and batch emission, source refusal
before collector construction, effective history overriding a noncolliding
cache, exact case-distinct names, proposed-kind refusal, and initialization
before key/store/cache/intent creation. Real file histories retain raw ambiguous
ticks, fact lookup, timeline, inspection and exact export. A separate tick-free
history accepts a signed corrective declaration with an actual Commit, retains
its original byte prefix and subsequently permits ordinary emission.

See the [independent validation](consistency-c5-validation-2026-09-06.md).
Final full runs passed **2,562 engine tests / 1 skipped**, **540 SDK tests** and
**101 architecture tests**. Scoped engine/SDK Ruff passed. The initial Fable review
accepted with no blockers and three optional notes. One is implemented: SDK
declaration preview now uses the same `DeclarationPreparationRefused` family as
signed preparation. Final SDK checks again passed **540 tests**, architecture
again passed **101 tests**, and scoped SDK Ruff passed; engine code is unchanged.
The focused Fable-low follow-up **accepted**. Its sole documentation note is
clarified in the triage. No reviews or validation jobs remain. See the
[primary triage](reviews/consistency-c5-2026-09-06/primary-triage.md).
C5 changes remain uncommitted;
nothing pushed or applied to live stores.
