# c7-implementation — Fable review

Effort: low. Finished: 2026-09-06T22:26:02.771807+00:00.
Packet SHA-256: `0c52a207c76f9d4ecc6ab5479104a90fee991636eeafb3afa0924ab9d78c4c8f`.

Static reviewer output; findings still require primary triage.

**Verdict: ACCEPT.** No blockers found in the static packet.

**Checks that hold**

- **Descriptor gating** (`libs/sdk/src/sdk/target.py:88-100`): no-descriptor roots return `(path, ast, None)`; role refusal precedes the aggregate policy; the default `allow_aggregate=False` still raises `TargetUnsupported` for every non-inspection caller, and `_arrival_descriptor` filters `descriptor=None` so `resolve_arrival_target` and the single-store readers/writers are unchanged in behavior.
- **Root-only open** (`libs/sdk/src/sdk/declare.py:692-739`): exactly one `_open_arrival_read` per descriptor root, effective declaration folded from that snapshot with `allow_aggregate=True`, no `open_aggregate_read`, no glob, no member resolution anywhere on the path. `basis=opened.basis` is the root H/P/G only; no synthetic aggregate head exists in the DTO.
- **Both drift directions**: `local_*` comes from `locator_ast`, `effective_*` from `effective_ast`; `is_aggregate` follows effective. Neither local shape selects execution shape. The contract test parametrizes both directions with a poisoned `Path.glob` and an opener that rejects any non-root locator.
- **CURRENT failures / lifetime**: `_open_arrival_read` keeps `ProjectionRequirement.CURRENT` and closes in `finally`; `open_read` closes partially-acquired resources on exception; `OpenedRead.close` is idempotent. Effective-refusal closure is tested via ledger/query events.
- **Storeless classification** (`declare.py:744-750`): requires `descriptor is None` and `ast.store is None` and a combine/discover, so a legacy stored aggregate stays on the probe path (tested). The frozen branch runs before `probe_target`, and reuses the single AST retained by `_arrival_definition` (single-parse race test asserts `calls == 1`).
- **Frozen evidence**: lists in `_inspection_fields`/`_inspection_topology` are freshly built; `effective_combine` is a separate copy of dicts; fingerprints are semantic over `vertex_to_documents`, and since `documents_to_vertex` reconstructs `discover` from documents, topology is included in the fingerprint, so `local_status` drift detection covers shape changes.
- **DTO**: four new optional fields appended after existing ones; positional construction preserved; `asdict` serializes plain lists/dicts/strings; legacy path now also fills `local_*` (additive, effective stays None).

**Notes (non-blocking)**

- `test_arrival_inspect_descriptor_root_uses_effective_plain_shape` and its mirror don't assert `local_status == "drifted"`. Adding that would pin the fingerprint-includes-topology assumption; if `vertex_to_documents` ever stops emitting combine/discover docs, local/effective topology could differ while `local_status` reports `matches-effective`.
- `sdk/read.py:117-143` (`_aggregate_aware_arrival_descriptor`) still catches the refusal and reparses the file, which is the same second-parse race C7 just removed from inspection. It can now be replaced by `_arrival_descriptor(target, allow_aggregate=True)`. Pre-existing, out of C7 scope, but worth a follow-up ticket.
- Frozen-branch results leave `store_mode`/`store_path` as None; that's consistent with "no custody basis", just make sure CLI consumers of the v2 DTO tolerate a `local-frozen` read_path with `is_aggregate=True` and no store.
- The storeless branch is only reached for aggregate-shaped roots; a plain storeless vertex still goes through the legacy probe. That matches the stated contract ("compatibility-only"), so no change requested.
