# GATE REPORT — sol-HIGH total-completion r1 remediation

Independent gate. Target `87704357` on `slice/D-solhigh-r1` (fix `7c792dfd`),
merge-base `3b432511`. Branch `slice/D-solhigh-r1-gate`.

## VERDICT: **PASS** — all five findings closed, no blocking findings.

Two observations recorded below; neither blocks.

---

## 0. A receipt gap, stated first

The assignment pointed me at
`docs/scratch/arrival-sliceD-impl/sol-high-total-r1-stdout.log` to re-derive
sol's fixtures from its pasted evidence. **That file does not exist** — not in the
worktree, not anywhere under `docs/`, not in git history
(`git log --all --diff-filter=A -- "*sol-high-total*"` returns only the brief),
and not in the `wt-solhigh` worktree. The only sol-HIGH artifact committed is
`sol-high-total-brief.md`, which states the round's charter but contains no
findings or evidence.

So I could not replay sol's reproductions. **I built my own instead**, from the
five findings as described in `SOLHIGH-FIX-REPORT.md` plus my own reading of the
diff. That is arguably the stronger form of verification — independent
re-derivation rather than re-running someone's script — and it is what the rest of
this report rests on. But this arc has been receipt-disciplined throughout, and a
sol round whose stdout is not committed is a gap worth naming before the
convergence decision: **round 2 cannot diff against a round-1 log that isn't
there.**

## 1. Scope and suites

In-fence: three engine sources (`canonical_audit.py`, `sqlite_store.py`,
`store_reader.py`) plus their tests and the report. Nothing else.

Baselines measured by this gate at `3b432511`:

| Suite | Baseline | HEAD | Delta |
|---|---|---|---|
| atoms | 517 | 517 | 0 |
| **engine** | **1894 passed, 1 skipped** | **1900 passed, 1 skipped** | **+6** |
| sdk | 324 | 324 | 0 |
| lang | 655 | 655 | 0 |
| store | 176 | 176 | 0 |
| arch | 98 | 98 | 0 |
| apps/loops | 2530 + 1 xfail | 2530 + 1 xfail | 0 |

The +6 decomposes exactly against collected counts: `test_query_facts` 29 → **31**
(+2), `test_arrival_coordinate_d0` 31 → **34** (+3), `test_audit_rebase_d3`
14 → **15** (+1). Matches the claimed figure.

## 2. The five reproductions — all independently re-derived

### SOL-HIGH-01 — structure alone no longer earns the stamp

Fixture: an arrival-lineage store whose `facts`/`ticks` are **structurally
complete** (both columns, NOT NULL, UNIQUE) and **unmarked**, with coordinates
shifted +10 against what the provider reports.

```
REFUSED: index coordinates do not match arrival log
         (facts row 'f0' has (10, 0), log has (0, 0)) — run …rederive_projections
marker stamped? None
```

Refuses with a precise location claim naming the row and **both** pairs, and the
`coordinate_axis` marker is *not* written. Structure alone no longer earns it.

### SOL-HIGH-02 — quoted identifiers survive the rebuild

Fixture: a legacy (coordinate-less) store carrying a view `weird"view`, an index
`idx"quoted`, and a trigger `trg"quoted` — all with embedded double quotes, the
shape that breaks raw interpolation.

```
views   : ['weird"view']
triggers: ['trg"quoted']       tbl_name='facts'
indexes : ['idx"quoted', 'idx_facts_kind', 'idx_facts_ts']
rows    : [(1, 'x', 1, 0)]     rowid preserved
quoted trigger fired: True     plain trigger fired: True
```

All artifacts migrate intact and both triggers fire against the rebuilt table.

**Correction to my own first measurement.** My initial probe reported "quoted
trigger still fires: False". That was *my* error, not the code's: I asserted
`COUNT(*) == 1` on an audit table that already held a row from the pre-rebuild
insert. Re-run with the table cleared between phases, both triggers fire. Recording
it because the false negative was mine.

### SOL-HIGH-03 — no record is ever split across pages

Fixture: ordinals `0 | 1×5 (a batch) | 2 | 3`, eight facts, `limit=3` — so the
limit lands **inside** the five-row batch.

