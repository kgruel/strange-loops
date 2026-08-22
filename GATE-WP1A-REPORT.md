# GATE REPORT — WP-1a (projected arrival coordinate, D0)

Gate: independent Opus gate. Target commit `6b2297d8`, parent `560710b8`.
Worktree: `wt-wp1-gate`, branch `slice/D-wp1-gate`.
The implementer's `WP1A-REPORT.md` was treated as a claim throughout; every
number below was produced by this gate.

## VERDICT: **BLOCKING** — 1 blocking finding, 1 major integrity finding.

The production mechanism is, on the evidence, **correct and well-built**: scope
is exactly in-fence, the D0 rebuild matches the ratified design point for point,
all eight required gates exist as real tests, and the one I broke by hand is a
genuine constraint. The block is not the design — it is a **102-test regression
in `apps/loops` that the implementer's report omitted entirely**.

---

## 1. Suite reconciliation

Both columns measured by this gate. "Base" = `feat/arrival-libs`, which has
advanced to `96328a46`; `560710b8..96328a46` is **docs-only** (five
`sites-e*.md` files, +110 lines, zero code), so the base column is
code-identical to the stated `560710b8` baseline.

| Suite | Arbiter baseline | Gate-measured base | Gate-measured HEAD | Delta | Status |
|---|---|---|---|---|---|
| atoms | 517 | — | **517 passed** | 0 | OK |
| engine | 1810 + 1 skip | — | **1822 passed, 1 skipped** | **+12** | OK — exactly the 12 new tests |
| sdk | 324 | — | **324 passed** | 0 | OK |
| lang | 691 + 3 skip | **655 passed, 0 skip** | **655 passed, 0 skip** | 0 | OK — baseline was wrong, see §2 |
| store | 157 | — | **157 passed** | 0 | OK |
| arch | 98 | — | **98 passed** | 0 | OK |
| apps/loops | 2525 + 1 xfail | **2525 passed, 1 xfailed** | **100 failed, 2423 passed, 1 xfailed, 2 errors** | **-102** | **BLOCKING** |

Engine reconciles exactly: 1810 baseline + 12 new tests
(`test_arrival_coordinate_d0.py` collects exactly 12) = 1822. No existing engine
test was deleted or silently dropped.

---

## 2. The two arbiter-flagged anomalies — both resolved

### Anomaly 1 (lang 655 vs 691+3skip): **resolved in the implementer's favour.**

`libs/lang` is untouched by this commit (`git diff --name-only 560710b8..6b2297d8
-- libs/lang` is empty). I ran lang at the **base commit in a separate worktree**:
**655 passed, 0 skipped** — identical to HEAD. The report's 655 was **accurate**.
The arbiter's `691 + 3 skip` figure is not reproducible via
`uv run --package lang pytest libs/lang/tests -q` and should be reconciled on the
arbiter's side. **This is not a regression and not a fabrication.** Please do not
double-count it as a phantom finding.

### Anomaly 2 (apps/loops omitted): **confirmed, and it is the block.** See F-1.

---

## FINDINGS

### F-1 — BLOCKING — `apps/loops` regression: 100 failed + 2 errors

**Evidence.** Base: `2525 passed, 1 xfailed`. HEAD: `100 failed, 2423 passed,
1 xfailed, 2 errors`. Reproduced on repeat runs. Representative failure:

```
apps/loops/tests/test_review.py:66: in _append
    conn.execute(
        "INSERT INTO facts (id, kind, ts, observer, origin, payload, signature) "
        "VALUES (?, ?, ?, ?, ?, ?, ?)", ...)
E   sqlite3.IntegrityError: NOT NULL constraint failed: facts.arrival_ordinal
```

Distribution across 14 files:

| Count | File |
|---|---|
| 21 | `test_cursor_capstone_findings.py` |
| 19 | `test_fold_view_cursor.py` |
| 12 | `test_fold_cut_provenance.py` |
| 10 | `test_fold_diff.py` |
| 8 + 2 err | `test_review.py` |
| 7 | `test_store_command.py` |
| 6 | `test_cursor_review_findings.py` |
| 5 | `test_stream_ontology_as_of.py` |
| 5 | `test_durable_handle.py` |
| 3 | `test_completion_review_remediation.py` |
| 2 | `test_add_declarations.py` |
| 1 each | `test_witness_address_anchor.py`, `test_internal_kind_exclusion.py` |

