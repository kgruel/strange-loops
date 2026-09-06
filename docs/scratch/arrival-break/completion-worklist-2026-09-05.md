# Arrival completion worklist

Status: implementation in progress against `main` at `d904ccba`; current
assignments, accepted stages and evidence are in the
[orchestration log](orchestration-2026-09-05.md).
Working branch: `arrival/finish`.

This worklist reconciles the ratified Arrival target with the checkout. It
does not ratify new protocol or query operations. The delivery order below
is proposed within the existing slice-5 and slice-6 boundaries.

## Authority and scope

- [Architecture suite](../../architecture/arrival/index.html): the backend-neutral
  protocol, wire profile, backend contract, and external head memory.
- [Original implementation plan](plan.md): slice 5
  integrates consumers and deletes legacy modes; slice 6 migrates live stores.
- [Slice-4 design](slice4-design-proposal.md), especially
  section F: subsequent corrections govern the original verb disposition table.
- Session direction: the SDK supports a new minimal CLI, followed by a richer
  Painted client. Reimplementing the outgoing CLI's presentation is not an exit
  condition for the Arrival protocol work.

The original `feat/arrival-libs` branch merged in PR #9 (`d1792bf5`). Wire v1,
the backend contract, head comparison, and the migration sidecar are on main.
The sidecar already uses `BackendRegistry` and `AttestedLedger`. Ordinary SDK
and runtime entry points still use the earlier resolution and writer paths.

## Work already present

| Capability | Implementation |
| --- | --- |
| Ordered records, keys, commitments, wire v1 | `engine/arrival.py`, `arrival_body.py` |
| Ledger/query split and full-head CAS | `arrival_contract.py`, `arrival_file_backend.py` |
| Explicit backend registry | `arrival_registry.py` |
| External head memory and comparison | `arrival_head_attestation.py`, `arrival_head_seam.py` |
| Frozen legacy reader, translation, verification, cutover | `libs/migrate` |

At the preparation baseline, 196 targeted contract/registry/CAS/head-seam/
transfer tests and all 69 migration tests passed in the main checkout. Those
counts describe selected checks, not the complete repository test suite.

## Delivery sequence

### 1. Complete descriptor resolution

- Reject non-string `backend` properties instead of coercing nulls, booleans,
  or numbers into adapter names (deferred finding WP4-F3).
- Complete the declared lineage/role path and enforce its relationship to
  the presented genesis and backend capabilities. A descriptor does not
  confer authority merely by naming it.
- Keep location interpretation with the adapter. `VertexFile.store` is a
  `Path` today, while `StoreDescriptor.location` deliberately permits a DSN
  reference or service URL; resolve this mismatch before claiming portable
  addressing. Preserve relative file paths relative to the vertex.
- Replace inferred suffix selection only as its callers move to explicit
  descriptors. Remove the transitional branch as part of the completed cut.

Exit: valid descriptors select the named adapter regardless of suffix;
malformed declarations, unknown adapters, wrong lineage, and unsupported
roles fail without modifying the target. Aggregate/storeless vertices keep
their distinct meaning.

### 2. Establish one consumer open/read path

- Route resolution through the registry before recovery or materialization.
  Moving only the final writer is insufficient: declaration resolution and
  `VertexHandle._open` currently resolve an index before opening a writer.
- Carry a captured head and represented projection prefix with reads. Define
  coherent snapshot acquisition so rows and their reported basis agree.
- Provide the SDK's required fact, tick, fold, pagination, search, and
  aggregate reads without exposing `FileQuery.reader` as a public portable
  contract. `ArrivalQuery` currently specifies only lineage and watermark;
  the neutral query spelling remains an explicit design task.
- Keep projection catch-up and deliberate rebuild separate from verification;
  report post-append projection failure without disguising a committed record
  as a failed append. Resolve the deferred rederivation-staleness finding.

Exit: ordinary reads cannot bypass head comparison; fresh, missing, behind,
divergent, rollback, and fork states remain distinguishable. Aggregate results
retain per-lineage positions rather than inventing a common ordinal.

### 3. Move runtime writes and declarations onto admission plus append

- Separate row preparation and execution semantics from `SqliteStore`'s
  persistence responsibilities. SQLite can remain the file backend's
  projection implementation without remaining an independent authority mode.
- Move receive, source execution, boundaries, and declaration edits to the
  witnessed ledger path. Preserve authored inner commitments and the outer
  signature rules rather than regenerating claims during transfer.
