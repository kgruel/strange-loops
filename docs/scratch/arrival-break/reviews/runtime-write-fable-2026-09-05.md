# Runtime writer adversarial review — 2026-09-05

## Invocation

Fable 5.1 reviewed the final static packet through the verified local `claude`
CLI with `claude-fable-5-1[1m]`, safe mode, restricted tools, no session
persistence, and JSON output. The packet and raw result are at
`/tmp/loops-arrival-review/runtime-write-prompt-2026-09-05.md` and
`/tmp/loops-arrival-review/runtime-write-result-2026-09-05.json`.

The result's top-level `model` is null, but `modelUsage` records
`claude-fable-5-1` (15,691 output tokens, including 13,207 thinking tokens),
with a small Haiku routing prelude. The returned review was therefore a
substantive Fable 5.1 run. It reported three defects, five suggestions, and
`Not ready to merge` before the dispositions below.

## Disposition

1. **Source-checked correction.** The reviewer inferred that a vertex-level
tick resets every loop. The actual `_fire_vertex_boundary()` snapshots all loop
states and resets only `_vertex_period_start`; `Vertex.replay()` then restores
the last vertex tick timestamp. Hydration now records that timestamp too,
without inventing loop resets. The regression pins retained loop state and
period timestamp after a vertex tick.

2. **Accepted and fixed.** Hydration now refuses `combine` declarations as
well as `vertices` and `discover`, before materialization/admission. Stage 3A
has no aggregate or multi-lineage writer.

3. **Rejected: clamp is ratified semantics.** A projection can advance after H
capture normally. Query rows are bounded by H; membership validation of the
later watermark permits clamping the public/execution basis back to H. A
subsequent exact-H append correctly refuses if custody advanced. This preserves
the accepted snapshot model and is covered by the projection-advance regression.

4. **Rejected: unsigned Arrival tick envelope is source-required.** The fresh
tick retains its inner row signature and chain commitment, while its Arrival
envelope has `signature=None` and observer equal to physical-genesis custodian.
This is existing `ArrivalStore._write` policy, not a gap.

5. **Rejected: generic adapter exceptions remain unknown.** Once append is
entered the runtime has no portable proof that an adapter did not persist.
`WriteCommitUnknown` therefore retains planned identity for reconciliation;
typed `ContractRefusal` and `NotWitnessed` remain distinct.

6. **Rejected: exact signed row equality is the accepted retry policy.** The
caller's explicit ID and current signing material must reproduce the exact fact
body; the writer neither weakens that comparison nor treats an unverifiable old
signature as equal. The supported path performs it before new-fact admission so
removed observers still obtain a no-op retry.

7. **Deferred performance suggestion.** Bounded hydration currently reads facts
more than once for explicit-ID retry and planning. It is correct but not
optimized; batch work can thread captured rows through planning. Execute's
private query handle is lifecycle symmetry with registry open, not public read
capability.

8. **Accepted cleanup.** The review noticed duplicate admission derivation; the
helper was removed and the supported preparation regression now covers the sole
derivation path.

## Recheck

After supported fixes, 225 focused engine tests passed across runtime writer,
consumer, tick-chain, canonical-audit, and compiler suites. Ruff passed for the
new runtime/commitment modules and runtime tests; `git diff --check` passed.
Both relevant architecture suites passed (36 tests). Root's broader cross-stage
engine run reported 2,371 passed and one skipped.

## Limits

Stage 3A handles one ordinary fact and at most one local boundary tick. It does
not initialize declarations, batch, execute sources, write through
children/aggregates, or materialize projections. Projection maintenance stays
an explicit postcommit operation.
