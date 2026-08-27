SCOPE 2 — the bridge dissolution and its residue (slice C2-part-B, C0).

Files under review (read every changed line; `git diff a49997cd..074a1860 -- <path>`):
- libs/store/src/store/jsonl.py (DELETED) + libs/store/tests/test_jsonl.py (DELETED) + libs/store/src/store/__init__.py + libs/store/src/store/merge.py + libs/store/tests/test_properties_merge.py + libs/store/tests/test_arrival_merge.py
- libs/engine/src/engine/jsonl_store.py (two refusal-string rewords ONLY — verify nothing else moved) + libs/engine/tests/test_jsonl_store.py
- apps/loops/src/loops/commands/store.py (export arm -> refusal)
- docs/RECEIPT_ORDER_FOLD.md
- tests/architecture/test_rule_17_fold_order_prose_is_receipt_order.py (C0 scan-scope change + later allowlist shrinks)
- libs/engine/tests/test_arrival_authority_gate.py (G3 deletion)

Review categories (proof of work per category):
1. DISSOLUTION COMPLETENESS — is any live code path still reaching for the dissolved module or silently depending on receipt-order interleave? Run your own grep sweep (export_jsonl|rebuild_jsonl|_receipt_order|ExportResult|RebuildResult and also receipt-order-adjacent idioms: interleaved fact+tick streams ordered by rowid across tables). Check that nothing in libs/store still imports what died.
2. RESIDUE TRUTH — are the reworded refusal messages TRUE (do the paths they name exist and work)? Is every claim in the rewritten RECEIPT_ORDER_FOLD.md R3 true against the code at 074a1860? Is R2 still true?
3. CLI SURFACE — run `uv run --all-packages loops store export /tmp/x.db` and probe adjacent store subcommands for collateral damage (store, store stats, and any subcommand parsing that could have been disturbed by the arm removal — check completion/_args walk if it exists for store).
4. RULE 17 SCOPE CHANGE — the scan now uses git ls-files + docs/scratch exclusion, and the allowlist shrank in two later slices. Construct an evasion: can shipped prose now make a (ts,id)-as-fold-order claim that the pre-C0 rule would have caught but the current rule misses (other than docs/scratch, which is ruled)? Untracked-but-shipped paths, allowlist rows that should have been deleted but weren't, glob roots that moved.
