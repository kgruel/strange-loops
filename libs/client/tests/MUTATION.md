# Mutation Testing Report: `libs/client`

- **Target Package**: `libs/client/src/client` (`target.py`, `types.py`, `read.py`, `emit.py`, `kind.py`)
- **Test Suite**: `libs/client/tests/` (77 passing unit, contract, integration, and property tests)
- **Status**: Hardened across all operations (`read`, `emit`, `kind`, `target`, `types`)

---

## Module-by-Module Breakdown

| Module | Status | Notes |
| :--- | :--- | :--- |
| **`target.py`** | **100% Killed** (0 survivors) | Complete coverage of path existence, target types, and unsupported format rejections. |
| **`types.py`** | **100% Killed** (0 survivors) | Complete coverage of dataclass fields, frozen immutability, `as_dict()` transforms, `ClientValueError`, and exception hierarchies. |
| **`emit.py`** | **Hardened** | Covers `emit_fact`, `emit_batch`, `preview_emission`, `dry_run`, `id_override`, admission policy enforcement, custody signing, and `InvalidEmissionRequest` / `CommittedEmissionError` error wrapping. |
| **`kind.py`** | **Hardened** | Covers default `LoopDef`, AST mutation splices, ceremony plan/apply, generation diffing, and recovery. |
| **`read.py`** | **Hardened** | Covers witness pagination, order toggles, kind/observer filters, edge/scalar fold serialization, and tick queries. |

---

## Running Mutation Tests

```bash
cd libs/client
uv run mutmut run
uv run mutmut results
```
