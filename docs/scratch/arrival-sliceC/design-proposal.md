# Cut C — ORDERING: design proposal (for ratification)

Arc: arrival-migration-arc · Branch: feat/arrival-libs @ 2bc91cfb · Plan: plan:arrival-libs-slice-C (RULED 2026-08-17)
Prior contract: decision:design/arrival-sliceB-projections (Cut B, converged). Drafted 2026-08-19 after
six-explorer recon (docs/scratch/arrival-sliceC/explorers/) and six arbiter-gate rulings (Kyle, this session).

## Spine

Ordering is DECLARED, never inferred. The taxonomy `Arrival | ByKey(field)` and its single
totalization live in atoms; every reader — StoreReader, the combined read, the sdk read paths,
the conformance generator — consumes that one primitive. The store-count fork in `_combined_read`
and the receipt-order interleave in the legacy bridge both dissolve into it. The CAS token names
an arrival coordinate, the axis the store actually accretes on. `.arrival` is the only real
store; the legacy families are frozen byte-for-byte pending the migration arc, never extended.

## Q1 — Ordering vocabulary and totalization (the cut's primitive) [RULED + refined]

- `atoms` grows a frozen `Ordering` union: `Arrival()` | `ByKey(field: str)`. No lang grammar
  change this cut: a later `LensDecl` key attribute is a thin constructor over this type
  (dissolution test — zero rework when it lands).
- ONE totalization function beside the type, the only definition of the sort key anywhere:
  - `ByKey(K)`: sort key `(K(record), record.id)`, id ascending. **id is tie-break only,
    NEVER semantic time (NON-NEGOTIABLE, plan verbatim).**
  - `Arrival()`: the substrate's native order (per-store: rowid ≡ dense ordinal correspondence,
    pinned by the Cut B rowid-survival ratchet). Not expressible cross-store (Q2).
- Missing K: a record without the field is NOT in the `ByKey(K)` projection — a key names what
  it projects; absence is non-membership, stated in the docstring and pinned by a vector.
  It is exclusion-by-declaration, not silent loss: the caller named K.
- Type-mixed K values (e.g. `"5"` vs `5` across records): REFUSE loudly. Mixed types under one
  declared key is a declaration error against the data, not something a comparator may paper
  over with a coercion.
- K is a flat payload field this cut (`ts` remains column-backed as an optimization detail,
  same semantics). Dotted paths: not this cut, not blocked by this design.
- Consumers import the one totalization; three near-copies (store_reader / vertex_reader /
  generate_lens) are ruled out by construction. Construction over detection: no new arch
  ratchet unless review finds drift pressure (per decision:practice/construction-vs-detection-ratchets).

## Q2 — 'arrival' is single-store-only [RULED]

