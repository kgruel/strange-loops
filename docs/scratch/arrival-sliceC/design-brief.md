# Cut C — ORDERING: design brief (draft, pre-ratification)

Arc: arrival-migration-arc · Branch: feat/arrival-libs @ 2bc91cfb · Plan: plan:arrival-libs-slice-C (RULED, Kyle, 2026-08-17)
Pipeline: antigravity-impl-pipeline (agy fleet) · Arbiter: main session · Date: 2026-08-19

## 1. The ruled plan, verbatim

> Wave-1 slice C — ORDERING. Declared projection order: 'arrival' | 'by KEY'; substrate read
> primitive ordered(prefix=W, key=K) totalized by (K(record), record.id); id NEVER semantic time.
> _receipt_order (libs/store/src/store/jsonl.py:104-126) DISSOLVES with residue swept in the same
> change — scoped to LIBS (the frozen sidecar last-0.x reader keeps its copy by design); its
> removal pre-migration is EXPLICITLY ACCEPTED by Kyle. generate_lens.py extends from ts-only to
> arbitrary declared keys. CAS as qualified predicate over the arrival axis, preserving
> lineage-filtered _decl.*-only semantics (sqlite_store.py:1411-1438), INCLUDING the escaped token
> in the persisted intent record (ceremony.py:432). PR#8: REWRITE CAS token coordinate -> arrival
> head; REWRITE combined-read fold fork (vertex_reader.py:390,:403-406 + sdk read.py) — combined
> read declares a projection ordering; KEEP Spec.replay_from, VertexHandle checkpoint machinery,
> benchmark arms, Rule 17. GATE: conformance lens vectors under declared keys; projection taxonomy
> drives checkpoint dispatch tests.

## 2. Anchors re-pinned to 2bc91cfb (plan's line numbers are stale)

| Plan anchor | Current location (verified by arbiter read at 2bc91cfb) |
|---|---|
| `_receipt_order` jsonl.py:104-126 | libs/store/src/store/jsonl.py:104-126 — UNCHANGED. Interleaves fact/tick rows for export; anchor-inheritance keyed sort. |
| CAS predicate sqlite_store.py:1411-1438 | libs/engine/src/engine/sqlite_store.py:1448-1475 `_declaration_head_in_txn` (returns `(rowid, id)`), :1477-1493 `declaration_head()` public reader. Consumer: absorb_edit compare at :1098-1106. |
| Escaped token ceremony.py:432 | libs/engine/src/engine/ceremony.py:423-441 `_write_intent` — `old_decl_head: list(preview.expected_head)` persisted as `[rowid, id]`. Producer read at ceremony.py:382 (`diff_declaration`); CLI read at apps/loops/src/loops/commands/store.py:1257. |
| Fold fork vertex_reader.py:390,403-406 | libs/engine/src/engine/vertex_reader.py:347-445 `_combined_read`; the fork: `single_store` → sort by rowid (r[6]), else `(ts, id)` (r[2], r[0]). Comment names itself "interim state pending the multi-store receipt-order ruling." |
| sdk read.py | libs/sdk/src/sdk/read.py — aggregate branches in read_summary:106-241, read_facts:244-384, read_state:430-481, read_ticks:484-521, read_fact_by_id:523-557, search_facts:560-662, resolve_entity:664-727, read_timeline:729-899. |
| generate_lens.py | spec/conformance/generate_lens.py — docstring :3-14 pins `(ts, id)` READ LENS as the combine fallback; vectors at spec/conformance/vectors/lens/; harness libs/engine/tests/test_conformance_lens.py:34-36 (loader), :74-89 (runner). |

## 3. KEEP fences (must not change; enumerate for implementer prompts)

- `Spec.replay_from` — libs/atoms/src/atoms/spec.py:128-148 (suffix replay, single-deep-copy contract).
- VertexHandle checkpoint machinery — libs/engine/src/engine/handle.py:752-1340; dispatch tests libs/engine/tests/test_handle_incremental.py (:110-120 equivalence, :164-173 replay_mode).
- Benchmark arms — benchmarks/characterize.py:206-224 (probe_store), :242-320 (probe_vertex_layers).
- Rule 17 test SEMANTICS — tests/architecture/test_rule_17_fold_order_prose_is_receipt_order.py (its file-selection has a ruled fix, §5 Q5, but the prose rule itself stays).
- Frozen sidecar last-0.x reader keeps its own receipt-order copy (fence OUT of the dissolution sweep). [e1 residue map pending — fold in before ratification]
- ArrivalStore write path / catch-up (Cut B, converged) — Cut C is read-side; write-side changes are out of scope except the CAS re-point.

## 4. Current-state facts the design leans on (arbiter-verified)

