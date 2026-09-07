# D0 → D2: explicit credential requests and persisted bindings

Status: implemented and validated on `arrival/finish`, based on `39bf05d7`;
final Fable-low review and primary triage accepted; no remaining blockers.
Included in the D0/D2 checkpoint on `arrival/finish`; nothing pushed.
All credentials and stores used for testing are disposable fixtures.

## Result

`MappedCredentialProvider` is an explicit alternative to the existing custody
provider. Exact namespace/observer strings select a persisted opaque key
reference. FACT, ARRIVAL, and TICK requests carry distinct domains and purposes;
the engine separately captures and verifies the authorizing history. Ordinary,
packed-batch, source-tier, and declaration preparation now support that path.

Initialization loads a pre-created binding. Observer grants require an explicit
public key when using mapped credentials. Creation/import/reuse/recovery are
separate custody operations, with serialized mutation, durable pending intents,
and complete-file publication. Legacy flat/nested import retains ambiguity and
alias refusal and leaves the original key files untouched. No read, preview,
or signer load implicitly creates or imports a binding.

The default provider and raw legacy callbacks retain their compatibility
behavior. Mapped credentials refuse on legacy writers; partial mapped
configuration cannot fall back to legacy callbacks. Arrival wire formats and
initialization intent recovery remain unchanged. Public guidance is in
[SDK README](../../../libs/sdk/README.md) and
[custody README](../../../libs/custody/README.md).

## Design review and implementation corrections

The [Fable-low design review](reviews/consistency-d0-d2-design-2026-09-06/design-findings.md)
returned **REVISE**. [Primary triage](reviews/consistency-d0-d2-design-2026-09-06/primary-triage.md)
accepted its three findings: retain self-key introduction under an older
valid key; choose one coherent pending-intent/concurrency protocol; and retain
unsigned receipts before the signed era when no receipt observer is configured.
The amended [design](consistency-d0-d2-design-2026-09-06.md) records these rules.

Independent root probes reproduced five failures in the first custody draft:
recovery without an intent minted a binding; completed creation skipped material
validation; reused tokens poisoned another slot; import recovery lost its
provenance; and a private-before-public interruption could not resume. A later
probe caught replacement-key creation during recovery of a missing published
key. All seven initial independent recovery regressions pass. These were development-draft probes,
not regressions against the pre-D0 checkpoint.

Integrated SDK validation caught five legacy kind-operation call sites missing
the newly required guard argument. Those were fixed and the full SDK passed.
A final malformed-evidence probe found a JSON serialization failure in refusal
reporting; public fields are now sanitized and four regressions pass.

The first [implementation review](reviews/consistency-d0-d2-implementation-2026-09-06/implementation-findings.md)
returned raw **ACCEPT**, but root reproduced two recovery failures and overrode
that disposition: published material could contradict retained intent, and an
interrupted pending/index publication could allow a reused token to publish a
second slot before refusing. Both were fixed. The focused recovery review then
returned **REVISE** for a fresh-token variant of the first problem. Completed
slots now validate their own retained intent regardless of the caller’s token.
The [final review and primary triage](reviews/consistency-d0-d2-final-2026-09-06/primary-triage.md)
accepted the correction with no remaining blockers.

## Measured validation

- Full engine: **2,611 passed, 1 skipped**, 70.50 seconds.
- Latest full SDK: **578 passed**, 22.17 seconds.
- Final full custody: **81 passed**, 0.55 seconds.
- Full signing primitives: **40 passed**, 5.13 seconds.
- Architecture: **101 passed**, 7.57 seconds.
- Scoped Ruff across every changed Python file and `git diff --check`: pass.

The engine suite predates two test-only formatting corrections (import spacing
and identical adjacent SQL string literals); engine production did not change.
The latest SDK suite includes the guard correction, malformed-evidence fix,
and first recovery corrections. It predates the final completed-slot
fresh-token and filesystem durability corrections, covered by the final custody
run. The final 81-test custody raw log is retained with the durability review.
A combined custody/sign run with importlib collection failed to import the
multiprocessing test module in spawned children; the normal separate package
runs above pass. This harness failure is retained in the evidence.

Every test process used isolated `XDG_STATE_HOME`, `XDG_CONFIG_HOME`, and
`LOOPS_HOME`. Source hashes and raw logs are retained for review. See the
[validation report](consistency-d0-d2-validation-2026-09-06.md) for coverage and
limits. No real keys or live project stores were migrated.

## Deliberate limits

- Mapping is opt-in; the default provider is still locator-based compatibility.
- A binding is domain-independent in v1; signatures remain domain-separated.
- Missing author bindings may remain unsigned where the current policy permits.
- Inner receipts use current declared keys, while authored records use verified
  lineage history through H for successor use. Outer ticks remain unsigned and
  retain the physical genesis custodian.
- Plans retain successful binding evidence, not a complete attempt audit.
- Key-history scanning is conditional on mapped credentials and may be O(N).
- The filesystem provider requires POSIX flock, hard-link, and fsync semantics.
- An import without a copied private candidate needs its source re-presented
  with the same token; a copied candidate can recover without the old source.
- No automatic key cleanup, local binding rotation, revocation, global identity,
  default CLI transition, or Arrival initialization-intent schema change.
- Exact retry signature equality remains the existing contract; rotation-aware
  retry ergonomics is a separate follow-up.

## Review handoff

D0/D2 has final Fable-low **ACCEPT** and primary **ACCEPT**. Root's final
inspection found missing parent-directory fsync and a retry that accepted an
unsynced binding link. Those were corrected. The durability review then caught
the same missing sync in imported-key recovery; that branch and its regression
are complete. The [final durability triage](reviews/consistency-d0-d2-durability-followup-2026-09-06/primary-triage.md)
closes the slice with no remaining blockers. Frozen packets, raw findings, triage, validation logs,
and source hashes are retained in the linked review directories. Sol owned
engine integration, Terra owned custody/SDK, Luna owned public-flow tests, and
root owned integrated review and independent recovery/refusal probes.

This checkpoint closes D0/D2. Next is public SDK workload conformance, starting
with the two-observer lifecycle recorded in the orchestration handoff. Remaining
work is the broader workload
conformance and maintenance/transfer/adoption pass, followed by C9 when its
retirement conditions are met. The default legacy provider remains supported.
