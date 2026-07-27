# loops-go protocol queue — the coordination ledger

*2026-07-27. One document answering "what does loops-go owe." It replaces a
scatter — three items in `docs/scratch/080-overnight/final-contracts.md`, a
fourth in `docs/dev/lifecycle-spec-delta-090.md`, a fifth carried only by an open
thread, and the sole enumeration of the vector families sitting in a `.html`
dashboard. That scatter is what let the batch be miscounted (§ Settled below).
Grounding and receipts: `docs/scratch/010-wave/loops-go-grounding.md`.*

This is a ledger, not a design. Nothing here resolves an open question; the
design gate does that.

**Repo state.** loops-go is at `94f7987` (branch `r2-replay-conformance`),
untouched since 2026-07-02. Nothing in this queue has partially landed — every
item is either fully owed or fully resident on the Python side.

---

## The queue — five members

| # | Item | Source | Status | Blocks |
|---|---|---|---|---|
| 1 | **GlobalReceiptPosition** — one durable, monotonic store-wide receipt ordinal (or an append log both tables reference), with a stated rule for whether a tick occupies an ordinal | `080-overnight/final-contracts.md:135`; originating FATAL at `s1-codex-crossexam.md:46`; carried by `design:architecture/temporal-cursor-witness-prefix` (RATIFIED 2026-07-17) | **owed** — never entered SPEC.md (zero hits for "receipt ordinal"/"store-wide"); `libs/engine/src/engine/witness.py:28` names it as a deliberate non-implementation | vector family 5; SPEC §10; the `to_review` JCS/rebuild claim (`apps/loops/src/loops/surface.py:1330`) |
| 2 | **`_decl` receipt-group durable id** — group id carried in the `_decl` event payload (a §9.2 payload touch) | `final-contracts.md:30-37` (A2 hardened) | **split**: the interim *heuristic* SHIPPED in 0.8.0 (`witness.py:205 receipt_group_span`, `:84 MidReceiptGroupPosition`, guarded at the engine `at=` selector); the *durable id* is owed (`grep group_id sqlite_store.py` → 0) | vector family 4, unless the heuristic is pinned instead (Q2) |
| 3 | **Five vector families** | `final-contracts.md:138-140`, enumerated only at `080-overnight/morning-dashboard.html:86` | **1 of 5 delivered** — see the family table below | the conformance thesis |
| 4 | **`lifecycle` payload field** on `_decl.kind-defined` | `docs/dev/lifecycle-spec-delta-090.md` (2026-07-18), per `090-wave/arbitration.md:125-129` (S5-F3) | **owed, explicitly non-blocking** — additive payload field on an existing document; no `DECLARATION_PROTOCOL_VERSION` bump | nothing |
| 5 | **Tombstone vocab** for the `lens` / `vertex-defined` singleton | `thread:decl-lens-tombstone-vocab-gap` (open, 2026-07-13) | **owed** — needs a **new frozen kind**, the hardest class of §9.2 change | nothing yet, but it is the second-hardest item after #1 |