- CAS token today: `(rowid, id)` per `_declaration_head_in_txn`; test test_absorb_edit.py:221-287 `test_cas_token_rides_the_receipt_axis` pins receipt-axis-not-(ts,id) via a backdated-declaration construction. Re-pointing the token to arrival head means that test's PINNED AXIS changes — the test must be rewritten to pin the ARRIVAL axis apart from both (ts,id) and rowid.
- Intent record: `old_decl_head` rides `[rowid, id]` (JSON list) with `_INTENT_VERSION` versioning; recovery classifies bad intents as IntentCorrupt (refuse, not guess).
- Arrival axis (Cut A/B): dense per-log ordinal (`ord`), ResumeMark = (lineage, offset, ordinal); merge lands as arrival append; rowid-survival ratchet at libs/engine/tests/test_arrival_rederivation_rowids.py:155-175 pins rowid≡ord+1 correspondence class.
- Combined read today: per-store rowid is the only receipt axis; no cross-store arrival total order exists (ordinals are per-log).
- Read-primitive surface: SqliteStore.since/since_raw/replay_cursor/between all rowid ASC; latest_by_kind* are (ts DESC, id DESC); StoreReader.key_prefixes takes (kind, key_field, prefix) — closest existing shape to `ordered(prefix, key)`.

## 5. Must-answer questions for the ratification gate (design fact must state each)

**Q1 — What does 'arrival' mean for a MULTI-store combined read?** (load-bearing)
Ordinals are per-log; a combined view has no arrival total order, same as it had no rowid one.
Options: (a) combined reads may only declare 'by KEY' — 'arrival' is a single-store-only
projection order, refused loudly on aggregates; (b) combined-'arrival' = interleave by some
cross-store coordinate (which?). If (a), the fold-fork rewrite becomes: single store → declared
order honored incl. 'arrival'; multi store → the declaration must be a KEY (default ts as today).
The design fact must say which, or the rewrite re-derives the fork it dissolves.

**Q2 — CAS token shape and the intent record.** Re-pointing token coordinate → arrival head
changes the persisted `old_decl_head` grammar. Does `_INTENT_VERSION` bump? Do old-version
intents refuse loudly (IntentCorrupt posture)? What is the token for the plain-sqlite store
family (no arrival log) — does declaration_head keep (rowid, id) there, making the token
mode-qualified?

**Q3 — Where does `ordered(prefix, key)` live?** Candidates: StoreReader (read-side inspector,
where key_prefixes already lives), SqliteStore (inherited by all three families), or ArrivalLog.
And: is by-KEY a read-time sort (as _combined_read does today in Python) or does it need an
index? Totalization is (K(record), record.id) per the plan; id is tie-break only, never semantic time.

**Q4 — What is the projection taxonomy as a TYPE?** 'arrival' | 'by KEY' needs a first-class
home (enum/dataclass in atoms? a lang decl?) since the GATE says "projection taxonomy drives
checkpoint dispatch tests" — tests must be able to enumerate it. Where is it declared per read:
lens decl, Spec field, read-API parameter?

**Q5 — Rule 17 git-ls-files fix: pre-C or in-C?** Verified at 2bc91cfb: `_scan_targets`
(tests/architecture/test_rule_17_fold_order_prose_is_receipt_order.py:147-179) walks the
filesystem via rglob — docs/scratch/*.md ARE scanned (no exclusion), and untracked files get
judged as shipped prose. Bit three agent drafts in Cut B (briefs must paraphrase retired
vocabulary). Proposed: fix as slice C0 (tiny, pre-everything) — select via `git ls-files`,
exclude docs/scratch; shrink-only semantics preserved.

**Q6 — generate_lens "arbitrary declared keys": which keys, declared where?** Today the lens
area pins (ts, id) only. Extension needs the key-declaration source of truth (LensDecl has no
key attribute today — lang/ast.py:639-649). Minimal form: vectors parameterized by key field
with (K, id) totalization? Or full lang-level key declaration (bigger blast radius → would need
its own ratify-gate one level down per impl-pipeline stage 0)?

## 6. Probable slice seams (NOT a commitment; decomposition after ratification)

- C0: Rule 17 scan-scope fix (if ruled pre-C).
- C1: substrate `ordered(prefix, key)` primitive + projection taxonomy type + `_receipt_order` dissolution w/ residue sweep.
- C2: CAS token → arrival head (sqlite_store + ceremony + intent record + CLI reader + test-axis rewrite).
- C3: combined-read fold fork rewrite (vertex_reader + sdk read.py) under the declared-order taxonomy.
- C4: generate_lens arbitrary-key vectors + checkpoint-dispatch gate tests.

## 7. Exploration receipts

Six flash-low explorers (e1-e6), shared read-only worktree explore/arrival-sliceC, outputs in
scratch (to be committed under docs/scratch/arrival-sliceC/explorers/). One citation per report
grepped by the arbiter; five of five landed reports verified verbatim. [e1 pending]
