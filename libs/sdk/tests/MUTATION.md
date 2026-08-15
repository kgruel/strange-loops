# Mutation Testing Report: `libs/sdk`

- **Target Package**: `libs/sdk/src/sdk` (`declare.py`, `target.py`, `types.py`, `read.py`, `emit.py`, `kind.py`)
- **Test Suite**: `libs/sdk/tests/` — per-mutant net is the unit/contract/integration/property/conformance layers; the stateful suite (`test_stateful_sdk.py`) self-excludes under `MUTANT_UNDER_TEST` (sequence-level complement, not a per-mutant killer).
- **Last full run**: 2026-08-14, mutmut 3.x, 3088 mutants.

## Results (2026-08-14)

| Module | Mutants surviving | Notes |
| :--- | ---: | :--- |
| `types.py` | 0 | Fully killed. |
| `target.py` | 32 | |
| `declare.py` | 90 | |
| `kind.py` | 209 | |
| `emit.py` | 244 | |
| `read.py` | 1183 | Largest module, weakest kill net. Sample confirmed-real survivor: `read_summary`'s `include_internal=False` default flips to `True` unnoticed — no test pins default exclusion of internal kinds. |

Timeouts: 6. Total survived: 1752 of 3088 (57%).

**Status: NOT hardened.** A prior version of this report claimed "Hardened" per
module in prose, with no numbers; the 2026-08-14 run falsified that for every
module except `types.py`. Survivors are UNCLASSIFIED (not triaged into
equivalent/finding), so this report deliberately does not end with the
`SURVIVORS: N (all equivalent/finding)` line and carries no Rule 14 ceiling
entry yet — adding one requires classifying survivors first, not asserting
them away. Survivor burn-down is tracked in thread:sdk-coverage-arc.

## Running Mutation Tests

```bash
cd libs/sdk
uv run mutmut run
uv run mutmut results
uv run mutmut show <mutant-id>
```
