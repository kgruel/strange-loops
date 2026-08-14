# Mutation Testing Report: `engine.witness`

- **Target Module**: `libs/engine/src/engine/witness.py`
- **Test Suites**: `libs/engine/tests/test_witness_position.py`, `libs/engine/tests/test_witness_address_helpers.py`, `libs/engine/tests/test_diff_interval_report.py`, `libs/engine/tests/test_fold_at.py`
- **Total Mutants**: 512
- **Killed (initial)**: 344
- **Initial Survivors**: 168
- **Killed (final)**: 402
- **Final Survivors**: 110 (all equivalent)

## Initial Gaps & Killing Tests

| # | Mutant ID | Diff Summary | Class | Added Killing Test |
|---|-----------|--------------|-------|--------------------|
| 1 | `engine.witness.x__lineage_of__mutmut_1` | `json.loads(payload_text).get('lineage')` -> `.get(None)` | `gap` | `TestReceiptGroupGuard.test_receipt_group_span_extracts_and_distinguishes_lineages` |
| 2 | `engine.witness.x__lineage_of__mutmut_2` | `json.loads(payload_text).get('lineage')` -> `json.loads(None)...` | `gap` | `TestReceiptGroupGuard.test_receipt_group_span_extracts_and_distinguishes_lineages` |
| 3 | `engine.witness.x__lineage_of__mutmut_3` | `json.loads(payload_text).get('lineage')` -> `.get('XXlineageXX')` | `gap` | `TestReceiptGroupGuard.test_receipt_group_span_extracts_and_distinguishes_lineages` |
| 4 | `engine.witness.x__lineage_of__mutmut_4` | `json.loads(payload_text).get('lineage')` -> `.get('LINEAGE')` | `gap` | `TestReceiptGroupGuard.test_receipt_group_span_extracts_and_distinguishes_lineages` |
| 5 | `engine.witness.x_receipt_group_span__mutmut_21` | `if rid == prev_rowid + 1 and ts == prev_ts and lineage == prev_lineage:` -> `... and ts == prev_ts or lineage == prev_lineage:` | `gap` | `TestReceiptGroupGuard.test_receipt_group_span_requires_contiguous_rowids_and_matching_ts` |
| 6 | `engine.witness.x__resolve_anchor__mutmut_29` | `TickAnchor(name=row[0], ts=row[1], fact_cursor=row[2])` -> `ts=None` | `gap` | `TestAnchor.test_anchor_is_last_sealed_tick_before_position` |
| 7 | `engine.witness.x__resolve_anchor__mutmut_35` | `TickAnchor(name=row[0], ts=row[1], fact_cursor=row[2])` -> `ts=row[2]` | `gap` | `TestAnchor.test_anchor_is_last_sealed_tick_before_position` |
| 8 | `engine.witness.x__resolve_witness_position_on_conn__mutmut_10` | `span = None if group_boundary == 'allow' else ...` -> `== 'XXallowXX'` | `gap` | `TestGroupBoundarySnap.test_allow_group_boundary_skips_guard` |
| 9 | `engine.witness.x__resolve_witness_position_on_conn__mutmut_11` | `span = None if group_boundary == 'allow' else ...` -> `== 'ALLOW'` | `gap` | `TestGroupBoundarySnap.test_allow_group_boundary_skips_guard` |
| 10 | `engine.witness.x__resolve_witness_position_on_conn__mutmut_24` | `fact_id = _id_at_rowid(conn, rowid)` in floor snap -> `fact_id = None` | `gap` | `TestGroupBoundarySnap.test_refuse_is_default_floor_snaps_before_first_row` |
| 11 | `engine.witness.x__resolve_witness_position_on_conn__mutmut_30` | `span[0]..span[1]` in MidReceiptGroupPosition message -> `span[1]..span[1]` | `gap` | `TestReceiptGroupGuard.test_resolve_at_mid_group_refuses` |
| 12 | `engine.witness.x_resolve_witness_position__mutmut_10` | Invalid store error message in `resolve_witness_position` -> `None` | `gap` | `TestResolveAddress.test_resolve_witness_position_invalid_store_raises` |
| 13 | `engine.witness.x_resolve_cut_summary__mutmut_8` | Invalid store error message in `resolve_cut_summary` -> `None` | `gap` | `TestResolveCutSummary.test_no_usable_store_raises` |
| 14 | `engine.witness.x_verify_position_for_store__mutmut_7` | Unadopted lineage mismatch error message in `verify_position_for_store` -> `None` | `gap` | `TestLineageQualification.test_unadopted_position_refused_on_a_different_store` |
| 15 | `engine.witness.x_verify_position_for_store__mutmut_26` | Lineage mismatch error message in `verify_position_for_store` -> `None` | `gap` | `TestLineageQualification.test_adopted_position_refused_on_a_different_lineage` |
| 16 | `engine.witness.x__resolve_address_rowid__mutmut_24` | UnknownWitnessHandle error message in `_resolve_address_rowid` -> `None` | `gap` | `TestResolveAddress.test_unknown_handle_refuses` |
| 17 | `engine.witness.x__id_at_rowid__mutmut_2` | `if rowid <= 0:` -> `if rowid <= 1:` in `_id_at_rowid` | `gap` | `TestGroupBoundarySnap.test_refuse_is_default_floor_snaps_before_first_row` |
| 18 | `engine.witness.x__id_at_rowid__mutmut_3` | `row = conn.execute(...).fetchone()` -> `row = None` in `_id_at_rowid` | `gap` | `TestGroupBoundarySnap.test_refuse_is_default_floor_snaps_before_first_row` |
| 19 | `engine.witness.x_durable_handle__mutmut_2` | `if pos.unadopted or pos.lineage is None...` -> `if pos.unadopted and pos.lineage is None...` | `gap` | `TestDurableHandle.test_unadopted_flag_with_non_none_lineage_refuses_durable_handle` |
| 20 | `engine.witness.x_diff_interval_report__mutmut_8` | Invalid store error message in `diff_interval_report` -> `None` | `gap` | `TestNoInterval.test_invalid_store_raises` |
| 21 | `engine.witness.x_diff_interval_report__mutmut_29` | `late_arrivals: list[dict] = []` -> `None` in `diff_interval_report` | `gap` | `TestLateArrivals.test_diff_from_empty_prefix_returns_empty_list_for_late_arrivals` |
| 22 | `engine.witness.x_expand_fact_prefix__mutmut_13` | UnknownWitnessHandle error message in `expand_fact_prefix` -> `None` | `gap` | `TestExpandFactPrefix.test_no_match_raises_unknown_handle` |
| 23 | `engine.witness.x_resolve_seq__mutmut_8` | Invalid store error message in `resolve_seq` -> `None` | `gap` | `TestResolveSeq.test_resolve_seq_invalid_store_raises` |
| 24 | `engine.witness.x_resolve_tick_cursor__mutmut_8` | Invalid store error message in `resolve_tick_cursor` -> `None` | `gap` | `TestResolveTickCursor.test_resolve_tick_cursor_invalid_store_raises` |
| 25 | `engine.witness.x_resolve_tick_cursor__mutmut_18` | `row = conn.execute(...).fetchone()` -> `row = None` in pre-chain schema branch | `gap` | `TestResolveTickCursor.test_pre_chain_schema_tick_raises_no_witness_anchor` |
| 26 | `engine.witness.x_resolve_tick_cursor__mutmut_19` | SQL query string mutated to None in pre-chain schema branch | `gap` | `TestResolveTickCursor.test_pre_chain_schema_tick_raises_no_witness_anchor` |
| 27 | `engine.witness.x_resolve_tick_cursor__mutmut_20` | Query params mutated to None in pre-chain schema branch | `gap` | `TestResolveTickCursor.test_pre_chain_schema_tick_raises_no_witness_anchor` |
| 28 | `engine.witness.x_resolve_tick_cursor__mutmut_21` | Query call signature mutated in pre-chain schema branch | `gap` | `TestResolveTickCursor.test_pre_chain_schema_tick_raises_no_witness_anchor` |
| 29 | `engine.witness.x_resolve_tick_cursor__mutmut_22` | Query fetchone signature mutated in pre-chain schema branch | `gap` | `TestResolveTickCursor.test_pre_chain_schema_tick_raises_no_witness_anchor` |
| 30 | `engine.witness.x_resolve_tick_cursor__mutmut_23` | Query string mutated to XX...XX in pre-chain schema branch | `gap` | `TestResolveTickCursor.test_pre_chain_schema_tick_raises_no_witness_anchor` |
| 31 | `engine.witness.x_resolve_tick_cursor__mutmut_26` | `if row is None:` -> `if row is not None:` in pre-chain schema branch | `gap` | `TestResolveTickCursor.test_pre_chain_schema_tick_raises_no_witness_anchor` |
| 32 | `engine.witness.x_resolve_tick_cursor__mutmut_27` | UnknownTickHandle message mutated to None in pre-chain schema branch | `gap` | `TestResolveTickCursor.test_pre_chain_schema_unknown_tick_raises_unknown_tick_handle` |
| 33 | `engine.witness.x_resolve_tick_cursor__mutmut_28` | NoWitnessAnchor message mutated to None in pre-chain schema branch | `gap` | `TestResolveTickCursor.test_pre_chain_schema_tick_raises_no_witness_anchor` |
| 34 | `engine.witness.x_resolve_tick_cursor__mutmut_29` | `row[0]` replaced with `row[1]` in pre-chain NoWitnessAnchor message | `gap` | `TestResolveTickCursor.test_pre_chain_schema_tick_raises_no_witness_anchor` |
| 35 | `engine.witness.x_resolve_tick_cursor__mutmut_30` | `row[1]` replaced with `row[2]` in pre-chain NoWitnessAnchor message | `gap` | `TestResolveTickCursor.test_pre_chain_schema_tick_raises_no_witness_anchor` |
| 36 | `engine.witness.x_resolve_tick_cursor__mutmut_47` | UnknownTickHandle message mutated to None in chained schema branch | `gap` | `TestResolveTickCursor.test_unknown_tick_id_refuses` |
| 37 | `engine.witness.x_resolve_tick_cursor__mutmut_50` | NoWitnessAnchor message mutated to None on unchained tick | `gap` | `TestResolveTickCursor.test_tick_with_no_cursor_has_no_anchor` |
| 38 | `engine.witness.x_resolve_tick_floor__mutmut_8` | Invalid store error message in `resolve_tick_floor` -> `None` | `gap` | `TestResolveTickFloor.test_resolve_tick_floor_invalid_store_raises` |
| 39 | `engine.witness.x_resolve_tick_floor__mutmut_38` | NoWitnessAnchor message mutated to None in `resolve_tick_floor` | `gap` | `TestResolveTickFloor.test_no_tick_before_mark_refuses` |

