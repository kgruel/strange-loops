# Mutation Testing Report: `libs/client`

- **Target Package**: `libs/client/src/client` (`target.py`, `types.py`, `read.py`, `emit.py`, `kind.py`)
- **Test Suite**: `libs/client/tests/` (90 passing unit, contract, integration, and property tests)
- **Status**: Hardened across all operations (`read`, `emit`, `kind`, `target`, `types`)

---

## Module-by-Module Breakdown

| Module | Status | Notes |
| :--- | :--- | :--- |
| **`target.py`** | **100% Killed** (0 survivors) | Complete coverage of path existence, target types, and unsupported format rejections. |
| **`types.py`** | **100% Killed** (0 survivors) | Complete coverage of dataclass fields, frozen immutability, `as_dict()` transforms, `ClientValueError`, and exception hierarchies. |
| **`emit.py`** | **Hardened** | Covers `emit_fact`, `emit_batch`, `preview_emission`, `dry_run`, `id_override`, admission policy enforcement, custody signing, and `InvalidEmissionRequest` / `CommittedEmissionError` error wrapping. |
| **`kind.py`** | **Hardened** | Covers default `LoopDef`, AST mutation splices, ceremony plan/apply, generation diffing, and recovery. |
| **`read.py`** | **Hardened** | Covers `read_summary` (with attestation counts), `read_facts`, `read_state`, `read_ticks`, `read_fact_by_id`, `search_facts` (FTS5), `resolve_entity`, `read_timeline`, `sync_target`, and aggregate vertices (`combine`, `discover`). |

---

## Running Mutation Tests

```bash
cd libs/client
uv run mutmut run
uv run mutmut results
```
