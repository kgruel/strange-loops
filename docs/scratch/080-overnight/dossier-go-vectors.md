# Dossier: loops-go conformance oracle — what the vectors actually pin (cursor-axis evidence)

*0.8.0 design-wave grounding chapter. Generated 2026-07-17 from `/Users/kaygee/Code/loops-go`
(branch `r2-replay-conformance`, HEAD `94f7987`; `main` at `017a5c1` is an ancestor — the
branch IS the current state) and `/Users/kaygee/Code/loops` (Python incumbent, main @ 82c958c).
All quotes verbatim; all counterfactuals executed against the real fixtures and real Python atoms.*

---

## 0. Executive answers (each substantiated below)

**Correction to the tasking prompt first.** The prompt describes testdata/ as "conformance
vectors for SPEC 9.3 and 10." **No such vectors exist.** The SPEC itself says so: §8.7 is
titled "Conformance surface **(to build)**" (SPEC.md:912) and §10.5 likewise "Conformance
surface **(to build)** & sequencing" (SPEC.md:1235), listing those vectors as "owed."
§9–§10 are marked PROVISIONAL and design-led (SPEC.md:6–7, 927, 1189). What testdata/
actually contains certifies SPEC **§4/§5 (fold/parse semantics), §6.1 (replay application),
and §6.2 (replay order + merge-commutativity)** — nothing at the §8 attestation tier, the
§9.3 two-cursor tier, or the §10 dump tier.

1. **Which cursor axis do the vectors assume for as-of/replay?**
   The vectors assume **no as-of cursor of any kind** — zero occurrences of any cursor
   vocabulary in either vector file (§4 below). What they DO pin is the **replay ORDER**,
   and there they are decisive: replay is **event order `(ts, id)`** — a ts-primary axis —
   NOT witness order and NOT tick-anchored. `TestMergeCommutativity` fails empirically
   under witness-order replay (demonstrated, §7). The as-of *cursor* axis is entirely
   unconstrained by the existing corpus.

2. **Any same-ts facts where ts-ordering is ambiguous but witness-order is pinned?**
   **No. Zero same-ts facts anywhere** — across all three fixture stores and all 30 fold
   vectors (verified by query, §5). The `(ts, id)` id tie-break is *specified* (SPEC §6.2)
   but *never exercised by data*. The SPEC admits this in §4.6: "The conformance corpus
   contains no ties yet, so the differential oracle does not catch it" (SPEC.md:405–406).

3. **What exactly does each vector pin?** Per-artifact table in §6. Summary: fold vectors
   pin fold semantics over an already-ordered payload array (order given by array position,
   no ids, no store); parse vectors pin parse semantics (no time at all); `proc.db` pins
   store-read interop + fold parity over a store whose witness order and event order
   *coincide* (so it cannot discriminate axes); the merge pair pins **replay ordering** —
   the only axis-discriminating artifact — plus final fold state. No artifact pins fold
   state *at a cursor*; every replay is a full-store replay to head.

4. **Would a ts-resolved, equal-cursors-default as-of break any vector?**
   **No vector would fail and none would be indeterminate**, because no vector places an
   as-of cursor. Moreover this hypothetical is not hypothetical: **the Python incumbent
   already ships exactly this** — `--as-of` resolves to an epoch-seconds anchor with the
   equal-cursors default (apps/loops fetch.py, §8 below) on the stream/ticks routes, and
   the fold route *refuses* temporal flags (read-router, 184dfce) because fold-state-as-of
   doesn't exist yet. The corpus is compatible with a ts cursor, a witness cursor, or a
   tick anchor — it only forbids changing the replay *order* away from `(ts, id)`.

---

## 1. Repo inventory — what exists where

