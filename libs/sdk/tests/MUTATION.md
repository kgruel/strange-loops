# Mutation Testing Report: `libs/sdk`

- **Target Package**: `libs/sdk/src/sdk` (`declare.py`, `target.py`, `types.py`, `read.py`, `emit.py`, `kind.py`)
- **Test Suite**: `libs/sdk/tests/` (138 passing unit, contract, integration, property, and conformance tests)
- **Status**: Hardened across all operations (`declare`, `read`, `emit`, `kind`, `target`, `types`)

---

## Module-by-Module Breakdown

| Module | Status | Notes |
| :--- | :--- | :--- |
| **`target.py`** | **Hardened** | Complete coverage of path existence, target types, unsupported format rejections, and directory-tree `discover_targets`. |
| **`types.py`** | **100% Killed** (0 survivors) | Complete coverage of dataclass fields, frozen immutability, `as_dict()` transforms, `SdkValueError`, and exception hierarchies. |
| **`declare.py`** | **Hardened** | Covers `init_vertex` (standalone, strict, observer, root discovery) and `inspect_declaration` (healthy, corrupt, non-vertex diagnostics). |
| **`emit.py`** | **Hardened** | Covers `emit_fact`, `emit_batch`, `preview_emission`, `dry_run`, `id_override`, admission policy enforcement, custody signing, and `InvalidEmissionRequest` / `CommittedEmissionError` error wrapping. |
| **`kind.py`** | **Hardened** | Covers default `LoopDef`, AST mutation splices, ceremony plan/apply, generation diffing, observer grant/revoke ceremonies (`grant_observer`, `revoke_observer`), `plan_kind_mutation`, and recovery. |
| **`read.py`** | **Hardened** | Covers `read_summary` (with attestation counts), `read_facts`, `read_state`, `read_ticks`, `read_fact_by_id`, `search_facts` (FTS5), `resolve_entity`, `read_timeline`, `sync_target`, and aggregate vertices (`combine`, `discover`). |

---

## Running Mutation Tests

```bash
cd libs/sdk
uv run mutmut run
uv run mutmut results
```
