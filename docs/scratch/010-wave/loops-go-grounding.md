# loops-go protocol package — grounding slice

Receipts for Track B of the 0.10.0 surfacing wave. The tasking states the loops-go
protocol package owes **GlobalReceiptPosition**, a **`_decl` receipt-group id**, and
**5 vector families**, *plus* three conformance-oracle owed vectors (§8.7
two-authorities late-arrival, cursor-selection at a witness position, same-ts
id-tie-break).

**That last "plus" is a double count.** The three named vectors ARE families 1–3 of
the five. Total owed vectors is **five, not eight**. Detail in §1.2 and §2.

Scope note: this document establishes receipts. §3 lays out layout options and §5
records open questions; neither resolves anything. No store emissions, no code
changes.

Sources swept: project store (`sl read project`), `docs/scratch/080-overnight/`,
`docs/dev/`, `docs/scratch/090-wave/`, `libs/engine`, `apps/loops`, git log
`v0.7.0..HEAD`, and the `loops-go` repo itself at
`/Users/kaygee/Code/loops-go` (branch `r2-replay-conformance`, HEAD `94f7987`).

---

## 0. The one fact that frames everything else

**`loops-go` has not been touched since 2026-07-02.** HEAD is `94f7987`
("spec: era-opening promoted to protocol pattern"), `SPEC.md` mtime Jul 2, the same
HEAD the 0.8.0 dossier read on 2026-07-17. The entire 0.8.0 design wave, the 0.9.0
wave, and every amendment below landed **after** the Go side last moved.

Consequence: nothing in the coordination batch has partially landed. There is no
half-shipped state to reconcile — every claim below is either fully owed or fully
resident on the Python side. This makes the verification unusually clean, and it
means the "package" question is being asked about work that has not started.

---

## 1. Claim-by-claim verification

### 1.1 GlobalReceiptPosition — CONFIRMED owed, in full

| Where specified | What it is |
|---|---|
| `docs/scratch/080-overnight/s1-codex-crossexam.md:46` | the originating FATAL + amendment text |
| `docs/scratch/080-overnight/s1-arbitration.md:158` (A1) | arbiter's disposition — queued, not built |
| `docs/scratch/080-overnight/final-contracts.md:135` | ratified queue item 1 |
| `design:architecture/temporal-cursor-witness-prefix` (RATIFIED 2026-07-17) | the design fact carrying it |

The cross-exam's verdict, verbatim (`s1-codex-crossexam.md:46-53`):

> **Verdict: FATAL.** Amendment **GlobalReceiptPosition**: add one durable,
> monotonic store-wide receipt ordinal (or an append log referenced by both
> tables), define whether a tick occupies an ordinal, and make both Watch and
> §10 consume it. A facts-only `WitnessPosition` may remain the fold boundary,
> but it cannot be advertised as the common receipt cursor without a separate
> store-wide event position.

**Verified absent everywhere it would have to appear:**

- `grep -n "receipt ordinal\|GlobalReceiptPosition\|store-wide" loops-go/SPEC.md` →
  **zero hits.** The spec has never carried the amendment.
- `libs/engine/src/engine/witness.py:28` states it explicitly as a non-implementation:
  *"A store-wide receipt ordinal (GlobalReceiptPosition) is a queued protocol
  amendment, not smuggled in here."*
- No schema column, no table. `facts` and `ticks` remain independent rowid domains.

**It is load-bearing on three shipped things, all of which honestly disclaim the gap
rather than papering it:**

1. `apps/loops/src/loops/surface.py:1330` — `to_review` "makes no JCS
   byte-canonicalization or rebuild-round-trip claim (that layer is gated on
   GlobalReceiptPosition + loops-go, arbiter S4-F4)."
2. `apps/loops/tests/test_review.py:21` — the same gate asserted as test doctrine.
3. `CHANGELOG.md:41` — shipped in the 0.9.0 user-facing notes.

Verdict: **the claim survives contact intact.** This is the largest single item in the
batch and the only one that is a store-schema change.

### 1.2 `_decl` receipt-group id — CONFIRMED owed, but the claim needs splitting