```
/Users/kaygee/Code/loops-go
  SPEC.md                                  67,809 bytes; §0–§10; §9–§10 PROVISIONAL
  FINDINGS.md                              drift/bug/decision record
  atoms/    {decode,fact,fold,parse,spec,types,value}.go   — Go port of libs/atoms
  store/    sqlite.go                      — the Go store READER (79 lines, read-only)
  internal/conform/                        — the conformance harness ("r2-replay-conformance"
                                             is the BRANCH name carrying this + §8–§10 spec work;
                                             cited as such in loops docs/dev/internal-table-build-
                                             plan-2026-07-11.md:3: "SPEC §9 (loops-go
                                             `r2-replay-conformance`, ef013f1..94f7987)")
    equal.go          SemanticEqual/Diff — value-model equality (numbers by value)
    vectors_test.go   TestFoldVectors, TestParseVectors      (differential oracle)
    property_test.go  TestOrderSensitivityProperty, TestApplyPurity, TestDeterminism
    store_test.go     TestM1StoreReplayParity                (M1: store-read + fold parity)
    merge_test.go     TestMergeCommutativity                 (SPEC §6.2)
  testdata/
    vectors/fold_vectors.json    30 vectors  @ python 581df73 (real loops commit, verified)
    vectors/parse_vectors.json   28 scenarios @ python 581df73
    stores/proc.{db,expected.json}          @ python 33937f6 (older pin than the vectors)
    stores/merge_{ab,ba}.db + merge.expected.json @ python 581df73
  tools/    gen_vectors.py, gen_store_fixture.py, gen_merge_fixture.py  (run against ~/Code/loops)
```

Suite status, run 2026-07-17: **all 7 top-level tests PASS, 150 subtests PASS**
(`go test ./internal/conform/`): TestFoldVectors, TestParseVectors, TestMergeCommutativity,
TestOrderSensitivityProperty, TestApplyPurity, TestDeterminism, TestM1StoreReplayParity.

The SPEC appendix (SPEC.md:1249–1260) confirms this is the *whole* conformance surface:
vectors + proc fixture + the five oracle families. (It predates the merge fixture's addition
to the list; the §6.2 body cites `TestMergeCommutativity` explicitly at SPEC.md:603–609.)

---

## 2. The prompt-contradiction, with the SPEC's own words

§8.7 (SPEC.md:912–923):

> ### 8.7 Conformance surface (to build)
>
> Vectors owed at this layer: JCS envelope bytes for each construction in §8.2 …;
> era-transition rows …; window hashes over mixed-era windows; chain walks with each break
> class …; **two-authorities differential (a late-arrival fixture where event order and
> witness order disagree — fold state must follow §6.2, window membership must follow §8.4).**

§10.5 (SPEC.md:1235–1245):

> ### 10.5 Conformance surface (to build) & sequencing
>
> Vectors owed: dump bytes for a mixed-era fixture store (pre-chain, chained, signed rows);
> rebuild-then-verify walks per §10.3(1); byte-identity per §10.3(2); **a witness-order
> fixture where event order disagrees (the §8.7 two-authorities fixture, round-tripped).**
>
> **Sequencing constraint (hard):** the incumbent's `_canonical_bytes` → JCS migration and
> chain re-anchor (§8.1) MUST land before any §10 vectors are generated, or the vectors pin
> pre-JCS bytes …

So the fixture that would decide witness-vs-event questions *at the attestation/dump tier*
— "a late-arrival fixture where event order and witness order disagree" — is **named, owed,
and absent**. There are also **zero declaration-event rows** anywhere in the fixtures
(`SELECT COUNT(*) FROM facts WHERE kind LIKE '_decl%'` → 0 in proc.db; no `_decl` string in
either vector file), so nothing exercises §9.2/§9.3 ontology history either.

---

## 3. What the SPEC (normatively) says about ordering and cursors — the frame the vectors serve

Three passages carry the whole design space. Quoted because the 0.8.0 conflict is exactly
about which of these axes the temporal cursor rides.

**§6.2 Replay order (SPEC.md:566–596)** — the axis the vectors DO certify:

> Replay processes facts in **`(ts, id)` order** — observation time `ts` ascending, with the
> stored ULID `id` as a unique, stable tie-break for equal `ts`.
> …
> The order is **observation-time primary**: `ts` ascending, `id` as the exact-`ts` tie-break.
> This matches the aspiration's "events have a total order by ts" — a backdated, imported, or
> derived fact folds in event-time order. (The alternative, `id`-only / write-time order, was
> considered and rejected: it is barely simpler and folds backdated facts by when they were
> written, not when they happened.)

