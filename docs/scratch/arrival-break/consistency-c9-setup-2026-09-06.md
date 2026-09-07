# C9: initialization recovery and credential lifecycle

Status: implemented and validated on `arrival/finish`, based on `50e37595`.
Fable-low correction review and primary verdict: **ACCEPT**. Initial B1 is closed.
No commit, push, live migration, or legacy retirement in this slice.

## Boundary decisions

Initialization recovery is a separate `init-recover TARGET` command. It calls
`sdk.init_vertex(target, store_type="arrival", recover=True)` without credentials,
backend selection, observer selection, or scaffold parameters. The SDK and engine
load the reserved descriptor, observer, declaration, and signatures from the
retained initialization intent. Recovery finishes that operation; it does not
choose a new lineage or sign a new initialization. Successful recovery removes
the intent. A subsequent recovery invocation refuses the missing intent without
starting another initialization.

Mapped binding mutation remains a separate local custody operation. SDK-owned
results serialize public binding coordinates and mutation outcomes. They carry
no Arrival Commit and no private key material. The exact namespace and observer
select a local slot; the explicit token identifies the durable operation. Receipt
observer selection belongs to subsequent writes and is not a binding mutation
argument. Existing read resolution remains read-only and can return no binding.

The process client exposes create, recover, bind-existing-ref, and import-legacy
through the corresponding public SDK provider methods. The SDK owns validation,
serialization and failure classification. The client performs one invocation and
preserves its result or error. It never scans private custody files, manufactures
an outcome, or performs an automatic retry. Import copies an explicitly selected
legacy key; it does not migrate a store or publish an Arrival descriptor.

## SDK outcome contract

`MappedCredentialProvider` keeps its four public method signatures and existing
result attributes. Those methods now return `CredentialBindingResult`, with
schema `loops.sdk/credential-binding/v1`, operation, namespace, observer, token,
key_ref, public_key, provenance, binding_created, and key_created. This changes
the concrete result type from the custody dataclass; callers inspecting that
concrete type must adopt the SDK result. Reusing an existing reference publishes
a binding, without implying new key creation or a vertex authorization grant.

SDK lifecycle errors are dedicated `CredentialBindingError` subclasses. They
replace exposed custody exceptions for these SDK methods; direct custody callers
are unchanged. `CredentialBindingConflict` and `CredentialBindingRecoveryRequired`
retain the attempted request coordinates and map to CLI status 4.
`CredentialBindingIncomplete` maps to status 6, retaining custody-supplied
key_ref/phase when available. Raw custody OSError/ValueError/TypeError cannot establish
that no mutation happened: they use the same incomplete family with phase
`unknown`, the source exception type, and the request coordinates. That fallback
does not claim an intent exists or supply a guessed key reference. Some failures,
such as an absent import source, consequently receive a conservative incomplete
outcome even though their current implementation fails before binding publication.
Simple invalid SDK argument shapes are rejected before the custody call.

The error's `recovery_action="reconcile"` is not an automatic retry command.
Recovery may require the exact retained token; an interrupted legacy import
without a published candidate may require repeating that explicit import with
the same token and source. A conflicting operation's attempted token is not the
token owning another pending intent. Exit status 4 also makes no blanket
zero-effects claim. No binding outcome fabricates an Arrival Commit.

## Evidence and validation

The process workload provisions its binding through `credential-create`, then
runs the actual `init` dispatch in an instrumented child process that exits with
`os._exit(75)` at the engine's `after-mint` hook. The parent retains the exact
genesis prefix and intent. A fresh `init-recover` process runs while the configured
custody directory is moved away, publishes the exact retained declaration, and
preserves the original ledger prefix and lineage. Repeating recovery refuses
with the intent gone and leaves both descriptor and ledger unchanged. Restoring
the original credential directory permits a signed emit whose Commit predecessor
is the recovered head; complete reads and structural Full verification account
for the result. This covers process termination at a durable hook, not arbitrary
power loss or a concurrent writer.

SDK lifecycle tests exercise actual custody hooks for incomplete publication and
for a raw OSError after the pending marker but before its token index. They retain
known versus unknown phase evidence and recover with the same token. Additional
checks cover wrong-token and key conflicts without mutation, corrupt persisted
public evidence without repair, idempotent results, explicit import/reuse, and
read-only resolution. A separate actual CLI subprocess injects an exception after binding publication.
It emits status 6 with exact SDK incomplete evidence, a wrong-token recovery
refuses with all persisted bytes unchanged, and a fresh exact-token recovery
preserves the complete key-file set and bytes. Same-token create replay is also
unchanged. This is an exception at a custody hook, not process termination.
CLI boundary tests separately check exact SDK delegation,
argument rejection, and serialization of a supplied incomplete error. Mocked
serialization is not process-crash evidence.

A fresh modular-wheel installation outside the checkout, with neither legacy
`loops` nor Painted installed, exercises credential create/replay/recover/reuse
then init → emit → declaration → read → verify. All four changed production
files match installed-source hashes. Every fixture uses isolated state/config/home
roots; only explicit text evidence is archived, never key/store fixture directories.

Final corrected validation: CLI **30 passed** /14.26s; SDK **599 passed** /29.17s;
architecture **101 passed** /16.00s; custody binding/recovery **31 passed** /1.33s.
Focused SDK compatibility **60 passed** /2.46s. Scoped Ruff and whitespace
checks pass. SDK and CLI suites and installed wheels were rerun after B1; the unchanged
architecture/custody boundary retains its prior passing suites.

## Initial review and B1 correction

Fable-low's initial verdict was **REVISE** for one accepted blocker: custody's
non-object JSON and malformed slot-identity checks raise TypeError, which the
SDK wrapper did not classify. Such failures escaped as CLI status 70 without
request/recovery evidence. The correction adds TypeError to the existing narrow
OSError/ValueError fallback; no blanket Exception handler or custody change.

New SDK tests cover actual array-valued pending and intent records with unchanged
bytes, and a post-marker TypeError before token-index publication followed by
same-token recovery. An actual CLI malformed-pending recovery now reports status
6 and the exact request coordinates with phase unknown and no invented key_ref
or Commit. The optional missing legacy-import candidate case also now has an SDK
recovery-required assertion. A native negative control temporarily restores the
old catch tuple in an in-memory SDK module: all three TypeError regressions fail
while the OSError case passes. It changes no worktree files; the archived script
and log distinguish it from the agent's earlier reported red run. The corrected
full suites pass. Focused Fable-low correction review and primary triage: **ACCEPT**, no remaining
blockers. Both frozen review packets and native evidence are retained in
`reviews/consistency-c9-setup-{final,correction}-2026-09-06/`. Sources matched at
review closure; subsequent edits only update maintained status/handoff.

## Remaining transition

After this boundary is accepted, select a representative existing store for a
migration rehearsal on a copy. Store conversion, descriptor adoption, credential
binding, and consumer cutover are distinct operations. Live writers and originals
remain untouched by this implementation. Before executing that rehearsal, reconcile
the older sidecar publication path
with current descriptor adoption: `migrate.sidecar.edit_vertex_store_clause`
currently writes location/backend without the explicit role required by the
Arrival SDK resolver. Do not assume the old wrapper is a complete adoption
workflow. Source execution is the next substantial minimal-client transition.
Deliberate legacy retirement still requires an inventory
of surviving consumers and replacement workflows.
