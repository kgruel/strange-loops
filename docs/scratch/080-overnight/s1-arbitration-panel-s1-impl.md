# Panel review — IMPLEMENTATION-REALITY lens on s1-arbitration.md (A1–A13)

*2026-07-17, Claude-family skeptic pass. Method: walked every amendment
against the actual code (declaration.py, sqlite_store.py, store_reader.py,
vertex_reader.py, cli/views/read.py, store/merge.py, store/slice.py),
queried every reachable live store with sqlite3, ran the S5 suite, and
empirically tested the ULID monotonicity claim. Re-derived, did not defer
to the codex pass.*

## Verdict: AMEND

The axis survives. I tried to break the selection/replay split and the A1–A13
package against the incumbent and could not invalidate the approach — but
four amendments are unimplementable or under-specified **as stated** against
the store corpus that actually exists, and one empirical premise the package
leans on is vacuous in the wild. Named amendments below (N1–N5), plus
confirmations and minor notes.

---

## The headline finding the codex pass under-weighted: the live corpus is pre-genesis

Queried every `.db` under `~/.config/loops`, `.loops/`, and gruel.network
(47 stores). Result: **exactly one `_decl.*` row exists in the entire live
corpus** — a single `_decl.genesis` in `~/.config/loops/tasks/data/tasks.db`
(rowid 1, id `01KXFGW1XHYRNHDXMK9G1V6PX1`, with matching
`store_meta.own_lineage`). Every other store — including
`.loops/data/project.db` (3,086 facts) and all five members of the `project`
aggregate — has **zero** `_decl` rows and **no `store_meta` table at all**.

Three consequences the synthesis does not state:

1. **A10 is unimplementable as written for the dominant corpus.** "Serialized
   cursor handles carry the store lineage id" — pre-genesis stores have no
   lineage id (no genesis, no `store_meta`). A cursor bookmarked today
   against `project.db` has nothing to qualify it with. → amendment N1.
