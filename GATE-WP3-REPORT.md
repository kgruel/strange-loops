# GATE REPORT — WP-3 (seal re-base D2 + the W2-1 cursor ruling)

Independent gate. Target `eb1b6566` on `slice/D-wp3` (impl `8f800ccf`), merge-base
`b4fc82aa`. Branch `slice/D-wp3-gate`. Implementer: flash-high (different family
from this gate).

This package implements the ruling on **my own W2-1 escalation**, so my WP-2
probes are the oracle and I re-ran them verbatim rather than relying on the
implementer's account of them.

## VERDICT: **PASS** — no blocking findings.

The signed-bytes law holds under byte comparison, both of my W2-1 oracles now
pass, and seals minted by the *old* code verify under the *new* code. Three
non-blocking findings, the first substantive.

---

## 1. SIGNED BYTES LAW — the blocking check — HOLDS

Diffed each commitment function against `b4fc82aa`:

| Function | Result |
|---|---|
| `_tick_envelope` | **byte-identical** |
| `_fact_row_hash` | **byte-identical** |
| `_fact_commitment_hash` | **byte-identical** |
| `fact_commitment_hash` | **byte-identical** |
| `_TICK_ROW_SQL`, `TICK_COLUMNS`, `FACT_CONTENT_COLUMNS` (era-aware column lists) | **identical** |

Every crypto-adjacent line in the whole `sqlite_store.py` diff is an `ORDER BY`
re-key on a *walk* — which tick is visited next — not a change to any signed
field. There is **no write-path change to `window_start` or `fact_cursor`**; a
grep for assignments to either is empty, and the fixture below confirms they are
still fact ids on disk. No drift. Not blocking.

## 2. My W2-1 oracles — both now pass

**Oracle A — incremental vs full replay on the permuted corpus.** This is the
exact probe that failed at WP-2:

| Corpus | full replay | incremental | equal? |
|---|---|---|---|
| ordered | `[0..7]` | `[0..7]` | yes |
| **permuted** | `[0,1,2,3,4,5,6,7]` | `[0,1,2,3,4,5,6,7]` | **yes** |

At WP-2 the permuted row read `[0,1,2,3,1,3,4,6]` — rows 1 and 3 re-delivered, 5
and 7 dropped. That divergence is gone; incremental now equals full replay and
both equal arrival order.

**Oracle B — the batch trap that killed the naive fix.** At WP-2 I showed that
re-keying the `WHERE` to `arrival_ordinal > ?` with a count cursor *drops
mid-batch rows*. Against a corpus of `ord 1 = 1 row, ord 2 = a batch of 3,
ord 3 = 1 row`, forcing a stop **mid-batch**:

```
step1: cursor->(2, 0), got ['f0', 'b0']
step2: cursor->(2, 2), got ['b1', 'b2']     <- resumes INSIDE the batch
step3: cursor->(3, 0), got ['f1']
delivered: ['f0','b0','b1','b2','f1']   MISSING: none | duplicates: False
```

The pair cursor resumes correctly at `(2,1)` where the ordinal-only cursor
skipped to ordinal 3. `b1` and `b2` — precisely the rows the naive fix dropped —
are delivered, in arrival order, exactly once. **The ruling is implemented
correctly, including the trap.**

## 3. Backward verifiability — exercised ACROSS code versions

The claim that matters is not "old-shaped seals verify", it is "seals minted by
the previous code verify under this code". I built the fixture in a scratch
worktree checked out at the **merge-base**, then verified it with WP-3:

- Built at `b4fc82aa` (pre-WP-3 code): 12 facts, 3 signed sealed windows.
  `verify_chain` there → `ok: True, chained: 3, signed: 3, covered_facts: 12`.
- Same bytes verified under WP-3 code → **identical result dict**, including
  `sig_checked: True`, `signed: 3`, `covered_facts: 12`, `uncovered_facts: 0`,
  `breaks: []`.
- `fact_cursor` on disk is still a **fact id** (`01M0NTPW…`), not an ordinal.

The signature check genuinely ran (`sig_checked: True`) rather than being skipped
into a vacuous pass.

## 4. Scope and suite reconciliation

