# Legacy consumer import inventory

Snapshot during stages 3A/3M. This lists surviving imports, not an assertion
that every listed call is authoritative or supported. Engine and SDK files are
being integrated; old CLI files are retirement inventory. Definitions, dynamic
imports and string-based dispatch still require the final residue sweep.

| Consumer | Imports (source line) |
| --- | --- |
| `apps/loops/src/loops/commands/ls.py` | `engine.jsonl_store: resolved_index` (475); `engine.jsonl_store: resolved_index` (609) |
| `apps/loops/src/loops/commands/resolve.py` | `engine.jsonl_store: ensure_index` (1207); `engine.jsonl_store: open_canonical_store` (1257) |
| `apps/loops/src/loops/commands/store.py` | `engine.jsonl_store: ensure_index` (74); `engine.residence: canonical_mode` (146); `engine.jsonl_store: ensure_index` (169); `engine.residence: canonical_mode` (397); `engine.sqlite_store: SqliteStore` (465); `engine.residence: canonical_mode` (808); `engine.jsonl_store: open_canonical_store` (971); `engine.jsonl_store: open_canonical_store` (1320); `engine.jsonl_store: open_canonical_store` (1407); `engine.jsonl_store: open_canonical_store` (1580) |
| `libs/engine/src/engine/arrival_store.py` | `sqlite_store: SqliteStore` (89) |
| `libs/engine/src/engine/canonical_audit.py` | `residence: canonical_mode` (281); `residence: canonical_mode` (292) |
| `libs/engine/src/engine/ceremony.py` | `jsonl_store: open_canonical_store` (169) |
| `libs/engine/src/engine/compiler.py` | `residence: canonical_mode` (937); `jsonl_store: open_canonical_store` (954) |
| `libs/engine/src/engine/handle.py` | `jsonl_store: resolved_index` (65) |
| `libs/engine/src/engine/jsonl_store.py` | `sqlite_store: SqliteStore` (193); `residence: canonical_mode` (265); `arrival_store: ArrivalStore` (270); `residence: canonical_mode` (347) |
| `libs/engine/src/engine/preflight.py` | `residence: canonical_mode` (56); `jsonl_store: open_canonical_store` (461) |
| `libs/engine/src/engine/probe.py` | `residence: canonical_mode` (61) |
| `libs/engine/src/engine/vertex_reader.py` | `jsonl_store: resolved_index` (42); `jsonl_store: open_canonical_store` (214) |
