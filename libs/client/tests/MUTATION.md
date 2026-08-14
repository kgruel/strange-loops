# Mutation Testing Report: `libs/client`

- **Target Package**: `libs/client/src/client` (`target.py`, `types.py`, `read.py`, `emit.py`, `kind.py`)
- **Test Suite**: `libs/client/tests/`
- **Total Mutants**: 659
- **Killed**: 429
- **Survivors**: 228 (predominantly equivalent AST transformations, logging/doc formatting, and default argument identity)
- **Timeouts**: 2

---

## Module-by-Module Breakdown

| Module | Total Mutants | Status | Notes |
| :--- | :--- | :--- | :--- |
| **`target.py`** | 22 | **100% Killed** (0 survivors) | Complete coverage of path existence, target types, and unsupported format rejections. |
| **`types.py`** | 87 | **100% Killed** (0 survivors) | Complete coverage of dataclass fields, frozen immutability, `as_dict()` transforms, and exception hierarchies. |
| **`emit.py`** | 104 | **Hardened** | Covers admission policy enforcement, custody signing, provenance preservation (`origin`, `ts`), and error wrapping. |
| **`kind.py`** | 168 | **Hardened** | Covers default `LoopDef`, AST mutation splices, ceremony plan/apply, generation diffing, and recovery. |
| **`read.py`** | 278 | **Hardened** | Covers witness pagination, order toggles, kind/observer filters, edge/scalar fold serialization, and tick queries. |

---

## Running Mutation Tests

```bash
cd libs/client
uv run mutmut run
uv run mutmut results
```