2. **The receipt-group detection premise (A2) is empirically vacuous.** The
   task asked: are ceremony `_decl` rows actually contiguous-in-rowid with
   shared effective ts in the live store? Answer: there are **no multi-row
   ceremonies anywhere** to check. The premise holds *by construction* at
   write time — verified in code: `absorb_edit` stamps ONE `ts` for the
   whole ceremony (sqlite_store.py:796-797 "ONE effective ts for the whole
   ceremony") and INSERTs sequentially inside one `BEGIN IMMEDIATE`
   (sqlite_store.py:776, 841-846), so origin-store contiguity + shared ts is
   real. But it is *untested by any live data*; only conformance vectors can
   carry it. And it is a **heuristic, not an identifier** — see N2.
3. **Ontology-from-prefix is dormant on every store 0.8.0 will actually run
   against.** For the whole live corpus, `load_declaration` takes the
   `file-pre-genesis` path (declaration.py:248-249, 386-393, status
   vocabulary at :362) — the current FILE answers regardless of cursor. A
   historical `--at` read on a pre-genesis store therefore renders head
   ontology, which is precisely the retro-claim the design campaigns
   against. The honesty channel exists (`file-pre-genesis` status) but no
   amendment requires the cursor surface to render it. → amendment N3.

---

## Per-amendment walk (code-path verification)

**A1 (facts-only cursor) — IMPLEMENTABLE, one plumbing gap.**
Facts and ticks are separate rowid domains, confirmed: `since()` reads
`facts WHERE rowid > ?` (sqlite_store.py:867-874), `ticks_since()` reads
`ticks WHERE rowid > ?` (sqlite_store.py:1680-1683); no cross-table receipt
log exists. The fold boundary genuinely needs only the facts axis (ticks
never feed fold state). Watch's tick markers are placeable on the facts axis
via `fact_cursor → rowid` (`_cursor_rowid`, sqlite_store.py:1176-1190) —
and in the live project.db **all 58 ticks carry fact_cursor** (58/58
non-NULL, first 2026-06-12 15:03:48; verified by query), so marker
placement works for the whole live tick history. Gap: every incremental
read primitive returns rows **without id or rowid** —
`since()` (sqlite_store.py:873), `since_raw()` (:909), `replay_cursor()`
(:931) all select `kind, ts, [observer, origin,] payload` only. A
seq-labeled Watch feed cannot be built on any existing primitive; the
implementation plan must scope a new/extended incremental read that returns
`(rowid, id, …)`. Not a design flaw — a scope line item.

**A2 (receipt-group atomicity) — IMPLEMENTABLE, mechanism under-specified.**
Write-side premise verified in code (above). Detection by
contiguity+shared-ts survives merge in practice: merge re-appends source
facts `ORDER BY ts, id` (store/merge.py:99-103), and same-ts rows stay
adjacent under that sort; ceremony ids are minted within the same
millisecond so a foreign fact interleaving requires an exact float-ts
collision *and* a lexically-between id — negligible. Two real holes:
(a) **kind-filtered slice can split a group** — `slice_store(kinds=…)`
filters facts by kind (store/slice.py:31, 84-85), and one ceremony can span
kinds (`*-defined` + a different subject's `*-retired`), so a sliced store
can hold a partial group that detection would mis-read as complete;
(b) **no durable group id** — the codex amendment explicitly said "store a
group id/end ordinal … a shared timestamp is insufficient"; A2 adopts the
*framing* but never commits to the mechanism. See N2.

**A3 (id-era opacity) — VERIFIED IMPLEMENTABLE.** Exact-then-prefix lookup
treats ids as opaque text: `WHERE id = ?` then `id >= ? AND id < ?||'~'`
(store_reader.py:391-405) — `'~'` (0x7E) upper-bounds both uppercase ULIDs
and lowercase uuid4 hex. Archived pre-rebirth store confirmed mixed: 872
uuid4 + 1,181 ULID facts (my query matches the crossexam's 2,053). One
wording defect: A3 says `seq:N` is "rowid-ordinal" — the crossexam
distinguished *ordinal-by-rowid-order* from *rowid value N* and A3's phrase
re-collapses them. Today they coincide (append-only, no deletes), but the
spelling should be ROW_NUMBER-over-rowid, not rowid value. Minor.
Bonus empirical support for A3's "never order by id": the gen_id docstring
claims within-ms monotonicity (sqlite_store.py:41-43) and it is **false** —
5 trials × 5,000 ULIDs produced adjacent inversions (e.g.
`01KXRB21GEQKM… > 01KXRB21GENTM…`, same ms, random suffix inverted). Any
code path assuming id order == append order within a ceremony is wrong;
A3's rule is not just era-hygiene, it is required even in pure-ULID stores.
The docstring should be fixed as a rider.

**A4 (rebuild durability gated on §10) — VERIFIED HONEST.** No dump/rebuild
implementation exists anywhere (`grep -rn "def dump|def rebuild"` over
libs/ and apps/: zero hits); SPEC §10.5 labels vectors "to build"
(SPEC.md:1233+). Merge appends source facts in `(ts,id)` order, not source
witness order (store/merge.py:99-103) — A4's "slice/merge/rebirth today do
not preserve source witness order" is accurate. Downgrade-to-goal is the
correct posture.

**A5 (wall-clock two-step) — IMPLEMENTABLE, and it is the PRIMARY path, not
the fallback.** Verified: live project.db has 2,176 facts with
`ts <= 2026-06-01` but its first tick is 2026-06-12 — so **every wall-clock
address over most of the flagship store's history takes the labeled
event-time projection**, not the tick floor. The design should say this
plainly: for the current corpus, `--at <date>` ≈ labeled `--as-of` almost
everywhere, and the tick-floor branch only engages for post-June-12 marks.
Mechanically fine: `ticks_between(with_envelope=True)` returns
`fact_cursor` per tick (store_reader.py:285-350); resolving it to a rowid
needs a StoreReader-side `_cursor_rowid` twin (trivial; the write-side one
is sqlite_store.py:1176-1190).

**A6 (discrete scrubber) — pure contract, no code path to falsify.** OK.

**A7 (Watch control events + replay budget) — COHERENT with A1/A2.**
Coalescing "per receipt group" reuses A2's detection — same mechanism, same
N2 dependency. Full-reconstruction-as-contract is honest: `since_raw`
returns new rows in `(ts,id)` order (sqlite_store.py:894-918) and a
backdated arrival cannot be tail-applied, exactly as the crossexam showed.
No contradiction found between A7's per-group coalescing and A2's snap rule
(a Watch refresh lands on group boundaries by construction).

**A8 (dual selector) — IMPLEMENTABLE; envelope plumbing confirmed real but
bounded.** `load_declaration(as_of=float)` signature confirmed
(declaration.py:409-415); S5 suite passes as shipped (9 passed, including
`test_same_ts_edit_is_in_force_at_its_own_ts` — the test A8 pledges to
preserve). `vertex_tick_fold` takes only a Tick and anchors at
`as_of=tick.ts` (vertex_reader.py:1046-1070). The envelope IS already
fetched at the drill call sites (`fetch.py:1582` loads
`with_envelope=True` then calls `vertex_tick_fold(vertex_path, tick)` at
:1591 discarding it) — so carrying `fact_cursor` through is a signature
change plus threading, not an architecture change. A8's "real work, scoped"
is accurate.
**Contradiction check A2↔A8 (assigned): no contradiction, but a placement
gap.** A2 locates the snap at "cursor resolution" (the address layer). If
`load_declaration(at=WitnessPosition)` is the engine seam, a caller passing
a raw mid-group position bypasses the CLI resolver and silently folds a
half ceremony — the invariant must live in the engine selector
(snap-or-refuse inside `at=` resolution), not only in address parsing.
→ folded into N2.

**A9 (aggregate cursor vectors) — IMPLEMENTABLE, two under-specifications.**
Per-member plumbing exists: `_resolve_stores` yields member store paths
(vertex_reader.py:345) and per-member `StoreReader`s can answer tick-floor
queries; the combined fact query is per-store UNION ALL
(vertex_reader.py:359-366), so per-member rowid bounds slot in as per-SELECT
WHERE clauses. `aggregate-head` status exists (declaration.py:362, 383-386).
Gaps: (a) **tick-address cross-member semantics unstated** — A9 says
"wall-clock and tick addresses resolve per-member (tick-floor vector)"; for
the tick's own store that is its `fact_cursor`, but for the other four
members the only available mark is the tick's **ts — a signed claim** the
main design explicitly refuses to use silently. A9 must state that a
`tick:` address on an aggregate degrades to wall-clock-via-claimed-ts for
non-source members, disclosed. (b) **combined tick envelopes are
deliberately EMPTY** (vertex_reader.py "Combined/aggregation vertices
return EMPTY envelopes… chained=False, blank cursor fields" — confirmed in
`vertex_ticks`), so witness anchoring can never engage through the
aggregate `--ticks` drill even for chained member ticks; A8's fallback
notice would fire on every aggregate tick drill. Since `project` (an
aggregate) is the flagship UX, this needs either envelope pass-through for
single-member-attributable ticks or an explicit disclosure line in the
plan. → N4.
**Contradiction check A9↔A5 (assigned): no contradiction, one chimera to
disclose.** A9's per-member A5 fallback means one aggregate answer can mix
witness-anchored members with event-time-projected members — coherent under
per-member disclosure, but the plan should require the combined output to
label the mixed-mode state, not just each member.

**A10 (lineage-qualified handles) — NOT IMPLEMENTABLE AS STATED** for
pre-genesis stores, which is the entire live corpus except tasks.db (see
headline finding). → N1.

**A11 (semantic flags) — IMPLEMENTABLE, largest hidden scope item.** The
router refusal confirmed at cli/views/read.py:64-87 ("fold-state-as-of is
0.8.0 temporal-cursor work"). Lifting it requires BOTH modes on the fold
route, and `vertex_fold` today has **no temporal parameter of any kind**
(signature at vertex_reader.py:892-898: observer/kind/retain_facts only) —
no fact-selection cutoff, no ontology cursor. So A11 commits 0.8.0 to
building two full fold-selection paths (rowid-bounded and ts-bounded)
through `vertex_fold`/`_combined_read` plus the Operation IR (fold is an IR
pilot surface). Implementable; must be scoped as two paths, not one.

**A12 (unsealed tail) — IMPLEMENTABLE.** Last-sealed boundary =
last tick's `fact_cursor` rowid; comparison against the position is one
query. All live ticks carry fact_cursor (58/58), so the boundary is always
computable on the flagship store.

**A13 (pre-genesis honesty ladder) — IMPLEMENTABLE, one boundary note.**
`Unhistorized` exists and carries the genesis floor (declaration.py:141-162,
302-303). For `at=` the genesis comparison must be by genesis ROWID, not
`genesis_ts > as_of` (declaration.py:302 is ts-mode); a witness-mode twin
is straightforward. Pleasant property: a position just before the genesis
row and the position at it resolve to the same document set — only the
status marker differs. But A13 covers "before the genesis row" — it does
NOT cover "no genesis at all", which is the dominant live case → N3.

---

## Named amendments (the AMEND list)

- **N1 (breaks A10): define handle identity for pre-genesis stores.** The
  live corpus has no lineage ids. Options: refuse durable serialization
  pre-genesis (handle is session-local until `store adopt`); or qualify by
  a store-file surrogate with an explicit "unadopted — not portable" flag.
  Either is fine; silence is not, because the flagship stores are all
  pre-genesis today.
- **N2 (hardens A2/A7/A8): name the receipt-group mechanism and its
  enforcement point.** Commit to either (a) a durable group id/end-ordinal
  column (the codex ask), or (b) the contiguity+shared-ts+lineage heuristic
  as the 0.8.0 mechanism with its two named failure modes (kind-filtered
  slice can split a group — store/slice.py:84-85; heuristic is
  origin-guaranteed, not interchange-guaranteed) accepted as residue until
  §10. Whichever: the snap/refuse rule must be enforced inside the engine
  `at=` selector, not only the CLI address resolver, and a
  mid-group/split-group case belongs in the owed conformance vectors —
  no live data exercises ceremonies at all (one genesis row exists,
  total, across 47 stores).
- **N3 (extends A13): pre-genesis-store cursor reads must carry the
  `file-pre-genesis` status.** On every current store, `--at <anything>`
  resolves ontology to the CURRENT file — head ontology rendered under a
  historical cursor. The shipped status channel
  (declaration.py:362 `DECLARATION_STATUSES`) must be a required part of
  the cursor output contract, or the flagship demo silently retro-claims.
- **N4 (completes A9): specify `tick:` on aggregates and the empty-envelope
  reality.** State that non-source members resolve via the tick's claimed
  ts (disclosed), and either pass envelopes through for member-attributable
  ticks or document that aggregate tick drills always take A8's unanchored
  fallback (`vertex_ticks` combined path returns `chained=False` envelopes
  by design).
- **N5 (rider, supports A3): fix the false gen_id docstring and scope the
  id-bearing incremental read.** python-ulid is NOT within-ms monotonic
  (empirically: adjacent inversions ~1/5,000 in tight loops) — correct
  sqlite_store.py:41-43, and note that Watch's seq feed needs a new
  incremental primitive returning `(rowid, id, …)` (all of
  `since`/`since_raw`/`replay_cursor` omit both today).

## What I tried to break and could not

- The A2 write-path premise: one shared ts + contiguous append inside
  `BEGIN IMMEDIATE` is real (sqlite_store.py:776-847); merge's
  `ORDER BY ts, id` re-append preserves group adjacency in practice.
- A8's compatibility pledge: the shipped S5 suite (9 tests, including the
  same-ts tie-break at test_ontology_as_of.py:162-176) passes and its
  semantics survive untouched under a dual-selector split.
- A1's facts-only sufficiency for fold: ticks never feed fold state; tick
  markers are placeable via fact_cursor on the facts axis for 58/58 live
  ticks.
- A5's fallback honesty: confirmed no silent semantic swap is needed —
  the event-time projection is already the design's explicit mode and the
  label requirement is enforceable at one code seam.
- A9↔A5 and A2↔A8 contradiction hunts (assigned): no true contradictions;
  each resolved to an under-specification (N4, N2) rather than a conflict.