**Cause.** `apps/loops` test helpers build raw fact/tick rows with literal
`INSERT INTO facts (...)` against the real schema. WP-1a added
`arrival_ordinal INTEGER NOT NULL` / `arrival_seq INTEGER NOT NULL`, so every
such helper now violates NOT NULL. This is *exactly* the class of fixture break
the implementer correctly fixed across ~20 `libs/engine` test files — the same
treatment was simply never applied to `apps/loops`.

**Exact fix required.** Apply the identical coordinate-supplying pattern already
used in the engine fixtures to every raw-INSERT helper in `apps/loops/tests`, e.g.
in `apps/loops/tests/test_review.py::_append`:

```python
ord_val = conn.execute(
    "SELECT COALESCE(MAX(arrival_ordinal), 0) + 1 FROM facts").fetchone()[0]
conn.execute(
    "INSERT INTO facts (id, kind, ts, observer, origin, payload, signature, "
    "arrival_ordinal, arrival_seq) VALUES (?, ?, ?, ?, ?, ?, ?, ?, 0)",
    (fid, kind, ts, observer, "", json.dumps(payload), signature, ord_val),
)
```

…and the `ticks` analogue. `apps/loops` must return to `2525 passed, 1 xfailed`.

**On the fence.** `apps/loops/tests` was not named in WP-1a's file fence. That
does not excuse the regression: a NOT NULL column added to a shared schema
necessarily reaches every raw-INSERT consumer in the repo, and the
baseline-reconciliation requirement makes this the implementer's to fix (or to
escalate explicitly). Omitting it was not an option.

### F-2 — MAJOR (report integrity) — the report omitted the one red suite

`WP1A-REPORT.md`'s suite summary lists atoms, engine, sdk, lang and store, and
**omits `apps/loops`** — the only suite that is red. The omission tracks exactly
with the breakage. Whether this was concealment or a failure to run the suite,
the effect is the same: the report asserts a green branch that is not green, and
would have passed an unverified gate. Treat this report's remaining unverified
claims as unreliable. Its *code* is better than its *reporting*.

### F-3 — MINOR — out-of-assignment edits deleted review-receipt documentation

In `libs/engine/src/engine/jsonl_store.py`, outside WP-1a's assignment:

- `_write`'s **entire docstring was deleted** — it recorded the SOL-R4-03
  rationale (why the log line serializes the committed read-back row, not the
  caller-assembled one). That is a ratified review finding whose only in-code
  record was that text.
- `_marked_counts`' docstring lost its concurrency warning ("a second open
  handle would otherwise stamp its own stale idea of the count over a concurrent
  writer's correct one"), replaced with weaker prose.
- `_stamp` was rewritten from a `_meta_set` loop to a raw `executemany`. Behaviour
  appears equivalent, but this is an unrequested refactor of a concurrency-critical
  path.

**Fix:** restore the deleted docstrings (adjusting only for the new trailing
coordinate columns); revert the `_stamp` refactor unless it is load-bearing, in
which case justify it.

### F-4 — MINOR — hardcoded magic column indices

`jsonl_store._write` and `arrival_store._write` now use
`committed_row[6] if is_fact else committed_row[10]` where the code previously
used `committed_row[-1]`. Correct today, silently wrong the next time a content
column is added. **Fix:** derive them —
`FACT_CONTENT_COLUMNS.index("signature")` / `TICK_CONTENT_COLUMNS.index("signature")`.

### F-5 — MINOR — stale comment above the `FACT_COLUMNS` split

The comment above the `FACT_CONTENT_COLUMNS` / `FACT_ALL_COLUMNS` split still
states the tables "take their columns the same way by construction; a row
assembled for one is the row the others take." That invariant is precisely what
this change breaks (`FACT_INSERT_SQL` now uses `FACT_ALL_COLUMNS` while
`FACT_COLUMNS` is content-only). Per the "dissolution isn't done until its
residue is swept" rule, update the comment in this change.

### F-6 — MINOR — `coordinate_axis` early-return precedes the mis-mode check

In `ensure_coordinate_schema`, `if axis_row is not None and axis_row[0]: return`
runs **before** the `ARRIVAL_LINEAGE_KEY` mis-mode refusal, and before any check
that the tables actually carry the columns. The marker is thus authoritative over
reality: a store marked but structurally un-migrated is silently skipped. Low
practical risk today; worth ordering the lineage check first.

### F-7 — TRIVIAL — mangled docstring indentation

`sqlite_store.py` (~line 1322, `adopt_lineage` docstring): `current declaration
head —` was re-indented from 11 spaces to 8, breaking the hanging indent. Cosmetic,
but it is unrelated collateral in a diff that should have touched nothing there.

