# Source execution after atomic batch — 2026-09-05

## Decision

Use **one dependency tier** as the custody atomic unit. The initial CURRENT
capture evaluates *all* cadence predicates and computes qualifying sources and
DAG tiers before any collector runs, matching `Executor.sync_async`. Those
qualification decisions and frozen source inputs remain fixed for the
invocation. The first tier is collected and its domain observations plus
per-source `_sync.<kind>` lifecycle observations are appended in one supported
batch commit.

Preserve the executor's overall `_sync` observation as well. On a completed
invocation, append it in the last tier's commit with accumulated run/skipped/
error/count evidence. With no qualifying sources, a lifecycle-only commit
still records the invocation and may include an eligible pending boundary.
An invocation interrupted by a refused or unknown tier reports its incomplete
terminal lifecycle explicitly; do not invent a successful summary or append a
second recovery history automatically.

Whole-invocation ledger atomicity is technically possible despite external
collector effects, just as tier atomicity is. Tier commits are chosen for a
smaller bounded recovery unit and honest partial-completion reporting: after a
durable tier, its receipts are useful evidence even if a later capture or
collector refuses. A single-source unit would fragment the current tier
structure and lifecycle evidence. Tiers preserve concurrent collection within
a dependency level and deterministic source-list ordering in their batch.

This is custody atomicity, not external-effect rollback. A stale or unknown
append after collection retains collected output and planned IDs for
reconciliation; it never restarts a collector automatically. If tiers 0 and 1
committed and tier 2 later fails, the result names tiers 0 and 1 as durable and
tier 2 separately. It never reports the invocation as wholly rolled back.

## Capture and planning

`prepare_source_invocation(registry, descriptor, locator, *, force=False,
observer, credentials, collector_factory)` opens the existing Authority registry path and
a CURRENT read snapshot. It uses the same effective declaration factory as the
runtime writer, including anchor/lineage validation and storeless hydration.
The capture DTO contains:

- `ReadBasis`, effective declaration identity/documents, and physical genesis
  custodian;
- all snapshot facts/ticks needed to reconstruct fold, period, and chain state;
- a `CadenceEvidence` value per source: mode, evaluated-at time, latest matching
  successful `_sync.<kind>` fact identity/timestamp, trigger matches, and the
  resulting qualified/skipped decision;
- ordered source descriptors, dependency graph, and tiers; and
- pending-boundary evidence (the bounded ticks/facts and the candidate outcome).

Capture must precede collection. The current `prepare_batch_write` opens its
own snapshot, so invoking it only after collection would silently replace this
captured basis. Extract a supported immutable runtime capture and a planner
that consumes it; keep the public ordinary/batch factory behavior by composing
those steps. Source planning uses its original captured Head through append.

Source environment values are residence/ingress rather than declaration
payloads. Reuse the existing `declaration._reattach_ingress` occurrence/count
rules when compiling the effective source configuration: only declared keys,
only matching block/command occurrences, no cross-block fallback. Preserve
source-pin verification before running collectors. Hydrating the runtime's
fold state alone does not yet perform either operation.
`verify_source_pins(vertex_path)` currently reopens a legacy store; extract its
document-based file-hash checks and feed the captured documents instead. Do
not call that legacy wrapper from the Arrival capture path. Template-generated
loop specifications must also be retained when constructing the candidate,
matching `load_program`'s `compiled.specs.update(template_specs)` behavior.

Cadence currently calls `latest_by_kind_where` on a private store. The source
slice replaces that with a pure evaluator over snapshot facts: elapsed finds
latest `_sync.<kind>` whose `status == "ok"`; triggered checks the captured
trigger facts; always qualifies. Error lifecycle facts do not reset an elapsed
clock, matching current cadence tests. Cycles refuse before any collector runs.