The tasking treats "decl receipt-group" as one owed item. It is two things with
opposite statuses, and conflating them overstates the debt.

**SHIPPED (0.8.0):** the interim *heuristic* boundary and its refusal.
`libs/engine/src/engine/witness.py:205` `receipt_group_span` — a maximal run of
`_decl.*` rows contiguous in rowid sharing one `ts` and one `lineage`;
`:84` `MidReceiptGroupPosition`; the guard runs at the **engine** `at=` selector
(`witness.py:298-315`) and again in `declaration.py:320-326`, not only at the CLI
resolver. Tests: `libs/engine/tests/test_witness_position.py::TestReceiptGroupGuard`.

**OWED:** the *durable* payload-carried group id. `grep -n "group_id\|group id"
libs/engine/src/engine/sqlite_store.py` → **zero hits**; `absorb_edit`
(`sqlite_store.py:700+`) stamps one shared `ts` per ceremony and nothing else. The
ratified text (`final-contracts.md:30-37`):

> **A2 hardened (both panels converged):** receipt-group boundary becomes
> **durable** — group id carried in the `_decl` event payload (a §9.2
> spec touch, queued to the oracle thread TOGETHER with
> GlobalReceiptPosition — the two protocol amendments travel as one
> coordination).

The engine's own docstring names the limit precisely (`witness.py:216-221`):
*"Origin-guaranteed by the write path, not interchange-guaranteed: a kind-filtered
slice can split a group across stores, and the shared-ts test is a heuristic until a
durable group id ships (A2 residue)."*

### 1.3 REFUTED — "no live data exercises ceremonies"

`final-contracts.md:36-37` states, verbatim:

> Conformance vectors owed: no live data exercises ceremonies (1 `_decl` row
> across 47 stores).

**Stale as of 2026-07-18.** A real five-row ceremony exists in the live corpus.
Swept all 41 `.db` files under `~/.config/loops/` and `/Users/kaygee/Code/loops/.loops/`;
two carry `_decl.*` rows — `tasks.db` (1, a lone genesis) and
`~/.config/loops/tasked/data/tasked.db` (6):

```
355 | 01KXVDEXP8QJFDH7TCYT0B3HZV | 1784405259.97671 | _decl.genesis
356 | 01KXVDG5AXEZXFFP0429THQA4Q | 1784405300.57295 | _decl.kind-defined     subject=cancel_requested  change=added
357 | 01KXVDG5B48X76HPGW9QVEG0RN | 1784405300.57295 | _decl.kind-defined     subject=task.close        change=modified
358 | 01KXVDG5B48X76HPGW9QVEG0RP | 1784405300.57295 | _decl.kind-defined     subject=seal              change=modified
359 | 01KXVDG5B48X76HPGW9QVEG0RQ | 1784405300.57295 | _decl.observer-defined subject=kyle              change=modified
360 | 01KXVDG5B48X76HPGW9QVEG0RR | 1784405300.57295 | _decl.observer-defined subject=walker            change=modified
```

Rowids 356–360, one shared `ts` (2026-07-18 15:08:20.572950), one shared lineage —
a textbook multi-subject absorb ceremony, written the day after the measurement that
said none existed.

I ran the shipped heuristic against it (read-only, `engine.witness.receipt_group_span`):

```
355 -> None          (genesis singleton — never mid-group)
356 -> (356, 360)    357 -> (356, 360)    359 -> (356, 360)   (interior — refused)
360 -> None          (ceremony's last row — whole edit included)
361 -> None
```

Two things follow. The heuristic is **empirically correct on real-world data**, not
just on synthetic tests — that is new evidence it did not have at ratification. And
the ceremony-group vector (family 4) no longer needs a fixture invented from the spec:
a real one exists to model from, in a store this repo can read.

### 1.4 REFINED — the batch is five queue members, not three

`final-contracts.md:134-140` names three. Two more accrued afterward and are both
documented; neither appears in the wave thread's framing.

