# C2 evidence contract — September 6, 2026

Status: design only. This specifies the evidence required before public SDK
normalization is widened; it neither changes wire records nor declares a common
transaction for custody, projection, cache publication, dispatch, or external
collection.

## What exists now

`normalize_exception` already preserves important public categories:
`WriteCommitUnknown`/batch equivalents become an unknown custody outcome,
`NotWitnessed` retains its resulting head and an actual `Commit` where the
underlying operation supplies one; post-commit projection failures retain their
commit. Initialization, declaration recovery, and restore have
operation-specific unknown/incomplete wrappers. Source invocation instead
returns structured per-tier results, preserving an earlier durable tier while a
later tier is uncommitted or unknown.

There are two material gaps. `sync_target` calls `sync_projection` directly and
therefore bypasses the existing `ProjectionSyncError ->
ProjectionOutcomeUnknown` mapping (`sdk/read.py:sync_target`). Also,
`_identity_details` serializes wrapper coordinates but not `exc.cause`, so an
in-process maintenance caller can inspect the causal exception while an SDK
caller cannot identify its stable type or its evidence. The same concern applies
to search-index synchronization. Declaration preparation catches a
`ProjectionBehind` in its generic preparation wrapper
(`arrival_declarations.py:prepare_declaration_edit`); chaining retains the
cause today, but public normalization must not erase it.

The current maintenance wrapper is intentionally conservative. Once
`sync_projection` enters its catch-up attempt, it wraps an ordinary
`Exception` as
`ProjectionSyncError(target, projected_before, observed_after, cause)`.
Some adapter checks can fail before changing rows, but the wrapper does not
prove that for every implementation. `SearchIndexSyncError` has the analogous
shape after a target is selected. Thus a nested `NotAuthority`,
`ProjectionBehind`, or backend refusal is not sufficient evidence of a
known-unmodified projection. Capture/open failures occur before that wrapper;
`BaseException` control flow, including cancellation, escapes it.

A successful sync can report `projected_after > target` when another serialized
maintainer legitimately advanced it. This proves custody-resolved coverage of
the target, not row-for-row projection provenance; the explicit restore audit
is the stronger operation.

## Proposed public evidence shape

This is a narrow additive schema for the existing maintenance, write and
source result/error DTOs. It is not a universal operation framework: each
operation exposes only fields it can prove, under its existing names where
possible. The new engine attribute is named `coordinator_phase`; only the SDK
serializer maps it to `details["evidence"]["phase"]`. It never writes or
reinterprets existing `details["phase"]`, which remains the operation-specific
field copied by `_identity_details` from current exceptions.

| Field | Meaning |
| --- | --- |
| `phase` | The operation-local `coordinator_phase` proved reached, such as `capture`, `prepare`, `custody-append`, `derived-sync`, `cache-publication`, or `dispatch`. It is not a global ordering across resources. |
| `effects` | Per-resource entries for `custody`, `witness`, `derived`, `cache`/`artifact`, or `dispatch`, each with `attempt` and `state`; see concrete values below. |
| `basis` | Captured `H`/`P`/generation where one exists, target/actual projection heads for maintenance, and declaration anchor where interpretation mattered. |
| `identities` | Planned fact/tick IDs, item or tier index, observer/kind, and a real `Commit` before/after when known. No invented Commit for a no-op or recovery. |
| `cause` | A bounded recursive diagnostic: causal type name, message, and the same safe identity coordinates available on that cause. Its exact source and bound are specified below. |

**Concrete additive SDK shape:** put an optional object at
`details["evidence"]`, retaining `loops.sdk/error/v1` and all current top-level
error fields:

```json
{"schema":"loops.sdk/evidence/v1", "phase":"derived-sync",
 "effects":{"derived":{"attempt":"entered", "state":"unknown"}},
 "basis":{"target":{}}, "identities":{},
 "cause":{"type":"OSError", "message":"…", "details":{}}}
```

When present, `attempt` is exactly `not-entered` or `entered`; it is omitted
when a legacy wrapper has no control-flow proof either way. `state` is exactly
`not-attempted`, `known-none`, `committed`, `unknown`, `completed`, or
`incomplete`. `not-attempted` means this coordinator did not cross that
resource's mutation boundary. `known-none` is a distinct proof: an entered
adapter call had an explicit atomic-rejection guarantee of no effect. Neither
follows merely from a nested exception type. Invariant:
`attempt=not-entered` requires `state=not-attempted`; other states may omit
`attempt` when boundary-entry evidence is unavailable. `phase` is proof, not a
progress guess. Cancellation and process-control exceptions are re-raised
unchanged, with no replacement wrapper. Structured source results use the
identical object at `terminal.details["evidence"]`, preserving the current
`SourceTerminalResult.details` DTO shape.

For `cause`, choose an explicit BaseException-valued `.cause` first; otherwise
use BaseException `.__cause__`. Serialize at most two causal nodes after the
outer error, stop by object-identity cycle guard, and use the same whitelisted
identity fields as `_identity_details`. Each message is capped at 512
characters with `truncated=true` when shortened. Never follow `__context__`,
call `repr`, or serialize payload/record bodies.

The existing categories can map without flattening evidence:

- An admission/preparation refusal is `phase=prepare`,
  `custody=not-attempted` only when its planner has not opened its append
  boundary. It may report `known-none` after an entered adapter call only with
  an explicit atomic-rejection proof; retain the declared admission details and
  its nested cause.
