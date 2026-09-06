# Arrival completion stage 3E — SDK ordinary emit and preview

Date: 2026-09-05  
Status: implementation complete; adversarial review approved

## Result

The existing `preview_emission` and `emit_fact` SDK names now resolve explicit
Arrival descriptors before legacy target probing. Both require the supported
Authority role through the engine writer. Descriptor-backed aggregates refuse
before any legacy store path, and `emit_batch` explicitly refuses Arrival until
the bounded batch planner lands.

Arrival preview calls `prepare_ordinary_write` only. The engine reconstructs
the effective declaration, facts, ticks, admission grant, and physical genesis
custodian from one attested CURRENT snapshot. The locator vertex contributes
residence. Successful and refused previews use that same-snapshot declaration
for strict-kind, observer, and fold metadata. Missing projections refuse and
are not materialized. Preview never executes a plan.

Arrival emit uses the same preparation, then calls `execute_ordinary_write`
once against the captured full head. A successful append injects
`sync_projection(..., through=commit.after)` as the explicit post-commit step.
The returned v2 receipt carries the descriptor, captured head, durable commit,
witness state, and projection outcome. It does not invent fold delta metadata
the neutral writer does not provide: `state_change` and `delta_count` are
`None` on Arrival success. `as_dict` reports commit heads, record count, and
durability without serializing record bodies.

An equal `id_override` retry is planned as already present and performs no
append or projection request. Its receipt says `stored=False`, `commit=None`,
`witnessed=None`, and `projection="not-requested"`.

Engine boundary errors pass through `sdk.errors.normalize_exception`. SDK
types distinguish a non-committing Arrival refusal, an append whose outcome is
unknown, a known durable commit whose witness failed, and a known durable
commit whose projection sync failed. The latter three retain stable fact/tick
IDs, captured head, and available commit heads in JSON-safe `as_dict` output.
The unknown path is called once and never retried automatically.

## Acceptance coverage

Real temporary Arrival fixtures cover snapshot-derived preview, locator policy
changes after declaration adoption, observer refusal with physical bytes
unchanged, successful append plus projection sync plus CURRENT lookup, an
idempotent retry, replica refusal, missing-projection preview refusal without
materialization, descriptor-member aggregate refusal, and batch refusal before
legacy probing. They also cover default credential lookup without key creation,
strict-kind diagnostic compatibility, a real boundary tick and two-record
commit, and a CAS race that performs exactly one refused execute. Injected
engine outcomes cover post-commit projection failure, unwitnessed commit, and
commit-unknown one-attempt identity.

## Validation

- Full SDK suite before the final review supplement: `373 passed`.
- Post-review focused emit/error/type suite: `39 passed`.
- Ruff and ty over the changed SDK source and focused tests: passed.
- Rule 18 focused architecture suite during the stage: `35 passed`.

The required Fable 5.1 review requested changes on six bounded issues. All six
were corrected and regression-tested. Its capped supplement returned
`APPROVE`; two additional source-backed low findings were corrected, while one
defensive suggestion was declined because `OrdinaryWritePreparationRefused`
requires a non-null `VertexFile` by construction. The full receipt and exact
model metadata are in
`reviews/sdk-ordinary-emit-fable-2026-09-05.md`.