Scope is in-fence: `sqlite_store.py`, `jsonl_store.py`, `projection.py`,
`replay.py`, engine tests, report. (`vertex.py` was permitted but untouched — a
subset, fine.)

Baselines measured by this gate at `b4fc82aa`, not inherited:

| Suite | Baseline | HEAD | Delta |
|---|---|---|---|
| atoms | 517 | 517 | 0 |
| **engine** | **1870 passed, 1 skipped** | **1876 passed, 1 skipped** | **+6** |
| sdk | 324 | 324 | 0 |
| lang | 655 | 655 | 0 |
| store | 175 | 175 | 0 |
| arch | 98 | 98 | 0 |
| apps/loops | 2525 + 1 xfail | 2525 + 1 xfail | 0 |

`test_seal_rebase_d2.py` collects exactly **6**; 1870 + 6 = 1876. The
implementer's report tables the same figures and they match mine.

## 5. `test_tick_chain.py::test_displaced_fact_breaks_window` — necessary, NOT weakened

The mutation changed from `UPDATE facts SET rowid = 1000` to
`UPDATE facts SET arrival_ordinal = 1000`. I judged this empirically rather than
by reading:

| Displacement under WP-3 code | `verify_chain` |
|---|---|
| `rowid = 1000` (the OLD mutation) | `ok=True, breaks=0` — **NOT detected** |
| `arrival_ordinal = 1000` (the new one) | `ok=False, breaks=1` — **detected** |

Windows are arrival-coordinate ranges now, so displacing a row on the rowid axis
no longer moves it out of its sealed window. **Keeping the old mutation would
have left a test that passes while asserting nothing** — a false green. The
change is required for the test to keep testing anything, and it targets the axis
that now governs. Equivalent in intent, and strictly stronger than the vacuous
alternative.

## 6. Break/restore — and what it exposed

Assigned proof was G-D2-4. I reverted the chain-head lookup to the rowid axis:

- `ORDER BY arrival_ordinal DESC, arrival_seq DESC` → `ORDER BY rowid DESC`
- **G-D2-4 PASSED.** The test that failed was **G-D2-5**, the text ratchet — and
  only because I had reintroduced the literal token `rowid`.
- Restored: 6 passed.

That G-D2-4 does not discriminate the chain-head axis is what led to W3-1.

---

## FINDING W3-1 — MODERATE — a real rowid-axis regression passes the entire suite when spelled `oid`

**Production code is correct today.** This is about what the net would catch
tomorrow, and it is the same shape as the R5-1 finding from the WP-1 rounds.

SQLite accepts `oid` and `_rowid_` as exact synonyms for `rowid` — verified, all
three spellings return identical results. G-D2-5's three pattern rules match only
`\browid\b`, and its AST rule tests `"rowid" in func_code`, so `oid` is invisible
to **all four** checks. (`_rowid_` contains the substring, so the AST rule does
catch that one.)

Combined with G-D2-4's failure to discriminate the chain-head axis, the two gates
have a shared blind spot. Demonstrated:

```
# chain-head lookup reverted to the rowid axis, spelled `oid`
=== D2 suite ===     6 passed
=== engine suite === 1876 passed, 1 skipped
```

**A genuine regression of exactly the property D2 exists to establish leaves all
1876 engine tests green.**

**Recommended disposition — narrow the claim, do not grow the detector.** Per the
project's own scope-the-claim rule, the fix is *not* to extend the regex to chase
`oid`/`_rowid_`; that is a detector arms race whose next evasion is a view or a
computed alias. Instead:

1. **Re-scope G-D2-5's claim** to what it actually establishes — "no *literal*
   `rowid` token appears in ordering/range/count position" — a location claim, not
   the verdict "this file is off the rowid axis" that its current name and
   docstring assert.
2. **Give G-D2-4 the discriminating power** the verdict needs: a behavioural
   assertion that the chain head resolves on the arrival axis (e.g. on a permuted
   store, the chain head is the arrival-latest tick, not the rowid-latest). A
   behavioural gate catches every spelling, including ones nobody has thought of.

The detector is still worth keeping — it defends the realistic failure mode of
someone typing `rowid` again. It just should not claim more than it checks.

## FINDING W3-2 — MINOR — stale allowlist entry

