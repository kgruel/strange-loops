# C9: minimal-CLI writer transition and legacy-authority inventory

Status: first C9 writer slice implemented on `arrival/finish`, based on
`f45f1f03`. Native validation is complete. Fable-low and primary verdicts: **ACCEPT**,
with no blockers. Included in this checkpoint; nothing pushed.
Legacy retirement remains open.

## Decision and first supported lifecycle

`loops-min` is the process boundary for the first writer slice.  It imports
only `sdk` and serializes SDK result/error objects; it does not open a store,
resolve a suffix, or construct a runtime.  The slice is deliberately
mapped-credential-only:

1. Before mapped initialization, an operator uses the SDK's explicit
   `MappedCredentialProvider.create_binding`, import, existing-reference, or
   recovery operation to create the required founding binding. Binding mutation
   has its own durable result and is not a CLI subcommand in this slice.
2. Each writer invocation supplies an exact `--credential-root`,
   `--credential-namespace`, and `--receipt-observer`.  The CLI constructs one
   `MappedCredentialProvider`; incomplete configuration is an argument error.
   Resolution is read-only and never creates a key or binding. A founding
   binding is mandatory for mapped init; an ordinary missing mapping may still
   produce an unsigned observation where the existing Arrival policy allows it.
3. `init` calls `sdk.init_vertex(..., store_type="arrival", backend="file")`.
   It never selects SQLite or JSONL.  `emit` accepts one JSON object payload;
   `emit-batch` accepts a JSON array of object items and calls `sdk.emit_batch`.
   Both preserve the SDK's result, atomicity, Commit, and unknown-outcome
   evidence rather than retrying or synchronizing.
4. `declaration TARGET --proposed-file FILE --observer OBSERVER` reads UTF-8
   proposal text and calls `sdk.edit_declaration`.  If its result/error carries
   a durable intent, `declaration-recover INTENT` calls
   `sdk.recover_declaration` without credentials: recovery must not re-sign or
   append a second declaration record.
5. A separate existing `sync`, read, and `verify` invocation observes the
   outcome.  The writer commands do not add an implicit projection repair,
   source run, or retry.

This is an additive process-client workflow, not an authorization to remove
the old application or to claim feature parity.

## Authority boundary and descriptor race