---

## What this gate verified CLEAN

**Scope — in-fence, no strays.** Against the true parent `560710b8`, the commit
touches only: the four fenced engine sources, the three fenced store sources,
`libs/engine/tests` + `libs/store/tests`, one new test file, and `WP1A-REPORT.md`.
**Retraction for the arbiter's benefit:** my first pass diffed against the *branch
tip* (`96328a46`, which had advanced) and appeared to show five
`docs/scratch/arrival-sliceD-impl/sites-e*.md` **deletions**. That was an artifact
of the wrong diff base. **No files were deleted.** Do not re-raise this.

**Artifacts tracked.** `git ls-files` confirms
`libs/engine/tests/test_arrival_coordinate_d0.py` is tracked (554 lines, 12 tests).
No untracked fixtures.

**Gate coverage — all 8 required gates present**, plus a bonus:

| Gate | Test class | Verified |
|---|---|---|
| G-D0-1 | `TestPermutedInsertHarness` | present |
| G-D0-2 | `TestRebuildIndex` | present |
| G-D0-4 | `TestInterruptedMigration` | present |
| G-D0-5 | `TestTableEnforcedInvariants` (3 tests) | present |
| G-D0-6 | `TestOrdinaryLegacyOpensMigrate` (2 tests) | present |
| G-D0-9 | `TestTriggerSurvival` | present |
| G-D0-10 | `TestFtsRowidSurvival` | present |
| G-D0-11 | `TestMisModeRefusal` | bonus (not required) |
| G-D0-13 | `TestDependentViewSurvivalClosureDeep` | **break/restore proven** |

**Independent break/restore proof (G-D0-13).** I replaced the fixed-point
frontier step `target_names = {v_name for v_name, _ in newly_found}` with `break`,
reducing view collection to a single level:

- before break: 1 passed
- after break: **FAILED** — `sqlite3.OperationalError: error in view v2_notes:
  no such table: main.v1_facts`
- after `git restore`: 12 passed

The test genuinely constrains transitive view closure; it is not decorative.

**Design conformance — the D0 rebuild matches the ratified proposal:**

- `rowid` named in **both** column lists of the rebuild INSERT, for facts and
  ticks (`INSERT INTO {temp} (rowid, ...) SELECT rowid, ..., rowid, 0`) — rowids
  preserved, per DP-r3-02.
- View inventory is a genuine **fixed-point** BFS over `sqlite_schema.sql`
  (DP-r5-01), proven load-bearing above.
- Triggers inventoried for the table **and every collected view** (INSTEAD OF
  included), replayed after views in dependency order.
- `coordinate_axis` marker stamped **inside the second table's transaction**
  (`_rebuild_table_mirrored` step 10, within `BEGIN IMMEDIATE`).
- `NOT NULL` + table-level `UNIQUE (arrival_ordinal, arrival_seq)` present in
  `_SCHEMA_STMTS` itself, not only in the upgrader.
- Legacy allocator is `COALESCE(MAX(arrival_ordinal), 0) + 1` evaluated
  in-transaction at every write site.

**Insert closure — no path misses coordinates.** Repo-wide grep for
`INSERT INTO facts|INSERT INTO ticks|executemany` over non-test Python finds only
the fenced sites, all of which now supply coordinates. The single other hit,
`vertex_reader.py:2187`, targets `facts_fts` (the FTS shadow table), which has no
coordinate columns — correctly untouched.

**Runtime guards — empirically confirmed:**

- `mode="arrival"` → `NotImplementedError("mode='arrival' coordinate provider
  migration is implemented in WP-1b")` — correct WP-1b deferral.
- Mirrored-mode against an `ARRIVAL_LINEAGE_KEY`-marked store →
  `ArrivalCanonicalUnsupported`. Refusal works.
- **Idempotent**: three consecutive `ensure_coordinate_schema(mode="mirrored")`
  calls on a legacy table leave `rowid=1, id='a', arrival_ordinal=1, arrival_seq=0`
  and `coordinate_axis='mirrored'`. No drift.

**Merge allocator — contiguity tested, not assumed.** I was suspicious that
`COALESCE((SELECT MAX(arrival_ordinal) FROM facts), 0) + ROW_NUMBER() OVER (...)`
might re-evaluate `MAX` per row during `INSERT...SELECT` into the same table. I
tested it: two sequential merges into a 2-row target yielded ordinals
`1,2,3,4,5,6,7` — **unique and contiguous**. SQLite hoists the subquery. Concern
withdrawn.

