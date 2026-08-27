SCOPE 3 — the arrival axis in anger: CAS head and the combined read (slices C3, C4).

Files under review (read every changed line; `git diff a49997cd..074a1860 -- <path>`):
- libs/engine/src/engine/arrival_store.py (_declaration_head_in_txn) + libs/engine/src/engine/ceremony.py (_INTENT_VERSION bump + IntentCorrupt docstring)
- libs/engine/tests/test_arrival_cas_head.py + libs/engine/tests/test_ceremony_orchestration.py (pre-bump intent test)
- libs/engine/src/engine/vertex_reader.py (resolve_ordering, _fetch_combined_rows, _combined_read ordering param)
- libs/engine/tests/test_combined_read_ordering.py
- libs/sdk/src/sdk/read.py + libs/sdk/tests/test_read_ordering.py

Review categories (proof of work per category):
1. CAS COORDINATE CORRECTNESS — construct stores where the head walk could go wrong: interleaved writers, a declaration inside a batch alongside foreign-lineage rows, genesis-only stores, a store whose reconciled mark lags the log tail (append without reindex if reachable). Compare declaration_head() with your own raw parse of the .arrival file in every case.
2. INTENT VERSIONING — probe the recovery path: v1 intent (refuse), v2 intent valid, v2 intent with a garbage coordinate shape, missing v field. Does any path GUESS instead of refusing? Is there any writer that still produces v1?
3. COMBINED-READ EQUIVALENCE AND REFUSAL — build your own single-store fixture where arrival != ts order; verify declared-Arrival == default == old rowid semantics and ByKey('ts') == the old aggregate lens. Verify the aggregate+Arrival refusal at engine AND sdk surfaces, and that sdk ordering=None paths call neither resolver nor totalize (read the code path; then probe that legacy read_facts behavior is byte-stable).
4. FOLD-INPUT CONSEQUENCES — _combined_read feeds folds. ByKey(K) with missing-K now EXCLUDES facts from the fold input (ruled). Probe for a today-reachable path where the DEFAULT (no declaration) changes fold input vs pre-cut behavior — any store where old (ts,id)-sorted fold input differs from new ByKey('ts')-totalized fold input (e.g. payload ts vs column ts, NULL handling, ts precision). The defaults must be behavior-identical for every existing caller; find a counterexample or prove work done trying.