Pending boundaries are planned once against the hydrated candidate before the
first collector. A historical recorded tick remains replay evidence, not a new
pending tick. Stage 3B's batch API does **not** yet accept a preplanned pending
tick alongside source inputs; source implementation requires that explicit
planner extension, preserving its exact chain/window evidence and placement
before the tier facts. Once available, a pending tick belongs at the front of
the first tier commit, or in a dedicated bounded boundary-only commit when no
source qualifies. It is never re-evaluated from a legacy store or dispatched
before durability.

## Tier collection and DTOs

`collect_source_tier(capture, tier, collector_factory) -> CollectedTier` has no
ledger handle and no append capability. It preserves input source order in its
output even though collectors run concurrently. Each `CollectedSource` holds
source identity, every yielded domain `Fact` in yield order, `status` (`ok` or
`error`), error evidence (`stderr`, return code, exception name/message), and
its generated `_sync.<kind>` fact. The tier also holds a stable invocation ID,
collector attempt count (one), and any pre-tier pending tick.

Domain facts use admission derived per observer from the captured effective
declaration. Only executor lifecycle facts use `admit_undeclared=True`, as the
current executor does. Source-produced facts never inherit that bypass.

The invocation caller supplies the observer for executor lifecycle facts,
matching ordinary SDK emission's explicit authorship choice. Do not infer it
from the vertex display name or substitute the physical custodian. Check that
observer and its known lifecycle kinds against captured admission before
running collectors. The strict-kind bypass does not bypass observer grants.

A source error after yielding facts retains those yielded facts and appends its
error lifecycle observation in the same tier batch; this matches the present
partial-error behavior. An invalid yielded fact, declaration refusal, or batch
preflight failure prevents the whole tier append, with zero ledger records.

`prepare_collected_tier(capture, collected) -> BatchWritePlan` calls the batch
writer with ordered `BatchFactInput`s. It must include every lifecycle fact and
(the required future extension) pending tick evidence; it must not manufacture
a partial snapshot or drop planned ticks. `execute_collected_tier` returns
`TierCommitted` (shared Commit, per-item IDs/ticks, lifecycle outcomes) or
`TierAppendUnknown` (captured H, all planned IDs/drafts, collected tier,
cause). `NotWitnessed` retains its actual Commit. Neither stale CAS nor unknown
calls `collector_factory` again.

Before collecting each later tier, explicitly synchronize projection, acquire a
new CURRENT capture, and require its effective declaration identity/documents
to equal the initial invocation's frozen declaration. A declaration change
refuses before collection and retains prior durable receipts. Independent
ordinary appends may be incorporated by this next capture; they do not alter
the invocation's initially fixed cadence qualifications or source inputs.

`SourceInvocationResult` contains initial and per-tier bases, skipped evidence,
collected but uncommitted tiers, durable tier receipts, error lifecycle IDs, and
an optional terminal refusal/unknown. This makes partial completion inspectable.

## Postcommit dispatch

A dispatcher is invoked once only after run-clause ticks appear in a durable
tier Commit. `DispatchFailed` carries that Commit, tick IDs/names/commands, and
cause. It does not retract custody or rerun collection. Without a durable
dispatch receipt and retry protocol, this design makes no exactly-once or
at-least-once delivery guarantee; it records one attempted postcommit dispatch
and explicit failure/unknown outcome.

`sdk.sync_target` remains projection maintenance. A later SDK source operation
may call this source API, but it must not overload sync-target or add authority
modes. Current child-graph/cross-store execution refuses before collection: one
lineage's batch cannot claim atomicity across independent lineages. This is not
a blanket restriction on same-lineage composed views; those remain valid when
the effective declaration and captured physical lineage are valid.

## Acceptance and open choices

Test fake collectors with counters plus a real ledger: tier ordering and
captured cadence; source error after output; invalid later output; stale and
unknown append with no rerun; recorded versus pending boundary; dispatcher
failure after a durable tick; and partial prior-tier durable receipts.

Accepted choices: a no-qualified invocation with a pending boundary uses a
dedicated bounded boundary-only commit, and independent sources in a tier retain
source-list order for batch IDs despite concurrent collection. The remaining
implementation prerequisite is the batch planner extension that admits the
preplanned boundary tick with its exact chain/window evidence.