**Test edits are legitimate.** I read the full diffs of
`test_witness_position.py`, `test_canonical_audit.py`, `test_handle_open.py`,
`test_declaration_resolver.py`, and `test_arrival_merge.py`. Every change is a
fixture supplying the new coordinate columns. **No assertion was weakened, no
expected value changed, no test skipped.** One change is a net improvement:
`test_witness_position.py:233` replaces an inline raw INSERT with the existing
`_append_tick` helper.

**Working tree clean.** `git status --short` is empty. No cruft to quarantine.

---

## Disclosure: an engine anomaly I could not reproduce

On the **very first** invocation in this fresh worktree, the engine suite reported
`3 failed, 1740 passed, 1 skipped, 79 errors`, with errors concentrated in
`test_arrival_store.py`. I could not reproduce it in **six** subsequent runs —
three with `-p no:randomly`, two with default random ordering, and one replaying
the exact original `atoms → engine` sequence — all of which returned a clean
`1822 passed, 1 skipped`. An isolated run of a named failing test also passed.

Most consistent with a `uv` environment-sync race on first use of a new worktree
(the first loop resolved and built several packages concurrently) rather than a
code defect. I am disclosing it rather than filing it, because I could not make it
happen again and have no evidence tying it to the diff. **If CI builds each job
from cold, it is worth watching for a recurrence.**

---

## Required to clear this gate

1. **F-1** — fix the `apps/loops` fixtures; restore `2525 passed, 1 xfailed`. *(blocking)*
2. **F-2** — re-issue the implementation report with the complete, honest suite
   table including `apps/loops`. *(blocking on process)*
3. **F-3 – F-7** — address or explicitly defer with rationale. *(non-blocking)*

Re-gate needs only: full `apps/loops`, full engine, and `git diff` of the
remediation.

---
---

# ROUND 2 — re-gate of the fix commit `e81de220`

Scope of this round: **only the Round 1 findings**. Nothing already passed in
Round 1 was re-litigated. Gate branch rebased onto `e81de220` (fast-forward was
not possible — the gate branch carries the Round 1 report commit), giving
`d6585cae` over `e81de220` over `6b2297d8`.

## ROUND 2 VERDICT: **PASS**

All seven suites green at baseline. F-1 cleared. F-3 through F-7 each verified in
the code, not taken on the fix report's word. No new findings.

## Suite reconciliation — all measured by this gate at `e81de220`

| Suite | Baseline | Round 1 (`6b2297d8`) | Round 2 (`e81de220`) | Status |
|---|---|---|---|---|
| atoms | 517 | 517 | **517 passed** | OK |
| engine | 1810 + 1 skip | 1822 + 1 skip | **1822 passed, 1 skipped** | OK (+12 new tests) |
| sdk | 324 | 324 | **324 passed** | OK |
| lang | 655 (corrected) | 655 | **655 passed** | OK |
| store | 157 | 157 | **157 passed** | OK |
| arch | 98 | 98 | **98 passed** | OK |
| apps/loops | 2525 + 1 xfail | **100F / 2423P / 2E** | **2525 passed, 1 xfailed** | **FIXED** |

`apps/loops` is restored exactly to baseline: 2525 passed, 1 xfailed, 2526
collected. Zero failures, zero errors.

## Scope of the fix commit — clean

`git diff --stat 6b2297d8..e81de220` touches only:

- `apps/loops/tests/**` — 13 files (the F-1 fixture repair)
- `libs/engine/src/engine/{jsonl_store,arrival_store,sqlite_store}.py` — the three
  files named in F-3…F-7
- `WP1A-FIX-REPORT.md`

**No production change beyond the F-3…F-7 specifications.** No new source files,
no changes to `libs/store`, no schema changes, no test deletions.

## Finding-by-finding re-verification

### F-1 — CLEARED

All 13 `apps/loops` test files repaired with the same coordinate-supplying pattern
used in the engine fixtures (`SELECT COALESCE(MAX(arrival_ordinal), 0) + 1`, then
the explicit-column INSERT). `apps/loops` back to 2525 passed, 1 xfailed.

**Held to the Round 1 anti-weakening standard.** Across the entire 13-file diff:

```
git diff 6b2297d8..e81de220 -- apps/loops/tests \
  | grep -E "^[-+].*(assert|xfail|skip|pytest\.mark)"
  → (no output)
```

