# Stage E site inventory — explorer e5 (flash-low, HEAD 560710b8)

found

- `libs/store/src/store/merge.py:526-532` — merge_store no-signature-verification docstring in _entry_for
- `libs/store/src/store/merge.py:512-515` — Carried fact-row signature prose in _entry_for docstring
- `libs/store/src/store/merge.py:463-498` — _entries_for dedup and remainder handling implementation
- `libs/engine/src/engine/arrival.py:1597-1637` — verify_authorship loop body and key resolution logic
- `libs/engine/src/engine/arrival.py:137` — Verify callable type definition
- `libs/engine/src/engine/arrival.py:694-699` — Entry docstring explaining signature absence on merge_store path
- `libs/engine/src/engine/arrival.py:102` — KEY_INTRODUCTION_KIND constant definition
- `libs/engine/src/engine/sqlite_store.py:254-283` — _fact_commitment_hash and fact_commitment_hash content-only commitment definitions
- `libs/store/tests/test_arrival_merge.py:726-747` — TestDivergenceRefusal class definition pinning CX-BR-01
- `libs/store/src/store/merge.py:66-71` — merge_store full signature
- `libs/store/src/store/receive.py:71` — merge_store production call site in receive_store

Not covered: None; all cited files, constants, classes, functions, docstrings, and callers were inspected directly at the requested commit.