G-D2-5's allowlist names five functions. **`_rebuild_table_with_coordinates` does
not exist** in `sqlite_store.py` (the real name is `_rebuild_table`; the other
four exist). Harmless today — a name that never matches can never widen anything
— but it silently pre-authorizes any future function that takes that name, which
is the one way an allowlist entry can do damage. Drop it.

## FINDING W3-3 — MINOR — the union-typed cursor has an incompatible consumer

`Projection.cursor` is now `tuple[int, int] | int`. Two hazards, both currently
**unreachable**:

1. `vertex.py:981` reads `loop._projection.cursor` and uses it as a **count** —
   `replayed >= loop.boundary_count` and `replayed % loop.boundary_count`. I
   confirmed both raise `TypeError` on a tuple. This is unreachable today only
   because **`Projection.advance()` has zero production callers** (a repo-wide
   grep for `.advance(` outside tests is empty), so loop projections are fed
   exclusively through `fold_one`/`fold_one_mut` and keep int cursors. But
   `advance()` is precisely the API one would reach for to add incremental
   catch-up, and doing so would break that consumer.
2. `fold_one`'s tuple branch advances `(cursor[0] + 1, cursor[1])` — bumping the
   **ordinal** and holding `seq`. For a batch that is wrong in the same way the
   naive WP-2 fix was wrong: within one ordinal the cursor should advance `seq`.
   Also unreachable while the two cursor kinds never mix.

Neither breaks anything now. Both are worth closing while the design is fresh —
either by giving the coordinate cursor its own attribute, or by making
`vertex.py`'s boundary arithmetic ask the projection for a count rather than
reading the cursor.

**Related note (not a finding):** `replay()`'s return type changed from
`store.total` (an int) to a coordinate tuple on the `since_with_cursor` path. It
has no production callers that consume the return value, so nothing breaks, but
it is a signature change worth knowing about.

---

## What I could not verify

- No concurrent-writer testing against the pair-cursor queries; my equivalence
  probes are single-writer, single-reader.
- The `oid` evasion is demonstrated for the pattern rules; I did not attempt to
  enumerate every other way the text scan could be evaded, deliberately — that is
  the arms race W3-1 recommends against.

## Bottom line

**WP-3 PASSES.** The crypto invariant holds under byte comparison, the W2-1
ruling is implemented correctly — including the mid-batch resume that defeated
the naive fix — and seals minted by the previous code verify identically under
this one, tested across actual code versions rather than across shapes. The
`test_tick_chain` change was necessary, not a weakening: I verified the old
mutation is now undetected and would have left a vacuous test.

W3-1 is the finding worth acting on: the D2 gates cannot distinguish a correct
implementation from a reverted one that spells `rowid` as `oid`, and I showed the
whole engine suite staying green through that regression. The right response is to
narrow what the text ratchet claims and to make the behavioural gate carry the
verdict, not to teach the regex more spellings.

---
---

# ROUND 2 — re-gate of the WP-3 fix (`6dc12f15`)

Scoped to W3-1, W3-2, W3-3. Gate branch rebased onto `6dc12f15`.

## ROUND 2 VERDICT: **PASS** — all three findings closed.

Scope is in-fence and additive: `vertex.py` (+4), `test_seal_rebase_d2.py` (+76),
`test_vertex.py` (+30), fix report. No production logic outside the one guard.

## W3-1 — CLOSED. The decisive check: my `oid` mutation now fails, in G-D2-4.

Re-applied the exact mutation from Round 1 — chain-head selection reverted to the
rowid axis spelled `oid`:

| | Round 1 | Round 2 |
|---|---|---|
| D2 suite | 6 passed | **1 failed**, 5 passed |
| engine suite | **1876 passed** (regression invisible) | **1 failed**, 1876 passed |
| failing test | — | `TestGD2_4_VerificationUnderPermutation::test_permuted_insert_verify_chain_identical` |

It fails in **G-D2-4**, the behavioural gate — not the text ratchet — which is
exactly where the verdict was supposed to move. Restored: green.

**Second site, not rehearsed in their proof.** Their demonstration mutates
predecessor selection in `append_tick_attested`. I picked a different site — the
`verify_chain` tick-ordering walk (`sqlite_store.py:2474`,
`SELECT {row_sql} FROM ticks ORDER BY …`) — and mutated it to `ORDER BY oid`:

```
1 failed, 1876 passed
FAILED …TestGD2_4_VerificationUnderPermutation::test_permuted_insert_verify_chain_identical
```

Caught, and at a **different assertion** (line 334) than the chain-head mutation
hits (line 357). So the strengthened gate discriminates at least three distinct
sites — theirs, my chain-head one, and my tick-walk one — rather than being
fitted to the single case they rehearsed. *(Correction to my own read: I initially
described 2474 as a reanchor walk; it is inside `verify_chain`. Still a distinct
code path and a distinct assertion, but I want the record accurate.)*

The strengthening is genuinely behavioural, not a text check in disguise: it
asserts arrival-axis outcomes that differ from rowid-axis ones and says so
inline — `window_facts == 2` where the rowid axis gives 4 and 0, `current_chain_head()`
resolving to `t-2` where rowid picks `t-1`, and live minting under permutation
where predecessor, `window_start`, and the newest-fact edge (`f-5`, where the
rowid axis would pick `f-4`) must all follow arrival.

**The claim is narrowed, as ruled.** G-D2-5's docstring now reads:

> NOTE: This ratchet is a residue locator for the literal 'rowid' spelling, not
> proof of axis correctness against synonyms or alternative syntax. The
> behavioral gates (such as G-D2-4) own the axis-correctness verdict.

That is a location claim, not a verdict claim — the scope-the-claim disposition
applied exactly, and the regexes were correctly **not** grown to chase `oid`.

## W3-2 — CLOSED

The allowlist shrank from five names to four; `_rebuild_table_with_coordinates`
is gone and the explanatory comment now names `_rebuild_table`. All four
remaining entries exist in `sqlite_store.py` (verified individually in Round 1).

## W3-3 — CLOSED for the reachable hazard; the second is a declared deferral

`vertex.py:982` now raises `NotImplementedError("loop boundary accounting is
count-based; pair-cursor projections are not yet supported here")` when the cursor
is a tuple, and `test_vertex.py` pins that exact message. That converts the latent
`TypeError` I found into an explicit, named refusal — the honest disposition,
since pair-cursor boundary accounting is not implemented rather than merely
mis-typed.

- **Pin test passes** (1 passed).
- **Int-cursor behaviour unchanged**: 105 boundary tests pass; the guard fires
  only on `isinstance(replayed, tuple)`, so the count path is untouched.

**Hazard #2 remains and that is fine.** `projection.py` was not touched, so all
three tuple-cursor bumps still compute `(cursor[0] + 1, cursor[1])` — advancing
the ordinal where a batch needs `seq`. It stays unreachable (`advance()` has no
production callers; `advance()` itself assigns the store's correct pair; the
boundary consumer now refuses tuples outright). The fix report **declares this
explicitly** — *"Cursor type unification deferred as a candidate for the simplify
pass"* — rather than claiming W3-3 fully closed. I agree with the deferral and am
recording it as a tracked deferral, not a residual finding.

## Suite reconciliation

| Suite | Round 1 (`eb1b6566`) | Round 2 (`6dc12f15`) | Delta |
|---|---|---|---|
| engine | 1876 passed, 1 skipped | **1877 passed, 1 skipped** | **+1** |
| apps/loops | 2525 + 1 xfail | **2525 + 1 xfail** | 0 |

+1 is exactly the W3-3 pin test. `test_seal_rebase_d2.py` still collects **6** —
the G-D2-4 strengthening was in-place assertions, not new cases, which is the
right shape for making an existing gate discriminate rather than adding a parallel
one. The fix report's suite table lists all seven suites and every figure matches
mine.

## Bottom line

All three findings are closed by the rulings, and the one that mattered is closed
in the right place: the axis-correctness verdict now lives in a behavioural gate
that catches the regression regardless of spelling, while the text ratchet has
been demoted to the residue locator it always was. My own evasion no longer works,
and neither does the same evasion at a site nobody rehearsed.

WP-3 is ready for the sol-low pass check.

---
---

# ROUND 3 — SOL-WP3-01 fix + the mandated residue sweep (`ec6b70c3`)

Scoped to the live_edge fix and the four sweep sites. Gate branch rebased onto
`ec6b70c3`.