```
oldest  page1: n=6 ids=[f0,f1,f2,f3,f4,f5] truncated=True
oldest  page2: n=2 ids=[f6,f7]             truncated=False
newest  page1: n=7 ids=[f7,f6,f5,f4,f3,f2,f1] truncated=True
newest  page2: n=1 ids=[f0]                truncated=False
-> all 8 facts seen exactly once: True (dupes=False)   [both orders]
```

The page extends past `limit` to carry the whole batch, in both directions, with
no duplicates and no omissions.

### SOL-HIGH-04 — the NULL backstop checks the pair

Fixture: a healthy arrival store with the NOT NULL constraints relaxed, then one
cell nulled — **each column tested separately**:

| Nulled column | `counts` check |
|---|---|
| `arrival_ordinal` | `ok=False` — *"this index holds a row carrying no arrival coordinate (facts has NULL arrival_ordinal)"* |
| `arrival_seq` | `ok=False` — *"…(facts has NULL arrival_seq)"* |

Both fail, and both name the table **and** the specific column. The ordinal-only
version would have passed the `arrival_seq` case.

### SOL-HIGH-05 — the deep-audit claim is exactly 1 + N

Instrumented at the anchor seam (`_record_ending_at`) and the verification seam
(`_verify_from`), at two sizes:

| facts | anchor | walk | total | `== 1 + N` |
|---|---|---|---|---|
| 5 (6 records) | 1 | 6 | 7 | yes (7) |
| 20 (21 records) | 1 | 21 | 22 | yes (22) |

The corrected claim holds exactly, and it scales as stated rather than
approximately.

## 3. Mutation proof 03, re-run independently

I removed the page extension myself (replacing the extend-and-probe block with
unconditional `truncated = True`):

```
3 failed, 1897 passed, 1 skipped
  test_exact_limit_boundary_not_truncated
  TestSolHigh03AtomicRecordPageExtension::test_two_facts_in_batch_seen_across_pages
  TestSolHigh03AtomicRecordPageExtension::test_limit_1_over_3_row_batch_returns_all_3
```

Restored: 1900 passed. Two dedicated tests plus one pre-existing boundary test
catch it — the behaviour is pinned, not just implemented.

## 4. The SOL-HIGH-03 hot path is bounded

The extension adds **two** statements per page (the assignment anticipated one),
and both are bounded:

1. the extension fetch — `arrival_ordinal = ? AND arrival_seq >/< ?`, an equality
   on the ordinal, so it returns at most *one record's worth* of rows;
2. the truncation probe — `SELECT 1 … arrival_ordinal >/< ? LIMIT 1`.

Both ride the `UNIQUE (arrival_ordinal, arrival_seq)` index from D0, so both are
index seeks rather than scans. Measured across a full pagination run:

```
SELECTs across 2 pages: 7  (~3.5/page)
statements lacking both a LIMIT and an arrival_ordinal predicate: []
```

Every statement issued carries either a `LIMIT` or an `arrival_ordinal`
predicate — **no scan on the read path**. The extension also only runs when
`len(rows) == limit`, so a short final page costs nothing extra.

**Observation (not a finding): a page can exceed `limit` substantially.** Because
the limit is a floor and records are atomic, `limit=3` returned **7** items in the
`newest` direction above. That is the ruled semantics working correctly, but it
means a caller sizing a buffer or a UI page on `limit` can receive
`limit + (record_size − 1)` rows, and a single pathological record with N rows
makes one page O(N). Inherent to "never split a record" rather than a defect —
worth stating in the `query_facts` docstring, which currently says the limit is a
floor without naming the worst case.

## Bottom line

All five sol-HIGH findings are closed, verified against fixtures I built rather
than replayed. The two I would single out: SOL-HIGH-01 now refuses with a location
claim that names both coordinate pairs instead of stamping on structure, and
SOL-HIGH-05's bound is exact at two different sizes rather than asymptotically
right. The 03 fix does what it claims on the hot path without introducing a scan.

The one thing I want on the record before the convergence decision is §0: the
round-1 stdout log referenced by the assignment does not exist in the repository,
so this gate's evidence is independently derived rather than corroborating sol's.
That does not change the verdict — but round 2 will have nothing to diff against.

**PASS.** Ready to merge and for sol-HIGH round 2 to decide convergence.