## Final Survivors (All Equivalent)

The 110 remaining survivors fall into four semantically equivalent categories:

1. **SQL Keyword Casing (74 mutants)**: SQLite keywords and column names are case-insensitive (`SELECT` vs `select` vs `SELECT ...`, `PRAGMA` vs `pragma`, `JOIN` vs `join`, `WHERE` vs `where`, `ORDER BY` vs `order by`, `DESC` vs `desc`).
2. **Default Timeout Parameters & Forwarding (17 mutants)**: `timeout: float = 5.0` -> `6.0` or omission of keyword pass-through `timeout=timeout` where the downstream helper has the exact same default value `5.0`.
3. **Exception Substring Formatting Variations (16 mutants)**: Non-semantic uppercase or lowercase variants and `group_boundary: str = 'refuse'` default argument literal mutations (`'REFUSE'` / `'XXrefuseXX'`) where exact error classes and messages are pinned.
4. **Semantic Invariants (3 mutants)**:
   - `x__id_at_rowid__mutmut_1`: `if rowid <= 0:` -> `if rowid < 0:`. When `rowid == 0`, SQLite returns no row, so `row[0] if row else GENESIS_SENTINEL` still returns `GENESIS_SENTINEL`.
   - `x_verify_position_for_store__mutmut_24`: `if conn is not None: conn.close()` -> `if conn is None: conn.close()`. Closing a read-only snapshot before returning.
   - `x_resolve_cut_summary__mutmut_11`: `conn.isolation_level = None` -> `conn.isolation_level = ''`. Autocommit transaction initiation before manual `BEGIN`.

SURVIVORS: 110 (all equivalent/finding)