- Make fresh initialization perform the ordinary genesis/key/declaration
  bootstrap. Legacy migration and fresh initialization are different callers.
- Preserve declaration edit semantics and stale-head checks against the
  same basis used for admission. Preserve batch record boundaries.

Exit: no ordinary writer can bypass the registry/admission path. Rejection
leaves the ledger unchanged; committed and unknown outcomes retain enough
identity for reconciliation. Replay does not emit a second history.

### 4. Finish the SDK operations and minimal process boundary

- Replace `canonical_mode` and raw index-location assumptions in public
  target/read/initialization models with descriptor-based results.
- Expose supported initialization, reading, emission, declaration changes,
  verification, projection maintenance, and transfer through headless calls.
- Specify SDK batch semantics. The current `emit_batch` docstring promises
  atomicity while its loop can commit a prefix before rejection. Either
  enforce the promised unit or report partial completion with prior receipts;
  backend atomic limits and single-observer batch grammar remain constraints.
- Preserve refusal, committed, and unknown outcomes in machine results and
  process exits. Serialization is an SDK contract, not a renderer fallback.
- Build the minimal CLI against that surface, with no imports from the old
  CLI and no independent custody, resolution, or admission implementation.

Exit: a small client can initialize, emit, read, publish, inspect provenance,
edit a declaration, and diagnose failures using SDK operations alone. Rich
Painted rendering remains a subsequent consumer.

### 5. Re-express transfer and remove superseded paths

- Preserve exact replication separately from admission into another lineage.
- Re-express export over a captured prefix; slicing is scan/filter/admission,
  not a filtered ledger prefix. Preserve same-ID/different-content refusal.
- Remove legacy merge arms, SQLite-file transport/receive, duplicate schemas,
  `JsonlStore`, and suffix-mode dispatch after surviving callers are green.
- Correct the old plan's dispositions: declaration **edits survive**;
  `reanchor` **dies outright**; descriptor-based adoption is **new work**, not
  an existing half of `_run_adopt` waiting to be renamed.
- Keep legacy codecs isolated in the migration sidecar. Keep backend-specific
  projection/administrative utilities explicitly backend-specific.
- Sweep obsolete tests, imports, allowlists, README claims, and runtime guides
  with the deletions. A retained old CLI needs an explicit support boundary;
  its current behavior is not the new client's feature checklist.

Exit: the supported runtime has one protocol with replaceable backends, and
cannot reopen a legacy artifact as an alternate authoritative store.

### 6. Validate and adopt live stores

- Run architecture checks, library suites, fault injection, conformance, the
  new client acceptance path, and an isolated built-wheel smoke test.
- Exercise real-sized copies and compare before/after reads and publications;
  record performance for SDK sessions and process-per-command usage.
- Inventory by consumer, including aggregates, colleagues' runtimes, hooks,
  pollers, and cross-host members. Directory enumeration alone is insufficient.
- For each agreed migration window: quiesce writers, stage, verify equivalence,
  establish external head memory, publish the descriptor, and verify through
  the supported client before resuming writers. Low-stakes store first;
  repository project store last. Retain the original as read-only evidence.
- Confirm all required consumers can read their migrated members before 1.0.
  Release remains a separate operation after adoption.

## Decisions to resolve during implementation

These are design choices, not permission gates imposed by this document:

1. The smallest query/snapshot interface the SDK requires before DuckDB.
2. Descriptor role enforcement and adoption without pretending to implement
   the deferred live authority-transfer protocol.
3. Atomic versus explicitly partial SDK batch operations and reconciliation.
4. The outgoing CLI's retirement boundary and which minimal commands the
   live adoption ceremony requires.

## Deferred beyond this completion arc

DuckDB is the next materially different adapter that can test neutrality;
PostgreSQL, git-hosted authority, formal authority transfer, erasure profiles,
and notary/quorum witnessing remain outside this arc. Limited-backend resumable
import is documented contract debt; do not claim support until it is exercised.

## First implementation item

The branch begins with the scoped WP4-F3 parser correction and regression
cases: typed KDL values are refused as backend names, while arbitrary explicit
string names remain legal for deployments with other registered adapters.
The wider consumer integration and legacy deletion are still pending.

Validation of this first item: the six non-string cases failed before the
correction; afterward all 697 language tests, 24 registry tests, and 101
architecture checks passed in the isolated worktree. No live stores were
opened or migrated by this work.
