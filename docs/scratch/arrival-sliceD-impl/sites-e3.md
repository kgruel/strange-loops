# Stage E site inventory — explorer e3 (flash-low, HEAD 560710b8)

found

- `libs/engine/src/engine/sqlite_store.py:158-164` — _tick_envelope defining the exact 10 signed fields
- `libs/engine/src/engine/sqlite_store.py:1531-1545` — _cursor_rowid implementation resolving cursor fact id to rowid
- `libs/engine/src/engine/sqlite_store.py:1547-1574` — _window_hash implementation computing fact window hash in rowid order
- `libs/engine/src/engine/sqlite_store.py:1632-1648` — append_tick_attested new-tick state newest-fact and predecessor-tick edges
- `libs/engine/src/engine/sqlite_store.py:784-787` — current_chain_head lookup for latest sealed chained tick
- `libs/engine/src/engine/sqlite_store.py:807-809` — _genesis_payload lookup for newest fact by rowid
- `libs/engine/src/engine/sqlite_store.py:1709-1712` — reanchor_chain pass 1 signed facts scan ordered by rowid
- `libs/engine/src/engine/sqlite_store.py:1734-1736` — reanchor_chain pass 2 ticks scan ordered by rowid
- `libs/engine/src/engine/sqlite_store.py:1853-1858` — verify_chain tick scan ordered by rowid
- `libs/engine/src/engine/sqlite_store.py:1902-1909` — verify_chain per-tick window fact count query using rowid range
- `libs/engine/src/engine/sqlite_store.py:1929-1935` — verify_chain covered total fact count query using rowid range
- `libs/engine/src/engine/sqlite_store.py:234-251` — _fact_row_hash implementation and era-aware column list
- `libs/engine/src/engine/jsonl_store.py:946-954` — jsonl_store rebuild docstring on rowid counter reset and FTS watermark defect

Not covered: None within the requested scope and cited files.