**§8.4 Two ordering authorities (SPEC.md:850–863)** — normative split, witness axis exists
but for a different job:

> **Ordering authority is split, and the split is normative** (incumbent fix `3b2ceb5`: id
> order ≠ append order in mixed-id-era stores):
>
> - **Event order `(ts, id)`** governs fold replay (§6.2). It answers *what happened, in what
>   observed sequence*.
> - **Witness order** (append/insertion order as recorded by the store — the incumbent uses
>   SQLite rowid) governs window membership and chain walking. It answers *what this store
>   received, in what order it received it*.
>
> The chain attests **receipt, not chronology**. A late-arriving fact with an old event-time
> must not retroactively enter a sealed window — that is honest witnessing, not tamper.
> Neither order substitutes for the other; an implementation that conflates them produces
> either false tamper alarms or non-deterministic folds.

**§9.3 Two time axes (SPEC.md:1110–1119)** — the as-of contract, cursor axis NOT specified:

> Once the ontology is historized, a historical read has two independent cursors:
> **facts-as-of** (which facts replay) and **ontology-as-of** (which declaration state
> interprets them). The default MUST be equal cursors — an honest snapshot of what a reader
> at T would have seen. Unequal cursors (today's ontology over old facts, or the reverse) are
> legitimate *deliberate reinterpretation* and MUST be explicitly requested, never a silent
> default. Non-critical state (lenses) MAY follow the reading session's present without
> violating honesty.

Note what §9.3 does NOT say: it never states whether the cursor value is a `ts`, a witness
position, or a tick id. The word "cursors" is unqualified. Adjacent tiers each pull their
own way:

- **Witness axis in the chain layer:** the tick envelope carries `fact_cursor`, and
  "**Window hash:** for the window `(window_start, fact_cursor]` in witness order (§8.4)…"
  (SPEC.md:816–817). Key rotation likewise: verification "MUST resolve the observer's key
  *as of the signed row's witness position*, not the registry head" (SPEC.md:1057–1059).
- **Event axis in the replay/ref layer:** entity refs resolve "as-of the referencing fact's
  observation time … `ts ≤ T`, under the §6.2 `(ts, id)` total order" (SPEC.md:619–624).
- **§0.5.4** pins the exception explicitly: "Set-determinacy deliberately does NOT hold
  [at the attestation tier] — the chain is a function of *witness order* (§8.4), receipt not
  chronology" (SPEC.md:80–83).

So the SPEC's own structure is: **replay/fold/ref questions ride `(ts, id)`; receipt/window/
custody questions ride witness order; §9.3's as-of cursor is textually unbound to either.**

---

## 4. Q1 evidence — no cursor vocabulary exists in any vector

Mechanical scan of both vector files (json string search):

```
parse_vectors.json:  as_of → 0   cursor → 0   witness → 0   tick → 0   _ts → 0
fold_vectors.json:   as_of → 0   cursor → 0   witness → 0   tick → 0   rowid → 0
```

(`fold_vectors.json` contains 11 occurrences of `"id"` — all are *payload* fields used as
Upsert/TopN keys, e.g. `{"id": "a", "name": "Alice"}` in `upsert_insert_and_update`,
fold_vectors.json:204–244. Fold vectors carry **no fact ids and no store**: the harness
applies payloads in array order — `for _, p := range v.Payloads { state = spec.Apply(state, p) }`,
vectors_test.go:78–80. Ordering is an *input* to these vectors, never something they test.)

The fixture stores have `ticks` tables (schema present) but they are **empty**:
`SELECT COUNT(*) FROM ticks` → 0 in proc.db. No artifact anywhere anchors anything to a tick.

The Go code consuming the fixtures has no cursor parameter at all. The entire read path is
(store/sqlite.go:34–41):

```go
// ReadFacts returns all facts in (ts, id) replay order — observation time
// ascending, ULID id as the stable tie-break (SPEC §6.2). This is the
// store-independent total order that makes replay merge-commutative: a fact
// keeps its (ts, id) verbatim through every slice/merge, whereas rowid is
// regenerated in merge-insertion order. Mirrors the incumbent's
// sqlite_store.since_raw / facts_for_replay (ORDER BY ts, id @ loops 14eb723).
...
rows, err := db.Query("SELECT kind, ts, observer, origin, payload, id FROM facts ORDER BY ts, id")
```

and `Spec.Replay(payloads)` (atoms/spec.go:50) takes the whole ordered list — no windowing,
no as-of, no anchor. **Grep of atoms/, store/, internal/ for `as_of|asOf|cursor|witness`: no
runtime hits.**

Conclusion for Q1: the vectors assume a **`(ts, id)` event-order axis for replay ordering**
and assume **nothing at all** about the as-of cursor axis. "Witness-order cursor" and
"tick-anchor cursor" appear in the corpus only as *absences*; "ts cursor" appears only as
the primary sort key of replay, never as a rewind point.

---

## 5. Q2 evidence — zero same-ts facts; the id tie-break is specified but data-untested

Raw fixture rows, complete (sqlite3, `ORDER BY rowid`):

```
--- proc.db (rowid | id | ts | kind | payload) ---
1|FIXTURE0000000000000000000|1000.0|proc|{"pid": "a", "cpu": 10.0, "mem": 1.2, "_ts": 1000.0, "ref": "host/x"}
2|FIXTURE0000000000000000001|1001.0|proc|{"pid": "b", "cpu": 30.0, "mem": 2.0, "_ts": 1001.0}
3|FIXTURE0000000000000000002|1002.0|proc|{"pid": "c", "cpu": 20.0, "mem": 0.5, "_ts": 1002.0, "ref": "host/y,host/z"}
4|FIXTURE0000000000000000003|1003.0|proc|{"pid": "a", "cpu": 50.0, "mem": 1.5, "_ts": 1003.0}
5|FIXTURE0000000000000000004|1004.0|proc|{"pid": "d", "cpu": 5.0, "mem": 3.0, "_ts": 1004.0}

--- merge_ab.db (A←B) ---
1|FIXA0000000000000000000000|1000.0|event|{"id": "x", "tag": "a0", "note": "first"}
2|FIXA0000000000000000000001|1002.0|event|{"id": "x", "tag": "a2"}
3|FIXB0000000000000000000000|1001.0|event|{"id": "x", "tag": "b0"}
4|FIXB0000000000000000000001|1003.0|event|{"id": "y", "tag": "b1"}

--- merge_ba.db (B←A) ---
1|FIXB0000000000000000000000|1001.0|event|{"id": "x", "tag": "b0"}
2|FIXB0000000000000000000001|1003.0|event|{"id": "y", "tag": "b1"}
3|FIXA0000000000000000000000|1000.0|event|{"id": "x", "tag": "a0", "note": "first"}
4|FIXA0000000000000000000001|1002.0|event|{"id": "x", "tag": "a2"}
```

Duplicate-ts check: `SELECT ts FROM facts GROUP BY ts HAVING COUNT(*)>1` → **0 groups in
all three stores**. Fold vectors: only two vectors carry `_ts` in payloads at all
(`latest_with_ts`: one payload; `multiple_typed_folds`: one payload) — no duplicates possible.

The SPEC knows. §4.6 TopN tie-break (SPEC.md:393–406):

> Under the §6.2 total order, facts arrive in `(ts, id)` order, so the tie-break **is**
> `(ts, id)` … *(The incumbent achieves this incidentally via insertion-ordered maps; one
> reference implementation currently tie-breaks by key string and must be brought to
> `(ts, id)` order to conform — a concrete fix-both task, tracked in FINDINGS. **The
> conformance corpus contains no ties yet, so the differential oracle does not catch it;
> a tie vector should be added once §6.2 is frozen.**)*

And §6.2's closing note (SPEC.md:609–611): "*A pure-atoms tie vector for the `TopN`
tie-break still awaits the M4/M5 boundary machinery — adding it to the id-less fold vectors
would have no replay-order step to exercise.*"

Conclusion for Q2: **No vector contains same-ts facts.** There is no case where ts-ordering
is ambiguous, and consequently no case where witness order is pinned as the disambiguator.
The equal-ts regime — the exact regime where a ts-only cursor is indeterminate and where the
three cursor-axis candidates actually diverge — is **unrepresented in the corpus**. The one
place ties are even discussed defers the vector to post-freeze.

A second, subtler gap: in `proc.db`, ts is strictly monotone with rowid (1000→1004 in
insertion order — gen_store_fixture.py:64–70), so **witness order and event order coincide**
and `TestM1StoreReplayParity` cannot discriminate the axes. gen_store_fixture.py:118–121
even asserts the coincidence: `read_back == PAYLOADS` after a rowid-ordered read-back. The
merge pair is the **only** artifact where the two orders disagree.

---

## 6. Q3 — what each artifact pins, exactly

| Artifact | Test | Pins | Cursor content |
|---|---|---|---|
| `fold_vectors.json` (30 vectors) | `TestFoldVectors` (vectors_test.go:62–86) | Final fold state after applying payloads **in array order** to `initial`; plus Python's `order_sensitive` verdict per vector (permutation check ≤6 payloads, gen_vectors.py:108) | None. No ids, no store, no time axis (2 payloads carry `_ts` as data for `Latest`) |
| `parse_vectors.json` (28 scenarios) | `TestParseVectors` | Parse-pipeline output per input case | None. No temporal content at all |
| same fold vectors | `TestOrderSensitivityProperty` (property_test.go:58–83) | That Go's order-sensitivity classification **agrees with Python's** per fold (`Collect`/`Window`/`Upsert`-overwrite sensitive; `Count/Sum/Min/Max/Avg`, refs, `Latest` not) | None — a property about permutations, not about any particular order |
| same | `TestApplyPurity`, `TestDeterminism` | §0.5.1 immutability, §0.5.2 fixed-order determinism | None |
| `proc.db` + `proc.expected.json` | `TestM1StoreReplayParity` (store_test.go:29–57) | Go reads a Python-written .db unchanged and reproduces Python's `Spec.replay` state over ALL 5 facts (10 folds incl. all order-sensitive ones). "**`id` is not part of the replayed Fact, so the result is ULID-independent**" (store_test.go:14–15) | None. Full-store replay to head; witness ≡ event order in this store |
| `merge_ab.db`/`merge_ba.db` + `merge.expected.json` | `TestMergeCommutativity` (merge_test.go:31–61) | **Replay ORDER.** Two real Python-merged stores (opposite directions, different rowid layouts, interleaved ts) must re-fold to ONE identical pinned state. "replaying in (ts, id) order MUST reproduce the same derived state from both directions" (merge_test.go:13–15) | This is the decisive artifact — see §7. Still no as-of: replay is full-store |

Answering Q3's dichotomy directly: the vectors pin **fold state at head** (never at a
cursor) and — via the merge pair only — **ordering of replay**. "Fold state at a cursor"
is pinned by **nothing**. There is no replay-prefix vector, no windowed replay, no
anchor-and-stop case anywhere.