## ROUND 3 VERDICT: **PASS** — SOL-WP3-01 closed, sweep fixes correct.

One coverage finding (W3-R3-1) and one scope disposition recommended for the
arbiter (§3b). Neither blocks.

## 1. SOL-WP3-01 — closed, reproduction re-derived independently

I rebuilt sol's scenario from the description rather than running their fixture: a
store whose sealed cursor's **rowid** sits behind an unsealed fact while its
**arrival** coordinate does not.

```
rowid vs arrival:   (1,'f-2',ord 2)  (2,'f-0',ord 0)  (3,'f-1',ord 1)
sealed cursor f-1 has rowid 3 (the highest) -> facts with GREATER rowid = 0
   => the OLD rowid-based live_edge reports 0

verify_chain: covered=2  uncovered=1
live_edge   : 1
*** AGREE: True
```

The old boundary would have reported an empty live edge while `verify_chain` said
one fact was unsealed — the exact divergence. They now agree.

The fix uses SQLite row-value comparison, `(arrival_ordinal, arrival_seq) > (…)`,
which is the correct pair semantics rather than an ordinal-only cutoff. The two
`COALESCE` fallbacks are `(-1, 0)`, so every documented fallback still yields the
conservative *whole-store-on-the-edge* answer; they cannot disagree with each
other because `arrival_seq` is `NOT NULL`.

**Mutation proof re-run independently.** I reverted `live_edge` to the old
rowid boundary myself:

```
1 failed, 1877 passed, 1 skipped
FAILED …TestGD2_4_VerificationUnderPermutation::test_live_edge_agrees_with_verify_chain_under_permutation
```

Restored: 1878 passed. *(My first attempt at this mutation had a Python syntax
error and silently never applied — the suite I saw was unmutated. I caught it and
redid it; recording the misstep rather than the clean second run alone.)*

## 2. Suite reconciliation

| Suite | Round 2 (`6dc12f15`) | Round 3 (`ec6b70c3`) | Delta |
|---|---|---|---|
| engine | 1877 passed, 1 skipped | **1878 passed, 1 skipped** | **+1** |
| store | 175 | **175** | 0 |
| apps/loops | 2525 + 1 xfail | **2525 + 1 xfail** | 0 |

`test_seal_rebase_d2.py` collects **7** (was 6) — the one new live_edge test.
+1 engine, exact.

## 3a. The sweep fixes to `slice.py` / `rebirth.py` / `merge.py` — CORRECT

**Semantics.** All four are *source-reading* or *newest-row* sites, and arrival
order is the arc's receipt order:

- `merge._read_index_source` — a transport `.db`'s rows now replay into the target
  in the source's arrival order, which is the order the source received them.
- `rebirth._chain_head` and `verify_rebirth` — pick the arrival-newest tick/receipt,
  matching `SqliteStore.current_chain_head()`, which WP-3 already re-keyed. Leaving
  these on rowid would have made rebirth and the engine disagree about the chain
  head on a permuted store.
- `slice.slice_store` — allocates target coordinates by `ROW_NUMBER` over the
  source's arrival order, so a slice preserves receipt order into the target.

Every site is era-aware: a `PRAGMA table_info` probe with a `rowid` fallback, so
pre-coordinate transport files still work.

**Zero behaviour change on mirrored stores — verified, not assumed.** On a
mirrored store `arrival_ordinal == rowid` for every row, so the two `ORDER BY`
clauses are provably the same sequence:

```
MIRRORED : rowid==ordinal for all rows: True
           by rowid  = ['f-0','f-1','f-2','f-3','f-4']
           by arrival= ['f-0','f-1','f-2','f-3','f-4']   identical -> ZERO change
```

**And non-vacuous where it should bite.** On a permuted source the orderings
differ, and the slice now carries arrival order into the target's coordinates:

```
PERMUTED : by rowid  = ['f-3','f-0','f-4','f-1','f-2']
           by arrival= ['f-0','f-1','f-2','f-3','f-4']
           slice out = [('f-0',1),('f-1',2),('f-2',3),('f-3',4),('f-4',5)]
```

Under the old ordering the slice would have written `f-3` at ordinal 1, scrambling
receipt order into the target. The fix is the correct semantics per the arc.

