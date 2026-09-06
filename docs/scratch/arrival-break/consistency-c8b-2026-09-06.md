# C8b collection ownership and evidence — September 6, 2026

Implemented on `arrival/finish` after checkpoint `cfb26920`, using Sol for
engine implementation, Luna for independent engine regressions, Terra for C2
design and independent review, and root for SDK integration and judgment.
Final review status is recorded in
[primary triage](reviews/consistency-c8b-c2-2026-09-06/primary-triage.md).

## Behavior

Collection now allocates an ID before retaining an observation, storing both
in one pair. ID allocation and lifecycle construction failures are coordinator
failures; they do not become collector error lifecycle facts. The prior code's
mismatched lists already failed strict pairing before append, so this correction
does not imply that those mismatches previously corrupted durable history.

Every owned asynchronous iterator and its distinct iterable owner receives
an available `aclose()` attempt, on exhaustion, invalid output, collector error,
bookkeeping error, or cancellation. Ordinary cleanup failures preserve an
existing primary failure. Cleanup interruptions still allow a close attempt on
the remaining owner; an existing control-flow exception retains its identity.
An otherwise successful collection whose cleanup fails becomes a coordinator
failure. Closing Python resources does not undo external effects or guarantee
subprocess termination. There is no guarantee against indefinitely blocking
cleanup or repeated external cancellation.

`collect_source_tier` owns its tasks. On coordinator failure it cancels
unfinished siblings and awaits settlement before freezing evidence into
`SourceTierCollectionFailed`: current tier index/basis, completed sources,
failed sources, cancelled sources, original cause, and paired partial output.
An incomplete attempt has no invented lifecycle fact. `execute_source_invocation`
returns this terminal with earlier bases and actual durable tiers intact; it
does not append the failed current tier. Caller cancellation remains a raised
control-flow exception, not a normal incomplete return.

If final invocation-summary construction fails after the tier was fully
collected, the existing known-uncommitted tier result retains those observations
and earlier commits. A source's own reported error retains the existing
error-lifecycle behavior when the tier can otherwise be committed.

## SDK surface

`run_sources` returns terminal category `collection-failed` with original
`source_type`/`cause_type`. `terminal.details.collection` holds `tier_index`,
`basis`, `custody="not-attempted"`, and `completed_sources`, `failed_sources`,
`cancelled_sources`. Partial sources use existing serializable source/fact DTOs
with status `bookkeeping`, `cleanup`, or `cancelled`, paired fact IDs, no
lifecycle fact, and no claimed lifecycle ID. Completed siblings retain their
actual planned lifecycle evidence, but none of this current tier is durable.

This terminal collection evidence is separate from `known_uncommitted`, which
continues to describe a fully collected tier. Earlier committed tiers remain
in the normal `tiers` list. Neither no custody attempt nor known-uncommitted
custody authorizes safe recollection of external effects.

## Scope

Production changes are limited to engine source collection and its SDK result
serialization. The SDK README documents the additive terminal evidence.
[C2 evidence design](consistency-c2-evidence-design-2026-09-06.md) recommends
future operation-local phase and per-resource effect evidence under a versioned
`details.evidence` object. That shared schema and broader normalization are not
implemented here; C8b's `details.collection` remains operation-specific.

Validation is recorded in the [validation report](consistency-c8b-validation-2026-09-06.md).
All stores used by tests are disposable fixtures; no live stores, credentials,
wire profiles, or backend protocols change in this slice.