`merge.expected.json` pinned state (merge.expected.json:41–85), the thing both merge
directions must reproduce:

```json
"log":  [ {"id":"x","tag":"a0","note":"first","_ts":1000.0},
          {"id":"x","tag":"b0","_ts":1001.0},
          {"id":"x","tag":"a2","_ts":1002.0},
          {"id":"y","tag":"b1","_ts":1003.0} ],
"tags": [ "b0", "a2", "b1" ],
"entities": { "x": {"id":"x","tag":"a2","note":"first","_ts":1002.0,"_n":3},
              "y": {"id":"y","tag":"b1","_ts":1003.0,"_n":1} }
```

Note `log`'s sequence is ts-interleaved A/B/A/B — an order that matches **neither** store's
rowid layout (§5 dumps). Only `(ts, id)` produces it from both DBs.

---

## 7. The decisive counterfactual, executed — witness-order replay fails; the pinned order is event order

Ran the fixture DBs through the **real Python atoms** (`Spec.replay`, loops main @ 82c958c)
under both orderings:

```
--- replay order: ts, id ---
merge_ab.db: MATCHES expected   tags: ['b0','a2','b1'] | log tag seq: ['a0','b0','a2','b1'] | x: a2 first
merge_ba.db: MATCHES expected   tags: ['b0','a2','b1'] | log tag seq: ['a0','b0','a2','b1'] | x: a2 first

--- replay order: rowid (witness) ---
merge_ab.db: DIVERGES from expected  tags: ['a2','b0','b1'] | log tag seq: ['a0','a2','b0','b1'] | x: b0 first
merge_ba.db: DIVERGES from expected  tags: ['b1','a0','a2'] | log tag seq: ['b0','b1','a0','a2'] | x: a2 first
```