| # | Item | Source | Status |
|---|---|---|---|
| 1 | GlobalReceiptPosition | `final-contracts.md:135` | owed, blocking §10 |
| 2 | `_decl` receipt-group id | `final-contracts.md:137` | owed |
| 3 | Vectors owed (five families) | `final-contracts.md:138-140` | owed |
| 4 | `lifecycle` payload field on `kind-defined` | `docs/dev/lifecycle-spec-delta-090.md` (2026-07-18), per `090-wave/arbitration.md:125-129` (S5-F3) | owed, **explicitly non-blocking** |
| 5 | Tombstone vocab for `lens` / `vertex-defined` singleton | `thread:decl-lens-tombstone-vocab-gap` (open, 2026-07-13) | owed, needs a **new frozen kind** |

Items 4 and 5 differ in kind, and the lifecycle doc itself draws the line
(`lifecycle-spec-delta-090.md:78-82`): lifecycle is *"a payload field on an existing
document"* and needs no coordinated vocabulary change, whereas the tombstone gap
*"needs a **new frozen kind** and so a real coordinated vocabulary change."* Item 5
is therefore the second-hardest thing in the batch after GRP, and it is currently
carried only by an open thread, not by the batch's own record.

### 1.5 Quote-check on the tasking's phrasing

- "cursor-selection at witness position" — **fair paraphrase.** Sources say
  "cursor-selection (fold-at-position incl. backdated straddle)"
  (`final-contracts.md:139`) and "cursor-selection vectors (fold-as-of at a witness
  position incl. a backdated arrival straddling the cursor)"
  (`thread:loops-go-conformance-oracle`, 2026-07-17). Nothing lost.
- "5 vector families" — **the phrase is real and traceable**, but it appears in prose
  exactly twice, and neither instance enumerates: `docs/dev/lifecycle-spec-delta-090.md:76`
  ("the 5 vector families") and `docs/scratch/080-overnight/morning-dashboard.html:86`
  ("five owed vector families"). Only the dashboard lists them. See §2.
