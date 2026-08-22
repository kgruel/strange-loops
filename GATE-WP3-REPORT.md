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
