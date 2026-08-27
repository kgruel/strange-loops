# Stage E site inventory — explorer e1 (flash-low, HEAD 560710b8)

found

- `libs/engine/src/engine/sqlite_store.py:308-335` — _SCHEMA_STMTS table and index definitions
- `libs/engine/src/engine/sqlite_store.py:131-132` — FACT_INSERT_SQL and TICK_INSERT_SQL definitions
- `libs/engine/src/engine/sqlite_store.py:513-537` — append method definition
- `libs/engine/src/engine/sqlite_store.py:1576-1609` — append_tick method definition
- `libs/engine/src/engine/sqlite_store.py:702-744` — Read-back-after-triggers contract in _committed_full_row and _committed_signature
- `libs/engine/src/engine/sqlite_store.py:1495-1523` — _ensure_chain_columns and _ensure_fact_signature_column lazy migrations
- `libs/engine/src/engine/sqlite_store.py:1708-1762` — Re-sign / re-anchor UPDATE paths in reanchor
- `libs/engine/src/engine/sqlite_store.py:1308-1339` — store_meta helpers _ensure_meta_table, _meta_get, _meta_set
- `libs/engine/src/engine/jsonl_store.py:667-671` — _write_fact_row and _write_tick_row index insert path
- `libs/engine/src/engine/jsonl_store.py:940-954` — Rowid-poisoning docstring in _rebuild
- `libs/engine/src/engine/arrival_store.py:102-104` — ARRIVAL_LINEAGE_KEY and ARRIVAL_ORDINAL_KEY definitions
- `libs/engine/src/engine/arrival_store.py:133-157` — ArrivalStore constructor ordering
- `libs/engine/src/engine/arrival_store.py:342-364` — _index_record catch-up indexer
- `libs/engine/src/engine/arrival_projection.py:479` — _ensure_index_schema call in rederive_projections
- `libs/engine/src/engine/arrival_projection.py:494-495` — FTS drop precedent in rederive_projections
- `libs/engine/src/engine/arrival_projection.py:500-509` — Record row insertion in rederive_projections
- `libs/engine/src/engine/arrival_projection.py:544-565` — _ensure_index_schema definition
- `libs/store/src/store/merge.py:165-177` — merge_store INSERT statements for facts and ticks
- `libs/store/src/store/rebirth.py:424-436` — rebirth_store executemany and execute INSERT statements for facts
- `libs/store/src/store/slice.py:88-110` — slice_store INSERT statements for facts and ticks

Not covered: Caller sites above libs/store/ and libs/engine/ (e.g. test harness setups and compiler callers).