- The wave thread (`thread:010-surfacing-wave`) **does not mention loops-go at all**
  in either of its two facts — both concern the primitives rider. The loops-go
  assertion the tasking attributes to "the wave thread" traces to
  `observation:architecture/instrument-family-survey-read` ("0.8.0 strays — loops-go
  protocol pkg, TUI shell, vouch — are one cluster") and to session memory, not to
  the thread text. Not a substantive error; worth knowing which fact to cite.

---

## 2. The 5 vector families

**All five are groundable, and the count is exact.** Source of truth is
`final-contracts.md:138-140` (the ratified list), enumerated in prose at
`docs/scratch/080-overnight/morning-dashboard.html:86`:

> five owed vector families (two-authorities late-arrival, cursor-selection,
> same-ts tie-break, ceremony groups, dump round-trip)

| # | Family | Upstream spec | Blocked on |
|---|---|---|---|
| 1 | §8.7 two-authorities late-arrival — event order and witness order disagree; fold state follows §6.2, window membership follows §8.4 | `loops-go/SPEC.md:912-923` ("Conformance surface **(to build)**") | the whole §8 chain layer, absent in Go |
| 2 | Cursor-selection — fold state at a witness position, including a backdated arrival straddling the cursor | no upstream §; created by `design:architecture/temporal-cursor-witness-prefix` | cursor form (see §5 Q1); Go reader has no witness axis |
| 3 | Same-ts id tie-break | `SPEC.md:393-406` (§4.6) and §6.2's closing note | nothing — generatable today |
| 4 | Mid-/split-group ceremony | §9.2, via A2 | durable group id, or a decision to pin the heuristic (§5 Q2) |
| 5 | §10 dump / rebuild witness-order round-trip | `SPEC.md:1235-1245` ("Conformance surface **(to build)** & sequencing") | GlobalReceiptPosition **and** a §10 implementation that does not exist |

Only family 3 is unblocked. Its upstream even pre-authorizes it — SPEC §4.6
(`SPEC.md:404-406`): *"The conformance corpus contains no ties yet, so the
differential oracle does not catch it; a tie vector should be added once §6.2 is
frozen."* §6.2 was frozen at `d865954`. The condition is met.

### A name collision worth flagging

`docs/scratch/080-overnight/dossier-go-vectors.md:85` refers to "the five **oracle**
families" — the *existing, shipped* suite, not the owed one. Two different fives, one
sentence apart in the same wave's docs.

And that one is a miscount. The SPEC appendix (`SPEC.md:1249-1260`) names **six**
oracles in three groups — `TestFoldVectors`, `TestParseVectors` (differential);
`TestOrderSensitivityProperty`, `TestApplyPurity`, `TestDeterminism` (property);
`TestM1StoreReplayParity` (M1) — and `TestMergeCommutativity` was added later without
being listed, for **seven** actual top-level tests (the dossier's own §1 reports "all
7 top-level tests PASS"). Neither 6, 3, nor 7 is five. Low stakes on its own, but
"five oracle families" and "five vector families" are one careless read apart, and one
means *already certified* while the other means *not started*.

### Refuted: the sequencing constraint people expect to be blocking, is not

§10.5 carries a hard gate (`SPEC.md:1241-1245`):

> **Sequencing constraint (hard):** the incumbent's `_canonical_bytes` → JCS
> migration and chain re-anchor (§8.1) MUST land before any §10 vectors are
> generated, or the vectors pin pre-JCS bytes.

**That gate is satisfied.** `libs/engine/src/engine/sqlite_store.py:115-122` —
`_canonical_bytes` is JCS/RFC 8785, citing
`decision:design/attestation-canonicalization-jcs`, with *"Pre-JCS chains were
re-anchored"* stated in the docstring. So families 1 and 5 are **not** blocked on
canonicalization. Family 5 is blocked on §10 existing at all: `sl store` offers
`verify | rebirth | reanchor | absorb | adopt | ticks | stats | reindex` — no dump,
no rebuild.

---

## 3. Package layout options

The charter constraint first, because it eliminates the option most people reach for.

`ARCHITECTURE.md:137-144` (surfacing-layer charter, ratified by Kyle 2026-07-27 per
`design:architecture/surfacing-layer-charter`):

> A layer is a **designation, not a package** … Membership lives in this table and
> in the import DAG (`tests/test_architecture.py`, Rule 11); a new library must
> declare its layer or the suite fails. Apps take no layer assignment … **App-side
> surfacing occupants (the TUI shell, cross-implementation protocol artifacts)
> belong to the layer by role without being libs.**

"Cross-implementation protocol artifacts" is this track, named. The charter has
already ruled that these belong to surfacing **without being a lib**. Any option that
creates `libs/protocol` contradicts the charter it would be implementing — and would
trip `test_every_lib_declares_a_layer` (`tests/test_architecture.py:866`) into
demanding a `_LIB_LAYER` entry for something the charter says need not be one.

### Option A — status quo: per-delta docs under `docs/dev/`

One doc per spec-delta, as `docs/dev/lifecycle-spec-delta-090.md` already is; vectors
and generators stay in loops-go.

**Dissolution test: dissolves completely — it already exists.** No new structure. Cost
is real though: the batch's five members are currently scattered across
`final-contracts.md` (items 1–3), a `.html` dashboard (the only enumeration of the
five families), an open thread (item 5), and one `docs/dev/` note (item 4). There is
no single place that answers "what does loops-go owe." That scatter is what makes the
tasking's double count possible.

### Option B — an in-repo `protocol/` directory (not a lib)

A non-lib directory holding spec-delta notes, vector *generators*, and generated
vector JSON, shipped or not shipped with the distribution.

**Dissolution test: splits.** The docs half dissolves into Option A and gains nothing.
The *generator* half does not dissolve, and there is a real defect it would fix:

`loops-go/tools/gen_store_fixture.py:27-29` reaches across repos by absolute path —

```python
LOOPS = Path.home() / "Code" / "loops"
for lib in ("atoms", "engine"):
    sys.path.insert(0, str(LOOPS / "libs" / lib / "src"))
```

The generators import the reference implementation via `sys.path` injection against a
hardcoded `$HOME/Code/loops`, bypassing the uv workspace, any released artifact, and
any version pin. They are loops code living in the loops-go tree. The drift this
invites is already visible: `gen_store_fixture.py`'s docstring says *"The Go side
opens the SAME .db with the SAME query (**ORDER BY rowid**)"* while
`loops-go/store/sqlite.go:41` actually queries `ORDER BY ts, id` — the docstring
describes the pre-§6.2-freeze behavior and was never updated.

### Option C — vectors stay in loops-go; loops keeps one coordination index

A single `docs/dev/loops-go-protocol-queue.md` enumerating the batch (the five members
of §1.4), each linking its own delta doc; vectors and oracles stay in loops-go, which
is where the consumer is.

**Dissolution test: dissolves.** The index replaces a scatter with a list; it adds no
machinery, no package, no layer question, and no import edge. It is a document doing a
document's job — which is what "the protocol package" turns out to be for four of its
five members.

### Recommendation

**Option C, plus the generator relocation from Option B** — an index doc under
`docs/dev/` dissolves the coordination artifacts into structure that already exists,
while moving `gen_*.py` into the loops workspace dissolves a `sys.path` hack into an
ordinary import of the reference implementation those generators are definitionally a
part of. Nothing here is a package: the charter already ruled protocol artifacts are
surfacing *by role*, and the residue that isn't a document is test tooling that
belongs next to the semantics it reads.

---

## 4. Conformance oracle needs

Grounded in `thread:loops-go-conformance-oracle` (open, N=9) and the artifact-by-
artifact table in `dossier-go-vectors.md:284-291`.

### What the thread actually says

The thread's 2026-07-17 fold, in its own words: the Go corpus certifies

> SPEC 4/5 (folds/parse), 6.1 (application), 6.2 (replay order +
> merge-commutativity) and NOTHING at the 8-attestation, 9.3-two-cursor, or 10-dump
> tiers

and its consequence:

> green conformance was silent on the cursor-axis choice — S5's ts cutoff neither
> passed nor failed an oracle

That is the oracle's whole shape problem: it is green and it is silent. A second
implementation today can pass every vector while disagreeing with loops about every
question the owed families ask.

### The format gap

Existing vectors cannot express any owed family. The fold/parse vector schema
(`dossier-go-vectors.md` Appendix A) is `{name, folds, initial, payloads, expected,
order_sensitive}` — **no ids, no store, no time axis**; the harness applies payloads
in array order (`vectors_test.go:78-80`). Ordering is an *input* to these vectors,
never something they test. Mechanical scan of both files: `as_of` 0, `cursor` 0,
`witness` 0, `tick` 0.

Store fixtures are the only artifact class that *could* carry a witness axis, since a
`.db` carries rowids. But the Go reader discards it — `loops-go/store/sqlite.go:41`:

```go
rows, err := db.Query("SELECT kind, ts, observer, origin, payload, id FROM facts ORDER BY ts, id")
```

No rowid selected, no cursor parameter anywhere in the package (79 lines, read-only).
So **every witness-axis family (1, 2, 4, 5) requires a Go-side reader change before
any vector can even be consumed.** That is a prerequisite the batch does not currently
name.

### What a second implementation must therefore consume

1. **A third artifact class** — store fixture + a cursor + expected fold state *at*
   that cursor. Today's two classes (id-less vector JSON; full-store-replay fixture)
   cannot express it. `dossier-go-vectors.md:293-296` states the gap directly: *"Fold
   state at a cursor is pinned by **nothing**. There is no replay-prefix vector, no
   windowed replay, no anchor-and-stop case anywhere."*
2. **A witness-exposing reader** — `rowid` in the projection, plus a prefix-select-
   then-replay path: select `WHERE rowid <= P`, replay the selected set in `(ts, id)`
   order. Note this is *selection on one axis, ordering on the other* — the
   distinction the ratified design rests on (`witness.py:1-15`), and the one a
   naive implementation collapses.
3. **A receipt-group detector** for family 4, matching whatever boundary rule ships
   (heuristic or durable id — §5 Q2).
4. **The entire §8 chain layer** for families 1 and 5 — commitments, signatures,
   window hashes, chain walks. Go has none of it.

### The trap the corpus already documents

The merge pair is the only existing artifact where witness order and event order
disagree, and it is decisive against the naive reading. Executed counterfactual
(`dossier-go-vectors.md:316-340`): replaying the merge fixtures in **rowid (witness)
order** diverges from the pinned expectation in *both* directions, and the two rowid
replays disagree with **each other** (`tags: ['a2','b0','b1']` vs `['b1','a0','a2']`).

Witness position is store-local state that does not survive merge. A cursor vector
must therefore pin its cursor in a form that survives fixture regeneration — which is
Q1 below, and it is the first thing to settle before a single vector is generated.

---

## 5. Open questions for the design gate

**Q1 — How does a cursor-selection vector express its cursor?**
`witness.py:544-561` `durable_handle` returns the portable form
`fact:<lineage>/<id>` for adopted stores and **refuses (`None`) for unadopted ones**,
inventing no surrogate: *"A caller rendering cursor metadata MUST NOT present a bare
`fact:<id>` as a reusable handle here — it is not portable (the id resolves in ANY
store that merged the fact, to a different prefix)."* All three loops-go fixture
stores have **zero `_decl` rows** — every one is unadopted, so none can carry a
durable handle today. Two ways out, with different costs: express the cursor as
`seq:N` (works immediately, but is fixture-local and re-derived on regeneration), or
adopt the fixture stores by minting a genesis — which pulls §9 into Go, and §9 is
PROVISIONAL with zero Go implementation (`lifecycle-spec-delta-090.md:66-68`).

**Q2 — Does the ceremony vector pin the heuristic, or wait for the durable id?**
The heuristic is now verified against real live data (§1.3) — which makes pinning it
tempting. But `witness.py:216-221` says it is *"origin-guaranteed by the write path,
not interchange-guaranteed: a kind-filtered slice can split a group across stores."*
A vector pinning contiguity+shared-ts would certify a boundary rule the protocol
amendment intends to replace, and would then have to be retired rather than extended.
The counter-argument: the durable id is queued behind GRP, and family 4 is otherwise
generatable today.

**Q3 — Is GlobalReceiptPosition a column, a table, or a derived ordinal?**
The amendment is disjunctive and the disjunction was never resolved
(`s1-codex-crossexam.md:46-49`): *"add one durable, monotonic store-wide receipt
ordinal **(or an append log referenced by both tables)**, define whether a tick
occupies an ordinal."* Both branches are store-schema changes across the live corpus,
and no migration path is stated anywhere in the batch. The two sub-questions ("column
or log" and "does a tick consume an ordinal") have different blast radii and are
currently bundled.

**Q4 — Which repo owns vector generation?**
The generators are loops Python (`libs/atoms` + `libs/engine`) living in the loops-go
tree, imported by `sys.path` injection against a hardcoded `$HOME/Code/loops`
(`gen_store_fixture.py:27-29`), with observable docstring drift already
(`ORDER BY rowid` vs the actual `ORDER BY ts, id`). Every owed family needs new
generator code, so this is decided now whether or not it is decided deliberately.

**Q5 — Does the batch ship as one coordination, or split?**
`final-contracts.md:33` binds two of the members: GRP and the group id *"travel as
one coordination."* Since ratification the queue grew to five (§1.4), and the two
newcomers have opposite urgency —`lifecycle` is additive, forward-compatible, and
documented as *"a queued line item on that batch, not a new coordination arc, and
does not block the oracle"* (`lifecycle-spec-delta-090.md:75-78`), while the tombstone
vocab needs a **new frozen kind**, the hardest class of change in §9.2. Shipping all
five as one coupling means the non-blocking additive field waits on a store-schema
migration.

**Not open, recorded so it does not get re-litigated:** whether the §10.5 JCS
sequencing gate blocks vector generation. It does not — the migration landed
(`sqlite_store.py:115-122`, §2 above). Family 5 is blocked on §10 not existing, which
is a different and larger problem.