Three facts fall out:

1. **A witness-order replay axis fails the suite today** — both merge DBs diverge from the
   pinned expectation (`TestMergeCommutativity` would fail on both subtests).
2. **Witness order is not even self-consistent across merge directions** — the two rowid
   replays disagree with *each other* (`tags: ['a2','b0','b1']` vs `['b1','a0','a2']`;
   `entities.x.tag: 'b0'` vs `'a2'`). A witness-position cursor is store-local state that
   does not survive merge; the fixtures demonstrate this concretely, not just argue it.
3. **The pinned expectation is the ts-interleaved sequence** `a0(1000), b0(1001), a2(1002),
   b1(1003)` — pure event time.

This is the fixture's designed purpose — gen_merge_fixture.py:42–49:

```python
# Two independently-emitted fact sets whose ts values INTERLEAVE, so neither
# physical merge order matches (ts, id) order. Order-sensitive folds will only
# agree across merge directions if replay honors (ts, id).
#  ts:   0      1      2      3
#  A:   a0            a2
#  B:          b0            b1
A_FACTS = [(1000.0, {"id": "x", "tag": "a0", "note": "first"}),
           (1002.0, {"id": "x", "tag": "a2"})]
B_FACTS = [(1001.0, {"id": "x", "tag": "b0"}),
           (1003.0, {"id": "y", "tag": "b1"})]
```