Arrival ordinals are dense PER-LOG; a combined view has no arrival total order — the same
structural fact that made rowid unusable there. Therefore:
- Single-store reads: may declare `Arrival()` (default) or `ByKey(K)`.
- Aggregate/combined reads: MUST be `ByKey(K)`; default `ByKey('ts')` (today's lens semantics).
  Declaring `Arrival()` on an aggregate REFUSES loudly, naming the reason and the alternative.
- `_combined_read`'s `single_store` fork (vertex_reader.py:403-406) DISSOLVES into the declared
  ordering: the function takes an `Ordering`, resolves defaults per the rule above, sorts via
  the atoms totalization. The "interim state pending the multi-store receipt-order ruling"
  comment retires — this is that ruling. sdk read.py aggregate branches route the same way.
- Equivalence pin: single-store declared-`Arrival()` produces the row sequence the old rowid
  sort produced, byte-identical (gate item).

## Q3 — CAS token = arrival head [RULED]

- The CAS token's one designed meaning: the arrival-axis coordinate of the newest self-lineage
  declaration — `(record_ordinal, fact_id)`, where `record_ordinal` is the arrival ordinal of
  the log record whose expansion carries the row (a batch record's rows share its ordinal).
- The predicate keeps its lineage-filtered `_decl.*`-only semantics verbatim (foreign-lineage
  rows excluded, own genesis participates) — only the coordinate axis changes.
- The escaped token: `_write_intent`'s `old_decl_head` now persists the arrival coordinate.
  `_INTENT_VERSION` BUMPS; recovery refuses old-version intents loudly under the existing
  IntentCorrupt posture (refuse, not guess). Shape stays `[int, str]`; the bump is what keeps a
  shape-identical stale coordinate from being misread as an ordinal.
- Legacy families (plain sqlite, jsonl): `declaration_head` behavior FROZEN byte-for-byte —
  no mode-qualification machinery, no extension. Their retirement is the migration arc's.
  (Kyle: "the only real store is .arrival"; we don't design for the condemned, we just don't
  touch them.)
- Test axis rewrite: `test_cas_token_rides_the_receipt_axis` (test_absorb_edit.py:221-287)
  currently pins rowid-vs-(ts,id) apart. Its Cut C successor pins the ARRIVAL axis apart from
  (ts,id) via the same backdated-declaration construction on an ArrivalStore.
- Gate item: token values agree with a from-scratch walk of the arrival log (the log stays the
  authority; the mechanism that answers faster is an implementation detail the implementer
  proposes).

## Q4 — `ordered(prefix=W, key=K)` lives on StoreReader, read-time sort [RULED]

- StoreReader (read-side inspector, where `key_prefixes` already lives) grows
  `ordered(prefix, key)`: records in the prefix `[0..W)` of the store's stream, totalized by
  the atoms primitive. Read-time sort (Python-side, matching `_combined_read`'s measured
  ORDER-BY-avoidance); NO new sqlite index this cut — an index is a later optimization the
  benchmark arms would have to justify.
- Perf: the pre-ship benchmark item inherited from Cut B extends to cover `ordered()` on the
  largest real store (wave-tail, before ship — not a slice gate).

## Q5 — `_receipt_order` dissolution takes the whole bridge module [RULED plan + scope note]

- `_receipt_order` cannot be removed alone: it is the ordering heart of `store/jsonl.py`, the
  sqlite→jsonl-canonical migration bridge. Exporting under any other order would rewrite
  receipt history on rebuild (log line order determines rebuilt rowids, i.e. fold order).
  So the MODULE dissolves: `_receipt_order`, `export_jsonl`, `rebuild_jsonl`, `ExportResult`,
  `RebuildResult`, the ORDERING RULE docstring (jsonl.py:14-44), and its direct tests
  (test_jsonl.py). The sqlite→jsonl migration path is superseded: migration targets `.arrival`
  (migration arc), and the planned frozen last-0.x sidecar reader carries its own copy of
  receipt-order semantics BY DESIGN (plan verbatim; e1 confirmed no sidecar exists yet — there
  is nothing to fence, only a future home to name).
- Residue swept in the same change (dissolution-residue rule):
  - `store/__init__.py` exports (lines 29, 38, 52).
  - `sl store export` CLI arm (apps/loops/src/loops/commands/store.py:751-754) — retires or
    refuses-with-pointer; implementer proposes, arbiter rules at gate. **apps/ is therefore NOT
    diff-empty this cut** (departure from B, forced by the dissolution's own residue rule).
  - Refusal-message pointers naming `store.jsonl.export_jsonl` as the way out:
    store/merge.py:120, engine/jsonl_store.py:689, :755 — reworded to name the surviving path.
  - docs/RECEIPT_ORDER_FOLD.md R2/R3 sections (Cut B's R1 note: "R2/R3 stay for cut C") — this
    is cut C; sweep what the dissolution makes false, keep what Rule 17 still pins as true for
    single-store fold order.
- `JsonlStore` (engine) itself is UNTOUCHED — frozen legacy family per Q3 posture. Only the
  libs/store bridge dissolves.

## Q6 — generate_lens parameterizes by key against the primitive [RULED]

- `spec/conformance/generate_lens.py` grows a key axis: each LensCase names its K; totalization
  pinned as `(K(record), id ASC)` via (or byte-agreeing with) the atoms primitive.
- Existing ts vectors become the `ByKey('ts')` family — existing vector files' ordering
  semantics UNCHANGED (they are normative artifacts loops-go reads; regeneration must be
  byte-identical or the diff is a finding).
- New vector families: at least one non-ts payload key; adversarial cases for the ruled
  postures — missing-K non-membership, type-mixed refusal, id tie-break under equal K.
- Checkpoint dispatch gate: tests enumerate `Ordering` variants — `Arrival()` licenses
  checkpoint + `Spec.replay_from` suffix replay; `ByKey(K)` does not (cold fold). This is the
  "projection taxonomy drives checkpoint dispatch tests" GATE line made concrete.

## Q7 — Rule 17 scan scope (slice C0) [RULED]

- First commit of the cut, before everything: `_scan_targets`
  (tests/architecture/test_rule_17_fold_order_prose_is_receipt_order.py:147-179) selects via
  `git ls-files` (tracked = shipped) and excludes `docs/scratch/`. Shrink-only: the scanned set
  narrows, the rule text and its judged semantics are untouched. Frees every Cut C brief and
  receipt to quote retired vocabulary verbatim.

## KEEP fences (NON-NEGOTIABLE, verbatim from the ruled plan)

- `Spec.replay_from` (atoms/spec.py:128-148) — untouched.
- VertexHandle checkpoint machinery (engine/handle.py:752-1340) — untouched; C5 tests DISPATCH
  on the taxonomy, they do not modify the machinery.
- Benchmark arms (benchmarks/characterize.py) — untouched.
- Rule 17 semantics — scan scope only (Q7); the prose rule stands. Single-store fold order IS
  still receipt order; nothing in this cut changes fold replay.
- ArrivalStore write path / catch-up / ceremony persist (Cut B, converged) — read-side cut;
  the only write-side change is the CAS coordinate (Q3).
- Legacy store families (SqliteStore, JsonlStore engine classes) byte-for-byte except the
  three refusal-message pointer rewords named in Q5.

## Commit seams

- C0: Rule 17 scan scope (Q7).
- C1: atoms `Ordering` + totalization + unit vectors for the postures (Q1).
- C2: StoreReader.ordered + bridge-module dissolution with residue sweep (Q4, Q5).
- C3: CAS re-point + intent version bump + test axis rewrite (Q3).
- C4: combined-read/sdk rewrite under declared ordering (Q2).
- C5: generate_lens key families + checkpoint dispatch tests (Q6).
Dependencies: C1 → {C2, C4, C5}; C0 independent-first; C3 independent of C1 (touches the
arrival axis, not the totalization) but sequenced after C0.

## GATE (empirical oracle for slices and reviews)

1. Conformance lens vectors under declared keys; existing ts family byte-identical.
2. Checkpoint dispatch tests driven by `Ordering` variants.
3. Single-store `Arrival()` ≡ old rowid sequence, byte-identical row order.
4. Aggregate + `Arrival()` refusal test (loud, names the alternative).
5. CAS token agrees with a from-scratch arrival-log walk; stale-intent refusal exercised with
   a real pre-bump intent file.
6. rowid-survival ratchet (test_arrival_rederivation_rowids.py) stays green.
7. Full suite green in the MAIN checkout post-merge (worktrees are environmentally weaker).