The public SDK generic writers still retain legacy compatibility:
`emit_fact` parses `_arrival_descriptor` and otherwise proceeds to the legacy
`open_vertex` path ([emit.py](../../../libs/sdk/src/sdk/emit.py#L363)).  The
same shape exists for `emit_batch` ([emit.py](../../../libs/sdk/src/sdk/emit.py#L596)).
Mapped credentials make a legacy downgrade fail closed:
`_refuse_legacy_mapped_credentials` rejects a mapped provider before that arm
([emit.py](../../../libs/sdk/src/sdk/emit.py#L128)).  `edit_declaration` is
already Arrival-only and refuses a target without an explicit descriptor
([declare.py](../../../libs/sdk/src/sdk/declare.py#L163)).

The CLI's `resolve_arrival_target` precheck is therefore a **classification
gate**, not a captured descriptor handle.  It parses the file once and the SDK
writer parses it again.  If the file is replaced with a legacy declaration
between those operations, mapped fail-closed behavior prevents a legacy write.
If it is replaced with a different valid Arrival descriptor, the second SDK
parse may choose that descriptor; the writer's own capture/CAS protects that
chosen descriptor, but the CLI has not promised identity continuity with the
first parse.

That is adequate for this first slice's no-legacy-authority claim.  It is not
a descriptor pinning contract.  A future process API that needs identity
continuity must receive a public resolved Arrival target/descriptor token or
perform resolve-and-write inside one SDK operation.  The CLI must not use
private SDK target helpers to simulate either design.

## Existing authority inventory

| Surface | Evidence | C9 disposition |
| --- | --- | --- |
| `apps/loops-min` | Its parser now exposes the mapped writer shapes and `_dispatch` calls exported SDK functions only ([main.py](../../../apps/loops-min/src/loops_min/main.py#L248)). | First supported writer client.  Its JSON parser rejects duplicate keys/non-finite values; SDK batch conversion errors are normalized to `InvalidEmissionRequest` before target resolution. |
| SDK transitional target/read/write arms | `resolve_target` still accepts `.vertex`, `.jsonl`, `.db`, and `.sqlite` ([target.py](../../../libs/sdk/src/sdk/target.py#L41)); generic reads retain `resolve_target`/legacy declaration fallbacks ([read.py](../../../libs/sdk/src/sdk/read.py#L515)); generic emit falls through to `open_vertex` ([emit.py](../../../libs/sdk/src/sdk/emit.py#L535)). | Retain as an explicit SDK compatibility boundary. C9 adds a mapped-only client and does **not** assert that all SDK reads or direct default-credential writers are Arrival-only. |
| legacy store suffix/canonical paths | The old store command resolves `.vertex` and `.db` artifacts, including JSONL-derived indexes ([store.py](../../../apps/loops/src/loops/commands/store.py#L57)); canonical JSONL handling remains in `engine.jsonl_store`. | Retain until individual migration/maintenance consumers have a replacement. A descriptor-backed process client does not make suffix paths removable. |
| `loops emit` / `close` | `cmd_emit` resolves local/config targets and calls `engine.load_vertex_program(...).receive` with filename-derived signers ([emit.py](../../../apps/loops/src/loops/commands/emit.py#L494), [emit.py](../../../apps/loops/src/loops/commands/emit.py#L863)). | Retain.  It has custom argument, local-resolution, dispatcher, and legacy signer behavior not represented by the first CLI slice. |
| `loops sync` | It loads programs, evaluates cadence, may run aggregate children and dispatch detached boundary commands ([sync.py](../../../apps/loops/src/loops/commands/sync.py#L78), [sync.py](../../../apps/loops/src/loops/commands/sync.py#L187)). | Retain; C9 writer commands do not substitute for source execution. |
| `loops init` / population | Init writes local artifacts, emits seed facts, and best-effort absorbs a lineage ([init.py](../../../apps/loops/src/loops/commands/init.py#L411)). | Retain.  Arrival init is intentionally different and forced through SDK. |
| legacy change/store tools | Change emission appends a canonical store directly ([resolve.py](../../../apps/loops/src/loops/commands/resolve.py#L1275)); store commands include migration, absorb, reanchor, and adapter-specific maintenance. | Inventory callers before removing any command. `reanchor` has no Arrival successor and dies outright under the completion worklist; that is a future removal decision, not an undecided replacement. |
| CLI registry/main shim | Registry still routes old verbs to legacy command wrappers; `loops.main` remains a compatibility re-export. | Retain until each named consumer has a replacement or an explicit retirement decision. |

The supplied registry/API call sites do not establish that generic SDK writers
are Arrival-only for default credentials.  C9 relies on mapped credentials for
the client boundary; it must not silently broaden that assertion to direct SDK
callers.

## Acceptance and retirement gates

The real subprocess workflow uses isolated `XDG_STATE_HOME`,
`XDG_CONFIG_HOME`, and `LOOPS_HOME`. SDK setup provisions Alice and Bob; CLI
init → emit → declaration granting Bob → mixed-author atomic batch → complete
read → Full verify checks actual Commit predecessors, exact IDs/authors/bodies
and captured/projected heads. Refusal controls cover partial arguments,
malformed later batch items, a distinct unauthorized Alice key in another
namespace, absent founding credentials, and a legacy writer target. A separate
ordinary missing-slot case preserves unsigned behavior without creating keys.

Tests at the SDK call boundary exercise committed/unknown error serialization,
declaration recovery dispatch without credentials, strict JSON/finite timestamp
transport and a descriptor changed to legacy after the classification gate.
They are deterministic injected seams, not subprocess crash or concurrent
writer tests. The prior [declaration recovery SDK workload](sdk-conformance-declaration-recovery-2026-09-06.md)
provides the real interruption/recovery custody evidence; this slice does not
claim to repeat that interruption through an operating-system process crash.

A separate modular-wheel smoke installs the client and SDK dependency wheels
into a fresh environment, with neither legacy `loops` nor Painted installed.
Outside the repository it provisions mapped credentials via SDK and invokes
the installed console executable for init → emit → declaration → facts → verify.
Installed production source hashes match the worktree. The first smoke harness
attempt compared a resolved module path to an unresolved environment prefix;
fixing that assertion allowed the same product wheels to pass.

Do not delete a legacy command merely because this workflow passes.  Deletion
requires: a named SDK/CLI replacement or intentional retirement for every
legacy consumer; subprocess compatibility evidence for former callers; an
explicit migration decision for store/absorb/reanchor/import tools; and updated
packaging/help that identifies `loops-min` as additive until the old `loops`
entry point can be replaced.  `run_sources`, close/seal, population operations,
aggregate writing, empty-receiver import, and custody binding mutation are
outside this slice.

## Follow-up work

The subsequent [setup/recovery slice](consistency-c9-setup-2026-09-06.md) now
exposes initialization recovery and SDK-owned serializable credential-lifecycle
outcomes with explicit binding commands. Source execution is the next substantial caller transition after
those setup/recovery boundaries. Inventory named old-command consumers before
removing wrappers or changing entry points. Generic SDK legacy arms, suffix
resolution, `JsonlStore`, and the reanchor command remain present; no runtime
authority path was deleted in this slice. Projection rebuild, empty-receiver
import, foreign admission, descriptor adoption, and live-store migration remain
separate work.

## Narrow implementation note: absolute File residence spelling

During C9 smoke validation, a mapped initialization with an absolute store
path under a directory symlink wrote that alias spelling into the `.vertex`
file.  The subsequent edit re-parsed the descriptor with
`descriptor_for`, which leaves absolute File paths unchanged, but declaration
preparation separately called `Path.resolve()` before comparing residence.
The unchanged proposal therefore refused.

`_descriptor_location` now delegates to `canonical_store_path`, the same rule
used by `descriptor_for`.  This preserves an absolute declaration spelling and
still resolves a relative File store against its declaring vertex.  Non-File
locations remain opaque; no descriptor identity rule was broadened.  The SDK
regression initializes through a pre-provisioned mapped provider at a real
directory plus symlink alias, accepts an unchanged-location edit, and refuses
a proposal changing the location.  The current `InitVertexResult.store`
normalizes the initialization output to the resolved File path while the
declaration text retains its submitted absolute spelling; this patch leaves
that established output behavior untouched rather than redefining descriptor
serialization. Absolute aliases and their resolved real paths remain distinct
declared location spellings; changing between them is not a residence-preserving
declaration edit.

## Narrow implementation note: batch input errors

Mapping-form batch payload and timestamp conversions previously raised raw
TypeError, ValueError, or OverflowError before SDK normalization. The client
would report those invalid inputs as internal failures. The SDK now raises
`InvalidEmissionRequest` at those conversion boundaries, preserving accepted
coercions and refusing before target resolution or any append. Six cases failed
before this correction and passed afterward; the CLI also exercises malformed
second items against an initialized store and checks unchanged ledger bytes.

## Validation and review

- Full minimal CLI: **20 passed** /7.45s.
- Full SDK: **590 passed** /32.93s.
- Architecture: **101 passed** /7.83s.
- Engine declaration custody: **14 passed** /0.15s.
- SDK declaration file: **37 passed**; focused batch conversion: **6 passed**.
- Scoped Ruff and whitespace pass. Installed modular-wheel lifecycle passes.

The SDK/architecture runs preceded final app-test-only assertion additions;
production sources stayed unchanged and the final CLI suite includes those
assertions and the seven boundary cases. Final run hashes matched. Native
logs, wheel source hashes and exact commands are in the
[review evidence](reviews/consistency-c9-transition-final-2026-09-06/validation-evidence/).
Fable-low and primary verdicts are **ACCEPT**, with no blockers. See the
[primary triage](reviews/consistency-c9-transition-final-2026-09-06/primary-triage.md).
All frozen sources matched at closure; only optional documentation clarifications
and maintained status/handoff prose changed afterward. No jobs remain.