**Existing transport/rebirth tests still pin output equivalence** — `test_slice.py`,
`test_rebirth.py`, `test_merge.py`, `test_transport.py`, `test_properties_merge.py`
and `test_conformance_merge.py` are all green at 175, unchanged. They pin the
mirrored corpus, which is the whole real corpus today.

## 3b. `apps/loops/commands/store.py` — RECOMMENDATION: accept, as a *second, narrow* exception

**What it actually changes.** Two queries inside `_read_absorption_state`
(`:866-895`):

1. `SELECT id FROM facts ORDER BY rowid DESC LIMIT 1` → the newest-fact cursor.
2. `SELECT … FROM ticks WHERE window_hash IS NOT NULL ORDER BY rowid DESC LIMIT 1`
   → fed straight into `tick_row_hash(row)`, i.e. **the chain head**.

**My recommendation: accept it under the sweep mandate — this is a forced
same-class fix, not scope creep.** Reasoning:

- Query 2 is *character-for-character* the chain-head selection the engine
  re-keyed in WP-3 — the very statement I mutated in Rounds 1 and 2. The app
  carries a duplicate of the engine's seal-chain derivation.
- Both quantities are signed-chain quantities. Leaving them on rowid creates an
  **app-vs-engine axis split on the exact value D2 re-based**: on a permuted store
  the app would compute a different chain head than the engine, which is the
  false-tamper / bad-prev_hash-linkage class the sweep exists to close.
- It is ordering-authority-in-a-seal-context, squarely the sweep's stated class.
- The edit is minimal and era-aware, identical in shape to the other three sites.

**But it should be recorded as a distinct exception, not absorbed into the
existing one.** The ruled D-Q2 exception covers the **audit dispatch arm**
(`:141-163`, WP-4 scope). This touch is a *different function and a different
concern* several hundred lines away. "store.py is already an exception file" must
not become blanket pre-authorization for further apps/ touches — the file being
excepted once is not the same as the file being open. I recommend the arbiter
record a second, narrowly-worded exception: *seal-chain ordering authority in
`_read_absorption_state`*, and nothing wider.

**Caveat if accepted:** it is unpinned. See below.

## FINDING W3-R3-1 — MINOR — the sweep changed four sites and added zero tests

The sweep commit `5bf44f52` touches `merge.py`, `rebirth.py`, `slice.py` and
`apps/loops/commands/store.py`. `git diff --stat` over `libs/store/tests` and
`apps/loops/tests` for that range is **empty**.

The mirrored corpus cannot discriminate these changes — I proved above that the
two orderings are identical there — so the existing suites are structurally
incapable of catching a revert. Demonstrated:

| Revert | Suite result |
|---|---|
| `slice.py` ordering → `rowid` | **store: 175 passed** |
| `apps/loops/commands/store.py` ordering → `rowid` | **apps/loops: 2525 passed, 1 xfailed** |

Both fixes can be undone with no test noticing.

This is the **third recurrence in this arc** of the same shape — W3-1 (the `oid`
evasion), R5-1 (the marked-incomplete refusal), and now the sweep. The pattern is
consistent: axis-correctness keeps landing as correct code guarded only by review
attention. The engine side got its behavioural ratchet in Round 2 (G-D2-4); the
store and apps sides did not get theirs.

**Recommended:** one permuted-source transport test — slice or merge a permuted
source and assert the target's coordinates follow the source's arrival order — plus
one app-side assertion that `_read_absorption_state`'s chain head matches
`SqliteStore.current_chain_head()` on a permuted store. Two tests close all four
sites, because they are the same claim.

Not blocking: every swept site is correct today, and I verified each one.

## Bottom line

SOL-WP3-01 is closed, and I confirmed it against a reproduction I derived
independently rather than against their fixture — the old boundary reports 0 where
`verify_chain` reports 1, and the new one agrees. The sweep fixes are the right
semantics, era-aware, provably inert on mirrored stores and provably corrective on
permuted ones.

The apps/ touch is a genuine same-class fix and I recommend accepting it, with the
exception recorded narrowly rather than folded into the D-Q2 audit-dispatch
ruling. The one thing I would not leave silent is W3-R3-1: four correct fixes,
zero tests, and both of the ones I reverted stayed green.