Items 1 and 2 are bound as one coordination by `final-contracts.md:33` ("the two
protocol amendments travel as one"). Items 4 and 5 accrued after that
ratification and are not bound by it — see Q5.

---

## Vector families

Five, not three and not eight (see Settled). The name in the left column is the
one to use; `morning-dashboard.html:86` is the only prose that enumerates them.

| # | Family | Upstream | Blocked on |
|---|---|---|---|
| 1 | §8.7 two-authorities late-arrival — event order and witness order disagree; fold state follows §6.2, window membership follows §8.4 | `loops-go/SPEC.md:912-923` ("Conformance surface **(to build)**") | witness-exposing reader (below) **+** the whole §8 chain layer, absent in Go |
| 2 | Cursor-selection — fold state at a witness position, incl. a backdated arrival straddling the cursor | no upstream §; created by `design:architecture/temporal-cursor-witness-prefix` | witness-exposing reader **+** the cursor's portable form (Q1) |
| 3 | **Same-`ts` id tie-break** | `SPEC.md` §4.6 + §6.2's closing note | **nothing — DELIVERED 2026-07-27** (`testdata/stores/tie.db`, `TestSameTSIDTieBreak`) |
| 4 | Mid-/split-group ceremony | §9.2, via A2 | witness-exposing reader **+** durable group id, or a decision to pin the heuristic (Q2) |
| 5 | §10 dump / rebuild witness-order round-trip | `SPEC.md:1235-1245` | witness-exposing reader **+** GlobalReceiptPosition **+** a §10 implementation that does not exist |

### The prerequisite the batch never named

Families 1, 2, 4, and 5 all need something no queue member lists: **a Go-side
witness-exposing reader**. `loops-go/store/sqlite.go` selects
`kind, ts, observer, origin, payload, id ORDER BY ts, id` — no rowid in the
projection, no cursor parameter anywhere in the package. A witness-axis vector
cannot even be *consumed* until Go can (a) put `rowid` in the projection and
(b) offer a prefix-select-then-replay path: select `WHERE rowid <= P`, then
replay the selected set in `(ts, id)` order.

That is **selection on one axis, ordering on the other** — the distinction the
ratified design rests on (`libs/engine/src/engine/witness.py:1-15`) and the one a
naive implementation collapses. The corpus already documents the trap: replaying
the merge fixtures in rowid order diverges from the pinned expectation in *both*
directions, and the two rowid replays disagree with each other
(`dossier-go-vectors.md:316-340`).

### Family 3, as delivered

Shipped as a **store fixture**, not a fold vector. The id-less fold-vector schema
(`{name, folds, initial, payloads, expected, order_sensitive}`) applies payloads
in array order, so ordering is an *input* there and never something under test;
SPEC §6.2 says so itself. A `.db` carries ids, and the Go reader's
`ORDER BY ts, id` is the code under test.

`tie.db` puts four facts at one `ts` with ids running against insertion order,
plus a fifth at a lower `ts` with the highest id and the last rowid — so rowid
order and `(ts, id)` order disagree on every row, and `ts` is pinned as primary
with `id` as tie-break rather than sort key. The fixture ships both answers
(`expected`, `expected_rowid_order`); the test asserts a match against the first
and a mismatch against the second, so it cannot decay into a tautology.

**It surfaced a new design-gate item — see Q6.** The §4.6 `TopN` equal-`by`
eviction rule is not implementable in Go under the current value model, which is
why this family had gone unbuilt rather than merely unprioritized.

---

## Settled — recorded so it stops being re-litigated

**The JCS sequencing gate is SATISFIED.** SPEC §10.5 carries a hard gate: the
incumbent's `_canonical_bytes` → JCS migration and chain re-anchor (§8.1) MUST
land before any §10 vectors are generated. It landed —
`libs/engine/src/engine/sqlite_store.py:115-122` is JCS/RFC 8785, citing
`decision:design/attestation-canonicalization-jcs`, with pre-JCS chains
re-anchored at the swap. Families 1 and 5 are **not** blocked on
canonicalization. Family 5 is blocked on §10 not existing at all: `sl store`
offers `verify | rebirth | reanchor | absorb | adopt | ticks | stats | reindex`
— no dump, no rebuild.

**The owed vector count is FIVE, not eight.** The framing that adds "three
conformance-oracle owed vectors (§8.7 two-authorities late-arrival,
cursor-selection at a witness position, same-`ts` id tie-break)" *on top of* the
five families double-counts: those three **are** families 1–3.

**"Five oracle families" ≠ "five vector families."** `dossier-go-vectors.md:85`
says "the five oracle families," meaning the *existing, shipped* suite; the five
vector families are the *owed* ones. One careless read apart, and one means
already-certified while the other means not-started. The oracle count is also
wrong: SPEC's appendix names six oracles, `TestMergeCommutativity` was added
later without being listed, and the dossier's own §1 reports seven top-level
tests. Neither 5, 6, nor 7 agree — use test names, not counts.

**"No live data exercises ceremonies" is REFUTED.** `final-contracts.md:36-37`
recorded "1 `_decl` row across 47 stores." A real five-row absorb ceremony exists
at `~/.config/loops/tasked/data/tasked.db` rowids **356–360** — one shared `ts`
(2026-07-18 15:08:20.572950), one shared lineage, multi-subject — written the day
after that measurement. The shipped heuristic was run against it live and is
correct on it: interior rows 356/357/359 refuse, row 360 (the ceremony's last)
admits, and the 355 genesis singleton is never mid-group. So family 4 has a real
ceremony to model from rather than one invented from the spec — and the heuristic
now has empirical evidence it lacked at ratification.

**Q4 is settled by this change: generation lives in the loops workspace.** The
generators are loops Python importing `atoms`/`engine`/`store`; every vector they
emit is loops output. They now live at `tools/` in this repo and take the loops-go
checkout as an argument (`--loops-go DIR` / `$LOOPS_GO_REPO`). Previously they sat
in `loops-go/tools/` and reached back with
`sys.path.insert(0, Path.home() / "Code" / "loops" / ...)`, bypassing the uv
workspace, any released artifact, and any version pin. The drift that invites was
already visible: the M1 generator's docstring described the Go reader as
`ORDER BY rowid` long after `store/sqlite.go` moved to `ORDER BY ts, id`.

This is not a package and does not create one. `ARCHITECTURE.md`'s surfacing
charter already ruled that "app-side surfacing occupants (the TUI shell,
cross-implementation protocol artifacts) belong to the layer by role without
being libs" — a `libs/protocol` would contradict the charter it implements and
trip `test_every_lib_declares_a_layer`.

---

## At the design gate — not answered here

**Q1 — How does a cursor-selection vector express its cursor?**
`witness.py:544` `durable_handle` returns the portable `fact:<lineage>/<id>` for
adopted stores and **refuses (`None`) for unadopted ones**, inventing no
surrogate. All loops-go fixture stores have zero `_decl` rows — every one is
unadopted, so none can carry a durable handle today. Either express the cursor as
`seq:N` (works now, but is fixture-local and re-derived on regeneration) or adopt
the fixture stores by minting a genesis — which pulls §9 into Go, and §9 is
PROVISIONAL with zero Go implementation.

**Q2 — Does the ceremony vector pin the heuristic, or wait for the durable id?**
The heuristic is now verified against real live data (above), which makes pinning
it tempting. But `witness.py:216-221` calls it *"origin-guaranteed by the write
path, not interchange-guaranteed: a kind-filtered slice can split a group across
stores."* A vector pinning contiguity+shared-`ts` would certify a boundary rule
the amendment intends to replace, and would then be retired rather than extended.

**Q3 — Is GlobalReceiptPosition a column, a table, or a derived ordinal?**
The amendment is disjunctive and the disjunction was never resolved. Both
branches are store-schema changes across the live corpus, and no migration path
is stated anywhere in the batch. The two sub-questions — "column or log" and
"does a tick consume an ordinal" — have different blast radii and are currently
bundled.

**Q5 — Does the batch ship as one coordination, or split?**
`final-contracts.md:33` binds items 1 and 2. The queue has since grown to five,
and the newcomers have opposite urgency: `lifecycle` is additive,
forward-compatible, and documented as not blocking the oracle, while the
tombstone vocab needs a new frozen kind. Shipping all five as one coupling makes
a non-blocking additive field wait on a store-schema migration.

**Q6 — How does an unordered-map implementation satisfy §4.6? (NEW, 2026-07-27)**
Surfaced by building family 3. §4.6 is normative: *"An implementation MUST evict
equal-`by` items by `(ts, id)` arrival order (equivalently: preserve `(ts, id)`
insertion order in the target and break ties with a stable sort)."* Python gets
this free — its target is an insertion-ordered dict under a stable sort. Go's is
a `map[string]any` with no order, and `atoms/fold.go` tie-breaks by key string
instead (logged as FINDINGS §3's "concrete fix-both").

FINDINGS offered "or re-derive it" as an escape. There is none. Arrival order is
recoverable from neither side of what a fold sees: the target map is unordered,
and the payload carries `_ts` but no `id` (the reader injects the first and drops
the second). For items tied on **both** `by` and `ts` — family 3's case — no
content-derived rule can order them.

So closing it takes a protocol decision, not a patch: carry the id into the fold
layer, or make a `TopN` target an ordered map — which JSON's value model says
objects are not, and which `SemanticEqual` currently compares order-insensitively.
Until then `TestSameTSIDTieBreakTopNEviction` asserts the current divergence and
**retires itself**: if Go ever agrees with Python there, the test fails and says
to promote the facet and delete FINDINGS §3.

---

## Adjacent, tracked elsewhere

**The committed store fixtures pin a pre-attestation schema.** Regenerating
`proc.db` / `merge_*.db` from today's engine reproduces the `facts` table
row-for-row but not the file bytes: the committed `.db`s predate the attestation
columns (`facts.signature`; `ticks.prev_hash / window_start / fact_cursor /
window_hash / signature`). Harmless to the Go reader, which selects columns
explicitly — but it means the fixtures were generated against a schema no longer
current, and nothing asserts otherwise (loops-go FINDINGS I3 wants a
`python_commit == loops HEAD` pin-guard; this is the same hole one layer down).
Not fixed here: regenerating is a decision about what the fixtures should pin,
not a side effect of moving the generators.

**Migration ceremony** (123 dangling refs enumerated) is its own arc by the S1-F2
ruling, not a queue member. **Digest design** remains at Kyle's gate.
