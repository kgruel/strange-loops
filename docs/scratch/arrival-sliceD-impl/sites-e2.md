# Stage E site inventory — explorer e2 (flash-low, HEAD 560710b8)

found

- `libs/engine/src/engine/witness.py:165-196` — WitnessPosition dataclass definition with fact_id, rowid, seq, lineage, unadopted, anchor, store fields.
- `libs/engine/src/engine/witness.py:550-568` — durable_handle function formatting lineage-qualified handle or returning None for unadopted/empty.
- `libs/engine/src/engine/witness.py:98-106` — WitnessAggregateUnsupported exception definition.
- `libs/engine/src/engine/witness.py:109-120` — WitnessLineageMismatch exception definition.
- `libs/engine/src/engine/witness.py:317-319` — _resolve_witness_position_on_conn seq count calculation using COUNT(*) on facts.
- `libs/engine/src/engine/witness.py:466-516` — verify_position_for_store function re-resolving or guarding cross-store positions.
- `libs/engine/src/engine/witness.py:248-274` — _resolve_anchor helper finding last sealed tick at or before rowid.
- `libs/engine/src/engine/witness.py:570-646` — diff_interval_report function computing late arrivals and declaration changes between positions.
- `libs/engine/src/engine/store_reader.py:605-650` — facts_between with at_rowid rowid_clause and query execution.
- `libs/engine/src/engine/store_reader.py:652-696` — facts_by_kind with at_rowid filtering.
- `libs/engine/src/engine/store_reader.py:809-816` — query_facts pagination rowid clauses for before and after WitnessPosition parameters.
- `libs/engine/src/engine/declaration.py:654-656` — _decl_lineage_and_head_on_conn at cutoff appending at.rowid.
- `libs/engine/src/engine/handle.py:852-855` — Storeless bootstrap position minting WitnessPosition(fact_id=GENESIS_SENTINEL, rowid=0, seq=0, ...).
- `libs/engine/src/engine/handle.py:787-792` — Handle in-memory checkpoint machinery holding raw fold state.
- `libs/engine/src/engine/vertex_reader.py:1216-1223` — First WitnessAggregateUnsupported raise site in vertex_fold.
- `libs/engine/src/engine/vertex_reader.py:1613-1620` — Second WitnessAggregateUnsupported raise site in vertex_facts.
- `libs/engine/src/engine/vertex_reader.py:1692-1700` — Third WitnessAggregateUnsupported raise site in vertex_query_facts.
- `libs/engine/src/engine/sqlite_store.py:1237-1242` — Comment marker indicating fold replay order is receipt order (rowid).
- `apps/loops/src/loops/cli/views/fold.py:1537-1540` — Diff baseline attribution comparing pos1.rowid <= pos2.rowid.

Not covered: Files not tracked by git or temporary artifacts outside the worktree.
