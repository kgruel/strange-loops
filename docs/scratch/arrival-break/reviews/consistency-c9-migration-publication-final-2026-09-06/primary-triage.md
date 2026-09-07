# Primary triage — ACCEPT

Fable 5.1 LOW accepted the frozen implementation and proposed adoption design.
No blockers were reported. Primary concurs. Packet/source hashes matched before
these maintained documentation clarifications; production and tests are unchanged.

Accepted non-blocking clarifications:

- Exact already-published resume skips descriptor replacement but regenerates,
  re-signs, and replaces the report. Different tool_version changes its body.
  README and report now state this; no immutable-report promise is made.
- Prior sidecar descriptors lacking explicit lineage/role refuse under the new
  existing-descriptor guard. README names that boundary without recommending a
  blind edit or calling those stores adopted.
- Registry-forming signatures for the first adoption are required to verify in
  ARRIVAL_DOMAIN. This is not only a fixture convention: the old production CLI
  calls custody.arrival_signer_for (apps/loops/src/loops/commands/store.py:836),
  whose implementation uses ARRIVAL_DOMAIN (libs/custody/src/custody/signing.py:331-346).
  A custom sidecar signer that does not meet that contract is refused at adoption;
  no claim is made that structurally valid historical logs prove authorship.
  Separate report-domain/versioning work remains distinct and explicit.
- Baseline-only sidecar offsets were removed from the baseline-gap paragraph.

Deferred non-blockers, retained as limitations/worklist:

- Preflight the effective store-clause shape before staging to reduce avoidable
  staged artifacts. Current late refusal is honest and never overwrites a changed
  descriptor at the check points.
- Normalize raw parse/decode errors in the quarantined sidecar. No new SDK error
  contract is promised for these old sidecar entry points.
- Report parent-directory fsync and a durable cutover intent are separate work.
  The implementation claims no arbitrary power-loss transaction across artifacts.
- A historical through=S report verifier would make migration evidence checkable
  after adoption or later writes. Current verifier's exact-live-head requirement
  is documented; it is not silently weakened here.

Compatibility: exported edit_vertex_store_clause now requires lineage and
expected_original. run_migration's signature is retained; old CLI caller tests
pass. Runtime adoption remains unimplemented, and no real store copy was migrated.

Validation: combined migration/integration76, architecture101, legacy CLI9,
scoped Ruff and whitespace. Native logs are archived; reviewer did not execute
these tests. In-process seam failures/seeded partial state are not process-kill
claims. Prior setup/recovery production is untouched and remains uncommitted.