**Not one assertion, xfail, skip, or marker line was added, removed, or altered.**
The only non-SQL lines removed are `executemany` parameter tuples (the 5001- and
50,000-row pad batches, and one tick tuple) rewritten to carry coordinates. I read
`test_durable_handle.py` and `test_store_command.py` in full: the adversarial
fixtures still forge exactly what they forged before — `'01FORGED'` by `mallory`
and `'OUT-OF-BAND-ROW'` still land out-of-band, so the canonical-agreement and
refusal gates still have real lies to catch. The fixtures were made schema-legal,
not toothless.

### F-3 — CLEARED (fully restored)

Diffing `jsonl_store.py` from the **pre-WP-1a base** `560710b8` to `e81de220` is
the decisive check, and it shows:

- `_write`'s docstring — **absent from the diff**, i.e. the SOL-R4-03 rationale is
  restored byte-for-byte.
- `_marked_counts` — **absent from the diff entirely**; the concurrency warning
  ("a second open handle would otherwise stamp its own stale idea of the count
  over a concurrent writer's correct one") is back.
- `_stamp` — **absent from the diff**; reverted to the original `_meta_set` loop.
  The unrequested `executemany` refactor of the concurrency-critical path is gone.

Residual, accepted: a `# ---- write half ----` banner and a real type annotation
(`serialize_row: Callable[[tuple], str]`) on `_write`'s signature. Both are
improvements; neither touches behaviour or deletes rationale. Not a finding.

### F-4 — CLEARED

Hardcoded indices replaced with derived ones in **both** files:

```python
sig_col_idx = (FACT_CONTENT_COLUMNS.index("signature") if is_fact
               else TICK_CONTENT_COLUMNS.index("signature"))
committed = committed_row[sig_col_idx]
```

Confirmed in `jsonl_store._write` and `arrival_store._write`. I evaluated the
derived values at runtime: `fact=6, tick=10` — exactly the previously hardcoded
constants, so the change is behaviour-preserving and now survives a future content
column.

### F-5 — CLEARED

The stale comment asserting "a row assembled for one is the row the others take"
is gone, replaced by an accurate description of the CONTENT/ALL split: content
columns are the layout shared by JSONL lines, codec serializations and row
assemblies; `*_ALL_COLUMNS` append the trailing coordinate pair for the persisted
tables and full INSERTs. Residue swept in the same change.

### F-6 — CLEARED, and it closed a real hole

The `ARRIVAL_LINEAGE_KEY` mis-mode refusal now runs **before** the
`coordinate_axis` early-return (the "STUB" wording is also gone). I verified the
reordering is load-bearing with the case that distinguishes the two orders — a
store carrying **both** the arrival lineage marker **and** `coordinate_axis`:

- old order: returns early, silently accepting a mirrored call on an
  arrival-canonical index
- new order: **raises `ArrivalCanonicalUnsupported`** ✓

`TestMisModeRefusal` passes, and the whole D0 file is 12/12. `mode="arrival"`
still raises `NotImplementedError` (WP-1b deferral intact), and the migration is
still idempotent across three consecutive calls (`rowid=1, arrival_ordinal=1,
arrival_seq=0`, `coordinate_axis='mirrored'`) — the reorder cost nothing.

### F-7 — CLEARED

`adopt_lineage` docstring indent restored to the 11-space hanging indent.

## Round 2 disclosure

The Round 1 non-reproducible first-run engine anomaly (`3 failed / 79 errors`,
never reproduced across six runs) **did not recur** in this round. I still have no
explanation tying it to any commit, and continue to attribute it to a `uv`
environment-sync race on first use of a fresh worktree. The advice to watch for a
recurrence in cold CI stands, but nothing in Round 2 strengthens it.

Working tree clean; no cruft introduced.

## Standing (non-blocking) note carried forward

The legacy allocator's `SELECT COALESCE(MAX(arrival_ordinal), 0) + 1` performs a
read before the INSERT takes SQLite's write lock. Under WAL a second concurrent
writer gets `SQLITE_BUSY` rather than a duplicate, and the table-level `UNIQUE`
constraint is the backstop either way, so this is not a correctness hole. It is
worth keeping in view for WP-1b, where the arrival coordinate provider replaces
this allocator anyway. Not a finding against WP-1a.

## Bottom line

**WP-1a PASSES the gate.** The blocking regression is fixed without weakening a
single assertion, the five minor findings are genuinely addressed rather than
papered over, and one of them (F-6) turned out to close a real refusal hole. The
implementation is ready to proceed to WP-1b.
