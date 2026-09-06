# Source execution handoff

Status: inventory and constraints for the slice after atomic batch acceptance.
No source execution behavior is implemented by this note.

`engine.executor.Executor` currently reads cadence through `vertex._store`,
evaluates pending boundaries, schedules dependency tiers, streams source facts
through `vertex.receive`, and records both `_sync.<kind>` and overall `_sync`
lifecycle observations. `VertexProgram.sync_async` dispatches resulting tick
run clauses. SDK currently has no equivalent source-execution operation;
`sdk.sync_target` means projection maintenance and must retain that meaning.

The port needs explicit decisions at three boundaries:

1. Capture effective declaration, source configuration, cadence evidence and
   runtime state through the same attested snapshot. Replace the private store
   dependency with bounded query evidence. Preserve dependency-cycle refusal,
   tier ordering and the meaning of skipped/error observations.
2. Collect source output separately from ledger mutation, then use the accepted
   batch writer for the chosen atomic unit. Define whether a unit is a source,
   tier or full invocation before implementing it. Source execution may have
   external effects; a refused ledger CAS cannot roll those effects back.
   Retain collected observations and stable planned identities for a failed
   append. Never automatically reexecute a source after stale or unknown
   durability. If earlier units committed, later failure must carry their
   receipts rather than report the invocation as wholly uncommitted.
3. Dispatch tick run clauses only after their tick is durable. Dispatch itself
   is another effect with a separate failure outcome. Do not claim exactly-once
   dispatch merely because the ledger append is atomic.

The current executor applies the explicit strict bypass only to its lifecycle
observations. Domain facts do not inherit that bypass. The new supported
factory must derive declared admission from captured declarations, preserving
the distinction between source authorship and the executor's own observations.

Pending-boundary evaluation is also meaningful: historical replay suppresses
boundary writes, while a source run may intentionally evaluate eligible
boundaries. It must not accidentally emit a second already-recorded boundary
because hydration lost period/count/tick context.

Initial acceptance should use fake collectors with invocation counters and a
real temporary ledger: dependency tiers, source failure after yielded output,
invalid later observation, stale CAS, unknown postappend failure, and a
postcommit dispatcher failure. Every case must state which observations are
durable and prove that no implicit collector rerun occurred. Child/cross-store
execution remains explicitly unsupported until its multi-commit semantics are
implemented; a single-lineage batch is not cross-store atomicity.