---

## 8. Q4 — the "ts + equal-cursors" hypothetical is the incumbent's shipped behavior, and no vector constrains it

**The premise is not hypothetical.** The Python incumbent resolves `--as-of` to an epoch-
seconds anchor today (apps/loops/src/loops/commands/fetch.py:41–66):

> ```python
> def _parse_as_of(s: str, now: datetime) -> float:
>     """Resolve an ``--as-of`` value to an anchor epoch ``ts`` (SPEC §9.3).
>
>     The anchor is the read's upper bound: facts replay up to it and — the
>     equal-cursors default — the ontology resolves at it. Accepts either a
>     duration ("ago" from ``now`` …) or an absolute position (epoch seconds,
>     or an ISO-8601 timestamp). …
> ```

and applies it equal-cursors (fetch.py:385–390):

> ```python
> # Equal-cursors (SPEC §9.3): one anchor is BOTH the fact-window upper bound
> # and the ontology-as-of cutoff. cursor=None (head) when --as-of is absent
> # keeps the equivalence property exact.
> anchor = _parse_as_of(as_of, now) if as_of else now.timestamp()
> cursor = anchor if as_of else None
> ```

The fact filter is a ts window — `WHERE ts >= ? AND ts <= ? … ORDER BY ts, id`
(vertex_reader.py:461, 466 and the single-store path) — and the ontology cutoff is
inclusive ts (engine/declaration.py:322–326):

> ```python
> # Inclusive cutoff (`> as_of`, not `>= as_of`): an edit AT `as_of`
> # is in force. With equal-cursors (`as_of == until_ts`) a fact and an
> ```

Scope caveat that matters for 0.8.0: this ts-as-of exists only on the **stream and ticks
routes**. The **fold route refuses it** (apps/loops/src/loops/cli/views/read.py:66–89,
commit 184dfce):

> ```python
> # Temporal flags without a temporal route: the folded read cannot
> # honor them yet, and silently dropping a cursor renders head state
> # as if it were T — a silent anachronism (SPEC §9.3's honesty
> # posture: rewound reads must never silently lie). Refuse until
> # fold-state-as-of ships (0.8.0 temporal-cursor work).
> ```

