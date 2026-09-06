# Minimal SDK CLI boundary

This CLI is a process client for `libs/sdk`. It owns argument parsing, JSON
encoding, diagnostics, and exit status. It does not resolve store suffixes,
open SQLite, call `BackendRegistry`, invoke custody, or implement admission.
A later Painted client can consume the same SDK results and add presentation.
The retired `apps/loops` CLI is inventory for migration, not a feature contract
for this client.

## Packaging boundary

Add a small application package, for example `apps/loops-min`, with source
package `loops_min` and one entry point, `loops-min = loops_min.main:main`.
Its only runtime library dependency is `sdk` (with workspace resolution in
local development). It must not import `loops`, `loops.cli`, `painted`, or the
old command modules. The first built-wheel smoke test installs this package
and invokes `loops-min`; it must work without the monorepo checkout.

The workspace root and `apps/loops` currently both publish a `loops` script:
`pyproject.toml` maps `loops` and `sl` to `loops.main:main`, while
`apps/loops/pyproject.toml` maps `loops` to the same old application. Do not
add a second `loops` entry point while that package remains in the wheel.
`loops-min` is the clean transition name. After the old app and its imports
are retired, the replacement package may take the `loops` name in one explicit
packaging change; `sl` remains a separately decided compatibility alias.

## Commands and current SDK mapping

The command names describe the intended boundary. The support column records
what the current exports can actually do; a missing operation stays visible as
an explicit unsupported result rather than being silently omitted.

| Command | SDK operation(s) | Current boundary |
| --- | --- | --- |
| `target` | `resolve_arrival_target` | Supported for descriptor parsing. `inspect_declaration` remains visible as an explicit unavailable command until its SDK path uses the Arrival snapshot rather than legacy declaration probing. |
| `init` | `init_vertex` | Scaffolds legacy SQLite/JSONL only. An Arrival-first `init_arrival` operation (mint ledger, declaration bootstrap, and binding) is missing and must land before claiming fresh adoption. |
| `summary` | `read_summary` | Arrival read path is available; legacy results remain labelled `read_path="legacy"`. |
| `facts` | `read_facts`, `read_fact_by_id` | Arrival bounded reads, filters, and lookups are available. Search and aggregate member semantics remain separate refusals. |
| `state` | `read_state` | Arrival folded state is available for a single descriptor-backed store. |
| `ticks` | `read_ticks` | Arrival tick reads are available. |
| `emit` / `emit-preview` | `emit_fact`, `preview_emission` | Current calls still use the earlier writer/resolution path; descriptor-backed runtime emission needs the runtime writer integration. |
| `emit-batch` | `emit_batch` | Current loop can commit a prefix before a later refusal. Do not advertise atomic CLI batches until SDK batch semantics are corrected or the result explicitly reports partial completion. |
| `declaration plan/edit` | `plan_kind_mutation`, `add_kind`, `edit_kind`, `remove_kind`, `grant_observer`, `revoke_observer`, `recover_ceremony` | These are the available kind/observer ceremony calls. A generic descriptor-aware declaration edit is not exported yet. |
| `verify` | — | No SDK verify operation. Add a headless `verify` wrapper over the ledger's scoped verification before exposing this command. It must not repair projections. |
| `sync` | `sync_target` | Exported, but explicit Arrival targets currently refuse. Add an Arrival maintenance operation before presenting it as adoption tooling. |
| `export` | — | The engine ledger has `export`; SDK has no process-safe wrapper. Add one that takes a captured basis/head and serializes a manifest plus records. |
| `replicate` | — | The engine ledger has exact `replicate`; SDK has no wrapper. It must preserve coordinates and refuse forks/stale heads. |
| `admit` | — | Admission exists below SDK; add a wrapper only after defining source verification, destination authority, and same-ID/different-content refusal. It is distinct from exact replication. `adopt` should be a separate descriptor ceremony when specified; `reanchor` has no command because that operation dies in the Arrival cut. |
| `search`, `timeline`, `resolve` | `search_facts`, `read_timeline`, `resolve_entity` | Keep commands and document current explicit-Arrival `TargetUnsupported` responses. Do not fall through to legacy storage or hide these capabilities from the worklist. |

The current declaration inspection and kind ceremonies still have legacy
resolution assumptions. They remain visible during migration, but the CLI
keeps inspection unavailable for now and must not imply that a legacy ceremony
changed an Arrival ledger unless the SDK says so.

## Invocation and JSON

Each invocation writes exactly one JSON document to stdout. Success is:

```json
{"ok": true, "result": {"schema": "loops.sdk/...", "...": "..."}}
```

The nested object is the SDK result's `.as_dict()` output. This preserves
`read_path`, descriptor identity, basis/head fields, declaration status, and
operation-specific receipts. `--pretty` may change whitespace only. No
human table, ANSI styling, or renderer import is allowed on stdout.

A failure uses the same envelope shape:

```json
{"ok": false, "error": {"type": "TargetUnsupported", "message": "...", "details": {}}}
```

Known exception fields belong in `details`: for example
`CommittedEmissionError.fact_id`, a target path, or a contract refusal's
basis/head when the SDK exposes it. Stderr receives one concise diagnostic
with the command and message; it never receives a traceback during ordinary
operation. Unexpected exceptions still get a stable `InternalError` envelope
and a diagnostic suitable for debugging.

Map process outcomes consistently: `0` successful result, including an
idempotent/no-op result; `2` argument or value errors; `3` recognized but
unsupported operation/target; `4` target, attestation, projection, CAS, or
contract refusal; `5` admission or declaration ceremony refusal; `6`
committed/unknown outcome requiring reconciliation; `70` unexpected internal
failure. The mapping is part of the CLI contract and should be tested by
subprocess, not inferred from exception text.

Arrival `read_facts` continuations are intentionally process-local. The SDK
redacts the engine `Continuation` in `.as_dict()` and reports
`has_continuation`; it does not provide a safe serialized token. The CLI must
return that fact plainly and must not invent a cursor string. Until a
process-safe continuation protocol exists, one invocation reads one bounded
page; a future `--all` or `--cursor` option requires a new SDK contract.

## Adoption acceptance boundary

The minimal built-wheel acceptance sequence is: resolve a descriptor,
initialize through the supported SDK operation, emit one fact, read summary,
facts, state, ticks, and an exact fact ID, perform a declaration plan/edit,
verify the captured prefix, sync the derived projection, export it, and test
replicate versus admit on temporary stores. Each step consumes only SDK
exports and checks JSON plus exit status. Until the missing Arrival init,
write, verify, maintenance, export, replication, and admission wrappers land,
the CLI should report those commands as typed unsupported outcomes rather
than reaching through SDK into engine internals.
