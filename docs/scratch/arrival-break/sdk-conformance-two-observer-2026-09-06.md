# Public SDK conformance: two observers and descriptor relocation

Status: complete, natively validated, and accepted by Fable-low and primary
review on `arrival/finish`, included in the checkpoint based on `a36487dc`.
This is the first
workload-conformance slice preceding C9's
SDK/minimal-CLI transition and deliberate legacy retirement.

## Contract under test

An application prepares two explicit mapped bindings, initializes Arrival with
one observer, introduces the other's public key, and emits a mixed-author batch.
The write receipts, public fact reads and prefix
verification must describe the same lineage and accepted history. Observer
labels select the corresponding public authorization; the explicit local
namespace selects custody material independently of the descriptor filename.

Moving and renaming the descriptor while retaining an absolute store location
must preserve the selected residence, lineage, history and mapped keys. A newly
constructed provider must support a subsequent authorized write from the moved
descriptor. This does not imply that moving a descriptor relocates its store,
rewrites relative locations or adopts another lineage.

`verify_target` verifies grammar, dense ordinals, lineage and the hash chain
through its returned prefix. It does not establish signature validity, key
trust or projection agreement. The workflow compares read and write evidence
explicitly; existing mapped-signing tests separately cover domain-separated
signatures and the engine's captured authorization checks.

## Scope and evidence

Sol owns the executable SDK workflow, Terra independently audits relocation and
updates public guidance, Luna validates coverage and package behavior, and root
integrates the result and triages the frozen Fable 5.1 LOW review. Every test
process isolates XDG state/config and `LOOPS_HOME`; all stores and keys are
disposable fixtures. No live migration or legacy retirement is part of this
slice.

The executable
[workload](../../../libs/sdk/tests/test_arrival_mapped_workload.py)
chains initialization, grant, batch and final-write heads. It checks current
projection evidence against captured custody, exact returned authors/payloads,
and the unchanged history and persisted key references after descriptor
relocation. Batch receipts share the enclosing result's captured head, witness
and projection evidence; the shared commit belongs to the batch result.

Three refusal controls exercise the same lifecycle: Bob's binding before his
grant, another namespace's Alice key, and an independently bound `Alice` label
that was never granted. Refusals retain the available typed evidence and leave
the verified head unchanged. A final successful write and exact fact listing
also check that those attempted facts never entered the query result.
The `Alice` control observes declaration admission before credential lookup;
a separate public resolution checks its case-distinct persisted key reference.

No production defect has been found by this pass. The changes are executable
conformance coverage and public SDK guidance.

## Validation and review

- Final full SDK suite: **579 passed**, 20.88 seconds.
- Architecture suite: **101 passed**, 5.49 seconds.
- Existing mapped-credential tests plus the new workload: **13 passed**.
- Scoped Ruff and maintained-source whitespace checks: passed.

The workload uses public SDK operations and the public credential-request
types. It opens no engine ledger or private custody file directly. A descriptor
rename and byte comparison express the caller's relocation, while custody
preparation remains explicit. This bounded flow exercises fact reads and prefix
verification, not every SDK read surface or concurrent/multi-machine relocation.
Existing domain-signature tests supply complementary coverage, rather than a
claim that `Full` cryptographically authenticates authorship.

The initial [Fable-low review](reviews/sdk-conformance-two-observer-final-2026-09-06/final-findings.md)
and [primary triage](reviews/sdk-conformance-two-observer-final-2026-09-06/primary-triage.md)
returned **REVISE**: the wrong-namespace assertion could accept a provider-load
failure without reaching captured authorization. Root reproduced the false
positive by replacing that namespace's resolver with an unconditional failure.
The correction asserts the specific authorization reason and request and a
distinct alternative public key. It also makes ordinal advancement explicit.
Focused correction validation: **13 passed** /1.09s and scoped Ruff passed.
The original test accepts the broken-resolver probe; the corrected test rejects
it even when a preflight resolution succeeds before the injected write-time
failure. Only test assertions changed after the full suites. The focused
[follow-up review](reviews/sdk-conformance-two-observer-followup-2026-09-06/followup-findings.md)
and [primary triage](reviews/sdk-conformance-two-observer-followup-2026-09-06/primary-triage.md)
both returned **ACCEPT**, with no remaining blockers. Final reviewed code and
test hashes match; only status and handoff documentation changed afterward.

Final full reruns confirmed SDK **579 passed** /17.53s and architecture
**101 passed** /6.02s before the review correction. The first review packet
contains the earlier full measurements above; supplemental rerun logs are
archived separately. No production files changed. Tests, guidance and review
evidence are included in this checkpoint; nothing pushed.

## Next bounded workflows

1. Interrupt a declaration edit, recover, inspect, and continue writing.
2. Run sources with partial failure, inspect persisted tiers, and identify what
   can safely resume.
3. Export a captured prefix, restore forward, verify, explicitly sync, and read.

Maintenance/transfer completion, adoption and C9 retirement remain separate
roadmap work; passing this workflow does not close them.