Also note the incumbent internally uses BOTH axes already, one per job, mirroring §8.4:
`since_raw(cursor)` — the incremental fold-replay entry — takes a **rowid (witness) cursor**
but orders by event time: `"SELECT kind, ts, payload FROM facts WHERE rowid > ? ORDER BY
ts, id"` (engine/sqlite_store.py:920–923), with the docstring "FOLD REPLAY ORDER is (ts, id)
— event order … Witness order (rowid) remains the chain/window authority"
(sqlite_store.py:902–907). And the tick's `fact_cursor` in the §8.2 envelope is a
witness-order position (SPEC.md:806–819). The declaration-edit ceremony even defends the
ts-as-of semantics at write time: all rows of one edit share ONE `ts` because "a historical
``as_of`` cursor could land *between* the rows of one edit and observe a half-applied
ontology" (sqlite_store.py:719–724).

**Against the vectors:**

- **FAIL: none.** No vector encodes an as-of anchor, so no vector can fail under any as-of
  axis choice. Verified exhaustively (§4 scan; harness code paths have no cursor parameter).
- **Indeterminate: none — but vacuously.** Every ts in the corpus is distinct (§5), so even
  a retrofitted ts-only cursor placed at any fixture ts is deterministic over this data.
  The corpus **cannot** expose the one known indeterminacy of a ts-only cursor: two facts at
  equal ts, where "as of T" cannot place the cursor between them, while `(ts, id)` order
  (and witness order) can. That fixture does not exist; §4.6 defers even the related TopN
  tie vector.
- **The only thing the corpus forbids** is moving the replay *order* off `(ts, id)`:
  witness-order replay demonstrably fails `TestMergeCommutativity` (§7). Any as-of design
  whose *replay prefix* is "all facts ≤ cursor **in (ts, id) order**" replays a prefix of
  the exact sequence the vectors already certify. A design that replayed a witness-order
  prefix would conform on as-of (unvectored) while contradicting the certified full-replay
  order the moment the cursor reaches head — an incoherence the merge fixture makes visible.

---

## 9. Boundary of the evidence (what this chapter does NOT establish)

- The corpus says nothing about **tick-anchored** cursors — ticks tables are empty, no
  vector references ticks, and the §8 chain layer (where `fact_cursor` lives, witness-order)
  has no vectors yet (§8.7 "to build").
- The corpus says nothing about **ontology-as-of** (§9.3's second cursor) — zero `_decl.*`
  rows in any fixture.
- `proc.expected.json` is pinned to an older Python commit (33937f6) than the vectors and
  merge fixture (581df73); both commits exist in loops history (verified). Not a semantic
  divergence — the suite passes — but regeneration cadence is uneven.
- The Go side is a **reader**, not an engine: no emit, no ticks, no merge primitive of its
  own (merge_test.go:17: "even though Go has no merge primitive of its own yet"). The
  conformance surface certifies atoms + store-read only (SPEC §0.6 "Certify" tier through §6).

---

## Appendix A — fold-vector shape (representative raw vector)

`upsert_partial_payload_preserves_prior` (fold_vectors.json:245–281) — shows the full
schema; note the absence of ids/ts/cursors:

```json
{
  "name": "upsert_partial_payload_preserves_prior",
  "folds": [ { "op": "upsert", "target": "tasks", "key": "name" } ],
  "initial": { "tasks": {} },
  "payloads": [
    { "name": "demo", "status": "open", "priority": "high", "message": "initial body" },
    { "name": "demo", "status": "in_progress" }
  ],
  "expected": { "tasks": { "demo": {
    "name": "demo", "status": "in_progress", "priority": "high",
    "message": "initial body", "_n": 2 } } },
  "order_sensitive": true
}
```

## Appendix B — commands to reproduce every claim

```bash
cd ~/Code/loops-go && go test ./internal/conform/ -v          # 7 oracles, 150 subtests
sqlite3 testdata/stores/proc.db "SELECT rowid,id,ts,kind,payload FROM facts ORDER BY rowid"
sqlite3 testdata/stores/merge_ab.db "SELECT rowid,id,ts FROM facts ORDER BY rowid"   # vs merge_ba.db
sqlite3 testdata/stores/proc.db "SELECT ts FROM facts GROUP BY ts HAVING COUNT(*)>1" # empty
grep -c as_of testdata/vectors/*.json                          # 0, 0
# counterfactual replay (from ~/Code/loops): §7 script — Spec.replay over ORDER BY rowid vs ts,id
```
