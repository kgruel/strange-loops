# Primary triage: C9 first writer transition

Verdict: **ACCEPT**. Fable 5.1 LOW accepted with no blockers. Root independently
reviewed the implementation, tests and native results, and agrees. The frozen
packet and source manifest matched at review launch and closure.

The central evidence is the public subprocess init/emit/declaration/mixed-author
batch/read/verify lifecycle; exact predecessor heads and complete rows; input,
wrong-key and legacy refusal controls; unsigned optional binding with unchanged
custody; and deterministic SDK-boundary tests for committed outcomes, recovery
routing and post-precheck legacy replacement. The latter are not process-crash
coverage. Full SDK590, architecture101, final CLI20 and engine declaration14
passed. The independent installed-wheel workflow passed outside the checkout.

## Optional findings

1. File alias spelling: accepted clarification. Absolute aliases and their
   resolved real paths are different declared location strings; changing that
   spelling is not an ordinary declaration residence edit. The new helper now
   exactly shares descriptor_for's path convention. The old rule already
   refused edits opened under an absolute alias and could accept an alias
   proposal against a resolved descriptor; do not generalize the reviewer’s
   directional example as an existing supported relocation contract. No
   storage identity redesign or backend-wide normalization is part of C9.
2. Mapping coercions: accepted documentation clarification. CLI passes object
   items to the SDK, whose existing coercion/default rules remain. Origin is
   stringified (including null to "None"); kind is passed through, so the
   reviewer’s shorthand is not proof every non-string kind is accepted by
   later runtime validation. No new semantic coercion policy added.
3. Inventory reference: corrected the stale dispatch line link.
4. Exit 2: README now includes SDK invalid-input/configuration cases, including
   missing founding credentials. No exit behavior changed.
5. Wheel hashes are native primary evidence, not reviewer-executed checks.
   Root compared installed main/sdk emit/engine declaration bytes to source;
   the recorded hashes agree. Initial harness assertion normalized only one
   side of an environment-prefix comparison; corrected harness passed the
   same wheels. Product code was unaffected.

Only these documentation clarifications and maintained status/handoff prose
changed after the frozen review. No production or test corrections were
required. No follow-up Fable pass needed. No live stores migrated, legacy
runtime paths deleted, C9 commit made, or push performed. Setup/recovery and
subsequent named-consumer retirement remain separate next work.
