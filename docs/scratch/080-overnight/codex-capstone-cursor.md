## Findings

1. **BLOCKER — [witness_address.py:181](/Users/kaygee/Code/loops/apps/loops/src/loops/cli/witness_address.py:181), [witness.py:342](/Users/kaygee/Code/loops/libs/engine/src/engine/witness.py:342): A10 durable lineage qualification is not implemented end-to-end.**  
   `fact:ID` is resolved directly against the target store; the address carries no source lineage, and unadopted stores still emit reusable fact IDs. After merge copies the fact into another lineage, the same advertised handle silently resolves there. The in-memory guard cannot help because the newly resolved position already names the target store. Additionally, positions passed between stores sharing a lineage reuse the source `rowid` instead of re-resolving `fact_id` in the target. The lineage regression tests cover only in-memory positions applied to a *different* lineage, not serialized CLI round-trips or same-lineage stores.

2. **MAJOR — [declaration.py:212](/Users/kaygee/Code/loops/libs/engine/src/engine/declaration.py:212), [declaration.py:478](/Users/kaygee/Code/loops/libs/engine/src/engine/declaration.py:478): exported declaration selectors bypass the lineage guard.**  
   `resolve_declaration_documents(at=...)` and `load_declaration[_status](at=...)` apply `at.rowid` without `verify_position_for_store`. `vertex_fold` and `vertex_facts` eventually verify, but direct users of these newly public declaration APIs can obtain ontology from an unrelated prefix.

3. **MAJOR — [witness_address.py:196](/Users/kaygee/Code/loops/apps/loops/src/loops/cli/witness_address.py:196), [witness.py:314](/Users/kaygee/Code/loops/libs/engine/src/engine/witness.py:314): floor-form receipt-group snapping is missing.**  
   The ratified contract says tick/wall-clock floor forms snap before a ceremony while `fact:ID` naming a middle row refuses. All forms currently flow into the same unconditional `MidReceiptGroupPosition` refusal. The docstring claims the CLI performs the snap, but no such adjustment exists.

4. **MAJOR — [fold.py:563](/Users/kaygee/Code/loops/apps/loops/src/loops/cli/views/fold.py:563): `--why --diff` silently discards the temporal operation.**  
   The `--why` short-circuit checks only `--at/--as-of`, then returns before the `--diff` branch. With an exact entity address, the command answers the head provenance query while ignoring `--diff A..B`.

5. **MAJOR — [fold.py:670](/Users/kaygee/Code/loops/apps/loops/src/loops/cli/views/fold.py:670), [dispatch.py:244](/Users/kaygee/Code/loops/apps/loops/src/loops/cli/dispatch.py:244): autoresearch interactive mode accepts temporal selectors but runs at head.**  
   The cursor is resolved and placed in an unused `Operation`, then interactive dispatch calls `AutoresearchApp(vertex_path, observer=...)` without either selector. `-i --lens autoresearch --at/--as-of` therefore reaches unselected data.

6. **MAJOR — [fold.py:611](/Users/kaygee/Code/loops/apps/loops/src/loops/cli/views/fold.py:611), [lens_resolver.py:461](/Users/kaygee/Code/loops/apps/loops/src/loops/lens_resolver.py:461): lens refusal covers fetch honesty, not rendered-mode honesty.**  
   A render-only custom lens uses the correct historical default fetch but silently drops the `cursor` kwarg when its signature does not accept it. Text output then omits the required witness/projection label, while JSON includes it. The lens regression test covers only lenses with an incompatible custom `fetch`.

7. **MAJOR — [declaration.py:465](/Users/kaygee/Code/loops/libs/engine/src/engine/declaration.py:465): aggregates with an own store lose the `aggregate-head` disclosure.**  
   Storeless aggregates receive `aggregate-head`, but a combine/discover vertex with `store` proceeds through declaration resolution and reports `store`. Its membership/existence set remains current, so an `--as-of` answer is mislabeled despite A9’s required named derogation.

8. **MAJOR — [fold.py:993](/Users/kaygee/Code/loops/apps/loops/src/loops/cli/views/fold.py:993), [fold.py:215](/Users/kaygee/Code/loops/apps/loops/src/loops/lenses/fold.py:215): `--diff` omits ratified honesty information.**  
   It computes only structural fold changes. It does not report late arrivals or declaration changes in the interval. Text endpoint labels also omit anchor, unadopted state, and honesty-ladder status—so current pre-genesis stores do not say “ontology is the current file,” contrary to A13. JSON does retain endpoint metadata.

9. **MINOR — safety-test coverage overstates two of the five critical regressions.**  
   The unconditional guard, floor-anchor preservation, and first-hop refs tests correctly lock their intended mechanisms. The lineage tests at [test_witness_position.py:449](/Users/kaygee/Code/loops/libs/engine/tests/test_witness_position.py:449) miss CLI serialization and same-lineage/reordered stores. The lens tests at [test_cursor_review_findings.py:136](/Users/kaygee/Code/loops/apps/loops/tests/test_cursor_review_findings.py:136) miss render-only lenses and interactive dispatch. Refs threading is correct in code, though the regression covers only one hop and witness mode, not depth>1 or `as_of`.

10. **MINOR — [__init__.py:97](/Users/kaygee/Code/loops/libs/engine/src/engine/__init__.py:97), [declaration.py:50](/Users/kaygee/Code/loops/libs/engine/src/engine/declaration.py:50): public API/documentation needs pruning and reconciliation.**  
    Every `__all__` name resolves, but low-level heuristic `receipt_group_span(sqlite3.Connection, ...)` is unnecessarily exported. The declaration module still says witness selection is deferred, while `MidReceiptGroupPosition` documents nonexistent CLI snapping.

## Residual risk register

- `receipt_group_span` scans all declaration rows and is commonly run twice per cursor read; acceptable for today’s corpus, but growth-sensitive.
- Durable receipt-group IDs, GlobalReceiptPosition, rebuild durability, and conformance vectors remain known protocol follow-ups.
- No new schema migration appears necessary; legacy tick columns are probed defensively.
- [CHANGELOG.md:1](/Users/kaygee/Code/loops/CHANGELOG.md:1), root version `0.7.0`, and [CLI-CHEATSHEET.md:60](/Users/kaygee/Code/loops/docs/CLI-CHEATSHEET.md:60) remain stale—the latter still calls folded reads head-only and says the cursor is unwired.

Verification: nine-commit shape confirmed; all changed Python files parse, public imports resolve, and `git diff --check` is clean. Pytest could not collect in this read-only environment because neither pytest nor `uv` had a writable cache/temp directory.

**NOT-MERGE-READY — the serialized lineage contract is unsafe, with additional paths that silently ignore or mislabel temporal selection.**