- A CAS/refusal before `ledger.append` in the runtime executor is a known
  no-custody-append refusal. A generic exception after entering `append` is
  `custody=unknown` with planned IDs and captured H (`WriteCommitUnknown`).
- `NotWitnessed` proves `custody=committed` and `witness=unknown`, with its
  resulting head. Its `commit` is present for append/replicate but is `None`
  for mint, so only serialize a Commit receipt when one exists; it must never
  be relabeled as a refusal.
- An `after_commit` failure is `custody=committed`, with a real Commit and an
  independently failed/unknown derived effect. Its result must not claim that
  projection was performed.
- `ProjectionSyncError` is `derived={attempt: entered, state: unknown}`: its
  catch-up wrapper begins at `maintenance.catch_up`, so it has no snapshot or
  provider substage to prove non-entry once it wraps. In contrast,
  `SearchIndexSyncError` can prove
  `{attempt: not-entered, state: not-attempted}` when target selection succeeded
  but `query.open_snapshot` or provider acquisition fails before `build`; use
  `entered/unknown` once the coordinator calls `build`, unless an adapter
  supplies atomic no-effect proof. Include target, before,
  observed-after/coverage, spec hash for search, and causal evidence. Do not
  infer custody uncertainty: these operations do not append custody records.
- A source result retains each tier's own basis, IDs, Commit/witness/projection
  and dispatch evidence. Collected external effects are not rolled back by a
  stale or unknown custody append; `known-uncommitted` custody is not evidence
  that recollecting is safe. A durable earlier tier is not downgraded by a
  later failure. C8b's proposed coordinator-only
  `SourceTierCollectionFailed` terminal carries the current tier basis,
  completed siblings, failed-source `(Fact, id)` metadata, cancelled sources,
  paired partial output, and cause. It belongs in the existing structured
  result, with no fabricated `CollectedTier` or lifecycle ID for an incomplete
  attempt. C8b serializes this current source-specific evidence at
  `terminal.details["collection"]`; that is deliberately separate from the
  prospective shared `terminal.details["evidence"]` object. Dispatch remains
  one attempted post-commit action with no at-least-once claim.

## Bounded implementation worklist

1. Add optional `coordinator_phase` plus resource-scoped `effects` evidence to
   only `ProjectionSyncError` and `SearchIndexSyncError`. Projection sync marks
   its wrapped attempt entered/unknown. Search marks snapshot/provider failure
   after target selection not-entered/not-attempted, then flips a local flag
   immediately before `build`. Do not inspect nested exception classes to
   synthesize proof. Keep constructor compatibility with optional fields.
2. Add one SDK serializer for `details.evidence`, including the bounded cause
   rule above, and extend `_identity_details` only with safe coordinates.
   Preserve `source_type`, existing error classes, `details.phase`, and current
   `as_dict` schemas. Remove the unreachable `ProjectionSyncError` member from
   the later generic-refusal tuple after its dedicated mapping.
3. Route Arrival `sync_target` through normalization and retain search sync's
   existing normalization boundary; classify effects from wrapper evidence.
   Leave unmatched `TypeError` and `ValueError` direct engine exceptions, as
   they are today; do not manufacture a broader compatibility promise.
4. Separately annotate declaration preparation/refusal with explicit
   preparation proof and
   preserve `ProjectionBehind`'s chained coordinates. Do not turn every nested
   `ContractRefusal` into a known-uncommitted public refusal.
5. C8b is implementing serialization of `SourceTierCollectionFailed` terminal
   evidence in the current source slice; C2 only fixes the shared object shape
   and documents the source tier result as the structured equivalent rather
   than forcing it through a scalar error class. Defer broad
   ordinary/batch/init/restore reshaping until a concrete mismatched public
   classification is found.

**Recommendation:** add optional `details.evidence` now. Existing error DTOs
already expose extensible `details` mappings; this preserves their v1 schema,
outcome and source type. Reserve a v2 envelope only for a later incompatible
change, such as moving evidence out of `details` or changing existing outcome
names.

## Acceptance tests

- A projection maintainer failure inside catch-up serializes
  `entered/unknown`; a search `query.open_snapshot`, provider acquisition, or
  pre-build `maintenance.coverage()` failure after
  target selection serializes `not-entered/not-attempted`; a failure after
  `build` enters serializes unknown unless its adapter proves atomic none.
  Each includes target/before/observed-after or coverage and causal type.
- Assert the attempt/state invariant and the bounded causal serializer:
  `.cause` before `__cause__`, two nodes maximum after outer, cycle guard,
  512-character truncation marker, and no context/payload serialization.
- A later valid projection advance reports actual `P >= target`, preserves its
  target, and does not claim a full row audit.
- `sync_target` and search sync preserve the same causal/effect evidence as
  their direct SDK-normalized counterparts; cancellation identity and cause
  chains remain intact.
- Declaration preparation with `ProjectionBehind` exposes its preparation
  phase and causal coordinates without claiming a custody append.
- Unknown append, unwitnessed append, post-commit projection failure and a
  no-op respectively retain planned IDs/H, an actual Commit only when supplied,
  and only the effects each operation proved. A mint-level `NotWitnessed`
  retains its resulting head with `commit=None`.
- A two-tier source run keeps the first tier Commit after a second-tier stale,
  unknown, collector, or dispatch failure; collected observations and lifecycle
  IDs remain inspectable without automatically re-running the collector. An
  incomplete C8b collection terminal has paired partial `(Fact, id)` evidence
  and no invented lifecycle ID.
