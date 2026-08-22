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

---
---

# ROUND 3 — full gate of WP-1b (arrival-canonical migration mode)

New work package, full protocol. Commits `ac7ac6a0` (implementation) +
`b07d5a03` (report), on top of the WP-1a tip `e81de220` this gate passed in
Round 2. Gate branch rebased onto `b07d5a03`.

## ROUND 3 VERDICT: **BLOCKING** — one finding (G-1).

All seven suites are green, the gate coverage is real, and the mechanism matches
the proposal on every point I was asked to check. The block is a **reachable
circular refusal**: WP-1b wires the provider-mismatch check into
`rederive_projections` itself, so on a divergent legacy index the designated
repair path refuses with the instruction "run `rederive_projections`". I
demonstrated it end-to-end; it is not hypothetical, and no test covers it.

## Suite reconciliation — all seven measured by this gate at `b07d5a03`

| Suite | Round 2 (`e81de220`) | Round 3 (`b07d5a03`) | Delta | Status |
|---|---|---|---|---|
| atoms | 517 | **517 passed** | 0 | OK |
| engine | 1822 + 1 skip | **1830 passed, 1 skipped** | **+8** | OK — exact, see below |
| sdk | 324 | **324 passed** | 0 | OK |
| lang | 655 | **655 passed** | 0 | OK |
| store | 157 | **157 passed** | 0 | OK |
| arch | 98 | **98 passed** | 0 | OK |
| apps/loops | 2525 + 1 xfail | **2525 passed, 1 xfailed** | 0 | OK — WP-1a fix holds |

**Engine +8 reconciles exactly.** `test_arrival_coordinate_d0.py` grew from 12 to
**20 collected** tests: G-D0-3, G-D0-7, G-D0-8, G-D0-12, and four
provider-mismatch/validation tests. 1822 + 8 = 1830. No existing test dropped.

**On the F-2 history — the reporting problem is corrected.** I checked
`WP1B-REPORT.md`'s suite table against my own numbers specifically because Round 1
found the WP-1a report concealing a red suite. This time all seven suites are
listed, `apps/loops` included, and **every figure matches mine exactly**
(engine 1830+1skip, apps/loops 2525+1xfail, lang 655, atoms 517, sdk 324,
store 157, arch 98). The claims are complete and truthful. Credit where due.

## Scope — clean

`git diff --stat e81de220..b07d5a03` touches only the three fenced engine sources
(`sqlite_store.py`, `arrival_store.py`, `arrival_projection.py`),
`libs/engine/tests/test_arrival_coordinate_d0.py`, and `WP1B-REPORT.md`. Nothing
outside the fence. Working tree clean; the only ignored entries (`.hypothesis/`,
`uv.lock`) are pre-existing and untracked, not cruft from this commit.

## Design conformance — every requested point verified in the code

**Composite `(table, row_id)` staging join — YES.** `_coordinate_staging` is
declared `PRIMARY KEY (table_name, row_id)`, and both rebuild INSERTs join on the
composite key (`ON s.table_name = 'facts' AND s.row_id = f.id`, and the `'ticks'`
analogue). **Proven load-bearing** by break/restore below.

**Mismatch refusal fires in BOTH directions — YES.** Three independent checks per
table: row-count disagreement; an index row with no log coordinate
(`missing_in_staging`); and a log coordinate with no index row
(`missing_in_index`). Plus coordinate-duplication (a `GROUP BY … HAVING COUNT(*)>1`
check *and* the staging primary key catching duplicate identities), invalid table
names, and malformed tuples. `TestProviderMismatchRefusal` covers fewer / more /
differing-id, all asserting `match="rederive_projections"`.

**ArrivalStore invokes the upgrader before its `_ensure_*` tail — YES.**
`__init__` assigns `self._log`, then sets `_coordinate_mode = "arrival"` and the
`_provider` closure (which walks `self._log` via `rows_of_record`, bounded by the
stamped resume mark), then calls `self._ensure_coordinate_schema()` **ahead of**
`_ensure_fact_signature_column` / `_ensure_chain_columns` / `_ensure_meta_table`.
Correct order, provider closed over the log after assignment.

**WP-1a rebuild machinery REUSED, not duplicated — YES.** `_rebuild_table_mirrored`
was renamed `_rebuild_table` and takes `mode`; the view dependency-closure,
trigger inventory, index inventory, drop/rename and replay steps are **one shared
body**. Only the single staging INSERT branches on mode. The WP-1a-era
`ArrivalStore._ensure_coordinate_schema` no-op override was correctly *deleted*
so the base implementation now drives both modes — dissolution residue swept.

**Mode argument validation tightened correctly:** `mirrored` + a provider →
`ValueError`; `arrival` without a provider → `ValueError`; unknown mode →
`ValueError`. The WP-1a lineage refusal is now correctly scoped to
`mode == "mirrored"` only, so arrival mode may legitimately operate on an
arrival-marked store. `TestMisModeRefusal` still passes.

## G-D0-3 genuinely discriminates `ordinal = rowid`

I was asked to confirm the fixture actually expands a batch. It does, and it is
the sharpest test in the file. The log carries ordinal 1 = one fact, **ordinal 2 =
a batch of three facts**, ordinal 3 = a tick. The assertions:

```python
assert fact_rows[1] == (2, "f-002-a", 2, 0)
assert fact_rows[2] == (3, "f-002-b", 2, 1)   # rowid 3, ordinal 2
assert fact_rows[3] == (4, "f-002-c", 2, 2)   # rowid 4, ordinal 2
```

Rowids run 2, 3, 4 while ordinals are 2, 2, 2 with seq 0, 1, 2. A rowid backfill
would produce `(3, …, 3, 0)` and fail on the very next line. **The test cannot
pass under `ordinal = rowid`.** It also verifies the post-migration catch-up
append lands at `(5, new_fid, 4, 0)` — a new ordinal, colliding with nothing.

## Independent break/restore — G-D0-12 (cross-table id collision)

I removed the table predicate from **both** staging joins, reducing the composite
key to `row_id` alone:

- before break: 1 passed
- after break: **FAILED** — `sqlite3.IntegrityError: UNIQUE constraint failed:
  facts_new.rowid` (a fact and a tick sharing an id fan the join out to two rows)
- after `git restore`: **20 passed** (full D0 file)

The composite key is genuinely load-bearing, and the test discriminates it.

---

## FINDING G-1 — BLOCKING — `rederive_projections` refuses with instructions to run `rederive_projections`

**What.** `rederive_projections` calls `_ensure_index_schema(conn, log)` at
`arrival_projection.py:480`, **before** the `DELETE FROM facts` / `DELETE FROM
ticks` at lines 493-494. WP-1b made `_ensure_index_schema` delegate to
`ensure_coordinate_schema(mode="arrival")`, whose provider/index agreement check
therefore runs against the **stale, pre-delete** index content. When that content
disagrees with the log — the exact condition rederivation exists to repair — the
migration raises `ArrivalCanonicalUnsupported` whose remedy text is *"run
engine.arrival_projection.rederive_projections to rebuild the index from the
log"*. We are already inside that function. The repair path cannot repair.

**Evidence — reproduced end-to-end, two reachable cases.** Both build a legacy
(no-coordinate) arrival index on disk and call the public
`rederive_projections(log_path)`:

| Case | Result |
|---|---|
| Healthy legacy index, ordinal mark present | SUCCEEDS (`records=4, facts=3`) |
| **Legacy index with a forged out-of-band row** | **REFUSED** — `index content does not match arrival log coordinates (facts has 4 rows, log has 3) — run engine.arrival_projection.rederive_projections …` |
| **Legacy index, rows present, `ARRIVAL_ORDINAL_KEY` meta absent** | **REFUSED** — `(facts has 3 rows, log has 0) — run engine.arrival_projection.rederive_projections …` |

The second case is broader than it looks: `_ensure_index_schema`'s `_provider`
returns immediately when the stamped ordinal mark is missing (`if mark_ord is
None: return`), yielding **zero** coordinates, so *any* legacy index with rows but
no ordinal mark refuses on the count check.

**Why the suite is green anyway.** G-D0-8 exercises rederivation only on an index
that already agrees with its log. No test drives rederivation on a **divergent**
legacy index. The gap is in coverage, not just in code.

**Is it a regression? — measured across all three commits, not inferred.** I ran
the identical probe at each tip. The precise answer is *"a regression against
pre-slice-D, and an unclosed assignment against WP-1a"*:

| Commit | Healthy legacy index | Divergent legacy index |
|---|---|---|
| `560710b8` pre-slice-D | SUCCEEDS (`facts=3`) | **SUCCEEDS — repairs it**, forged row purged, `facts=3` |
| `e81de220` WP-1a tip | `OperationalError: table facts has no column named arrival_ordinal` | same error |
| `b07d5a03` WP-1b | SUCCEEDS | **REFUSED (circular)** |

Read across the row, the story is exact. **Pre-slice-D, rederivation did exactly
its job**: handed a legacy index carrying a forged out-of-band row, it rebuilt
from the log and dropped the forgery. **WP-1a broke the route outright** for
*every* legacy arrival index — its rederivation inserts began supplying
coordinates via `FACT_INSERT_SQL` while `_ensure_index_schema` still could not add
those columns, so both cases died on a missing column. That latent breakage was
never caught because no test drives rederivation on a legacy index.

**WP-1b's assignment was to close precisely that gap** — the
`arrival_projection._ensure_index_schema` delegation is named in it. It closed
the healthy half and left the divergent half broken, converting a loud
`OperationalError` into a quiet circular refusal. So G-1 is not "WP-1b broke a
working path"; it is **"WP-1b half-fixed the path it was assigned to fix, and the
unfixed half is the one that matters"** — the divergent index is the only kind
that needs repairing at all. Against the pre-slice-D behaviour above, the
capability loss is real and measured.

**Exact fix required — and why the obvious two do not work.** I checked both
before recommending:

- *"Just delete the rows first, then migrate"* — does **not** work. The provider
  walks the log and would still yield N coordinates against an emptied index, so
  the count check fails in the other direction.
- *"Skip the migration in the rederive path"* — does **not** work either. I
  verified that `_SCHEMA_STMTS` is `CREATE TABLE IF NOT EXISTS` and so cannot add
  columns to an existing legacy table (probe: columns remain
  `id…signature`, no `arrival_ordinal`). A NOT NULL column addition genuinely
  requires the table rebuild. Rederivation's own `FACT_INSERT_SQL` needs those
  columns to exist.

The correct shape is a **schema-only rebuild for the rederivation route**: add the
coordinate columns via the existing `_rebuild_table` machinery with placeholder
coordinates and **no provider-agreement validation**, stamping
`coordinate_axis = 'arrival'`. This is sound precisely because rederivation
deletes every row microseconds later and reinserts each one with authoritative
`(ord, seq)` from the log walk — validating the doomed content is not merely
unnecessary, it is the thing preventing the repair. Concretely: give
`ensure_coordinate_schema` a way to add the axis without asserting agreement (a
third internal path, or a `validate=False` flag honoured only by
`_ensure_index_schema`), and keep the strict validating path for
`ArrivalStore.__init__`, where refusing *is* the right answer because that route
has no authority to rewrite content.

**Also add the missing test**: rederivation over a divergent legacy index must
succeed and produce log-faithful coordinates. That is the gate G-D0-8 should have
had.

---

## Round 3 disclosure

The Round 1 first-run engine anomaly did not recur. I ran the full engine suite
twice more this round with no instability. Nothing else in WP-1b was unverifiable.

## Standing notes (non-blocking, carried forward)

- **Staging temp table cleanup is asymmetric.** `_coordinate_staging` is dropped
  in the `finally` of the rebuild block, but every provider-mismatch refusal
  raises *before* that block is entered, leaving the temp table on the connection.
  Harmless in practice — it is a `TEMP` table that dies with the connection, and
  each arrival call begins with `DELETE FROM _coordinate_staging` — but the
  cleanup would read more honestly wrapped around the whole arrival section.
- The WP-1a legacy-allocator concurrency note still stands unchanged for the
  mirrored path; arrival mode takes coordinates from the log and is unaffected.

## Bottom line

WP-1b's mechanism is correct and its tests are real: the composite key, the
bidirectional mismatch refusal, the batch-expansion discrimination and the
machinery reuse all hold up under direct attack, and the report's numbers are
honest this time. One wiring decision — validating provider agreement inside the
repair path — turns a good safety check into a deadlock on exactly the indices
that need repairing. Fix G-1 and add the divergent-rederivation test, and this
package passes.

---
---

# ROUND 4 — re-gate of the G-1 fix (`8a5fbe35` + `1aa1f7af`)

Scoped to G-1 only, as instructed. Gate branch rebased onto `1aa1f7af`.

## ROUND 4 VERDICT: **PASS** — G-1 cleared. WP-1 is complete.

Two minor residue notes and one reporting note below; none blocking.

## G-1 — CLEARED, verified with my own Round 3 probes

I re-ran the exact probes that produced the circular refusal, plus the two
controls. All through the **public** `rederive_projections`:

| Case | Round 3 | Round 4 | Forgery purged | Axis |
|---|---|---|---|---|
| Healthy legacy index | SUCCEEDED | **SUCCEEDS** (`facts=3`) | n/a | `arrival` |
| **Divergent legacy (forged row)** | **REFUSED (circular)** | **SUCCEEDS** (`facts=3`) | **yes** | `arrival` |
| **Legacy, rows, no ordinal mark** | **REFUSED (circular)** | **SUCCEEDS** (`facts=3`) | n/a | `arrival` |
| `ArrivalStore.__init__` on divergent fixture | REFUSED | **REFUSED** (strict path intact) | — | — |

The deadlock is broken in both directions that mattered, and the strict route
still refuses — so the refusal design is preserved where refusing is correct, and
its remedy text now names a function that actually works.

**Coordinates are log-faithful, not placeholders — proven with a batch.** The
`validate=False` rebuild backfills `arrival_ordinal = rowid, arrival_seq = 0`, so
a test using only single-record facts could not distinguish "log-faithful" from
"placeholder left behind". I built the discriminating fixture: a legacy index
seeded **scrambled** (rows out of log order), carrying a forged row, against a log
whose ordinal 2 is a **batch of three**. After rederivation:

```
(1, 'f-001',   1, 0)
(2, 'f-002-a', 2, 0)
(3, 'f-002-b', 2, 1)    <- rowid 3, ordinal 2
(4, 'f-002-c', 2, 2)    <- rowid 4, ordinal 2
```

A surviving placeholder backfill would read `(1,0),(2,0),(3,0),(4,0)`. It does
not: the batch shares ordinal 2 with seq 0/1/2, and `01FORGED` is gone. The
placeholders are genuinely overwritten by rederivation's own log-driven inserts.

## The fix's shape is exactly right — machinery shared, not duplicated

`validate=False` gates **only two things**: the `_coordinate_staging` creation +
provider-agreement block (`if mode == "arrival" and validate:`) and the choice of
INSERT. Everything else in `_rebuild_table` is one shared body. Better still, the
non-validating INSERT **reuses the existing mirrored placeholder SQL** rather than
adding a third statement (`if mode == "mirrored" or not validate:`), so the fix
adds no duplicated SQL at all. The `_provider` closure in `_ensure_index_schema`
was deleted outright rather than left dead.

**Verified empirically, not just by reading the diff.** I ran the
`validate=False` path against a legacy table carrying two stacked views, an AFTER
INSERT trigger, an INSTEAD OF trigger on a view, and two indexes:

- **rowids preserved** — `[(1,'f0'),(2,'f1'),(3,'f2')]` unchanged
- **dependency-closed views survived** — `v1_facts` *and* `v2_notes` (the
  view-over-view) both present and queryable
- **both triggers survived** — `trg_after` and `trg_io`; the AFTER INSERT trigger
  still fires on a subsequent insert
- **indexes recreated** — `idx_facts_kind`, `idx_facts_ts`
- **marker stamps `'arrival'`**, not `'mirrored'` — the correct axis, which a
  lazier fix (just calling mirrored mode) would have got wrong

So the non-validating path is the *same* migration, minus only the agreement
assertion. That is precisely the requirement.

## Their break/restore evidence is genuine

`WP1B-FIX-REPORT.md` shows the two new tests **failing** against the pre-fix code
with `ArrivalCanonicalUnsupported` at `sqlite_store.py:524` (`2 failed, 1 passed`)
and passing after — including the honest red output rather than only the green.
My independent probes reach the same conclusion by a different route.

## Suite reconciliation

| Suite | Round 3 | Round 4 (`1aa1f7af`) | Status |
|---|---|---|---|
| atoms | 517 | **517 passed** | OK |
| engine | 1830 + 1 skip | **1833 passed, 1 skipped** | OK — **+3, exact** |
| sdk | 324 | **324 passed** | OK |
| lang | 655 | **655 passed** | OK |
| store | 157 | **157 passed** | OK |
| arch | 98 | **98 passed** | OK |
| apps/loops | 2525 + 1 xfail | **2525 passed, 1 xfailed** | OK |

Engine's +3 reconciles exactly: `test_arrival_coordinate_d0.py` collects **23**
(was 20), the three added being `TestDivergentLegacyRederivation` — divergent
rederivation succeeds, no-ordinal-mark rederivation succeeds, and
`ArrivalStore.__init__` on the divergent fixture still refuses. That last one is
the right test to have written: it pins the strict path so a future loosening of
`validate` cannot silently disarm it.

Scope in-fence (`arrival_projection.py`, `sqlite_store.py`, the D0 test file, the
fix report). Working tree clean.

## Minor notes — none blocking

**R4-1 (minor) — unswept residue: `_ensure_index_schema`'s `log` parameter is now
dead.** Deleting the `_provider` closure left the signature
`_ensure_index_schema(conn, log: ArrivalLog | None = None)` with `log` appearing
**only in the signature** — the body no longer references it — while
`rederive_projections:480` still passes it. Per the project's own rule that
dissolution isn't done until its residue is swept, drop the parameter and the
argument in the same change.

**R4-2 (minor) — unused import.** `from typing import Iterator, NoReturn` in
`arrival_projection.py`: `Iterator` was imported for the deleted closure and is
now unreferenced.

**R4-3 (reporting, minor) — the fix report's suite section covers six of seven
suites; `libs/lang` is absent.** I want to be precise about severity given the
F-2 history: this is **not** a repeat of F-2. F-2 concealed a suite that was
**red**. Here the omitted suite is untouched by the fix and I verified it green
myself (655 passed). This is incompleteness, not concealment — worth naming only
because the earlier round makes suite-table completeness a standing expectation.
Every figure the report *does* state matches mine exactly.

**Standing note check (as asked): the staging temp-table cleanup asymmetry is
unchanged.** The cleanup is still `finally: if mode == "arrival" and validate:
DROP TABLE IF EXISTS _coordinate_staging`, and provider-mismatch refusals still
raise before that block is entered, so the temp table still outlives a refusal.
The fix neither improved nor worsened it. Still harmless for the same reasons
(TEMP table, dies with the connection, each call re-`DELETE`s it), still worth
tidying opportunistically. Not a finding.

## Bottom line

**G-1 is cleared and WP-1 is complete.** The fix is the minimal correct one: it
adds a single flag that suppresses only the agreement assertion, reuses the
existing rebuild machinery and even the existing placeholder SQL, keeps the strict
route strict, and stamps the right axis. I confirmed by direct probe that the
repaired path produces log-faithful coordinates — batch expansion and all — on a
scrambled, forged, legacy index, which is the case that started this finding.
Clear R4-1 and R4-2 as housekeeping whenever convenient; neither affects behaviour.
WP-1 is ready for the codex pass check.

---
---

# ROUND 5 — re-gate of the SOL-WP1-01 fix (`ac8b61fa` + `3f9fa7fb`)

The codex sol-low pass found a defect my Rounds 1-4 did not: `ensure_coordinate_schema`'s
migrated-detection was shallow — a bare marker returned immediately with no
structural inspection, and the markerless path accepted mere `arrival_ordinal`
column presence, never checking `arrival_seq`, NOT NULL on both, or UNIQUE. It is
the deeper version of my F-6. **Credit to the codex pass: my F-6 fixed the
*ordering* of the marker check and I did not go on to ask whether the marker was
*trustworthy*. That was a real gap in my Round 2 review.**

Scoped to the arbiter-ruled fix. Gate branch rebased onto `3f9fa7fb`.

## ROUND 5 VERDICT: **PASS** — SOL-WP1-01 cleared.

One coverage finding (R5-1) that does not affect current behaviour but should be
closed before the sol re-verdict, plus two carry-forwards.

## SOL-WP1-01 cleared — all four ruled behaviours verified independently

Scope in-fence (`sqlite_store.py` + `test_arrival_coordinate_d0.py` only).

**1. The verifier is genuinely deep.** I drove `_verify_coordinate_schema`
across every defect dimension the finding named, each returning a precise
location claim rather than a bare verdict:

| Table shape | Result |
|---|---|
| no coordinate columns | `facts lacks arrival_ordinal column` |
| **`arrival_ordinal` only — the old shallow pass** | **`facts lacks arrival_seq column`** |
| both columns, `arrival_ordinal` nullable | `facts lacks NOT NULL on arrival_ordinal` |
| both columns, `arrival_seq` nullable | `facts lacks NOT NULL on arrival_seq` |
| both NOT NULL, no UNIQUE | `facts lacks UNIQUE (arrival_ordinal, arrival_seq) constraint` |
| complete (control) | `(True, None)` |

The second row *is* SOL-WP1-01, demonstrated closed. A fresh store built from
`_SCHEMA_STMTS` passes cleanly, so the stricter verifier raises no false refusal
on new stores.

**2. Marker present + incomplete → loud refusal, store provably unmodified.**
`ArrivalCanonicalUnsupported` naming table and defect plus "out-of-band
interference", with **no auto-rebuild**. I checked "unmodified" at the strongest
level available rather than trusting the absence of DDL: after the refusal the
**file's SHA-256 is byte-identical**, and so are the full `sqlite_schema` listing
(names, rootpages, SQL) and every row. Evidence preserved exactly as ruled.

**3. Marker absent + failing table → rebuild, idempotent.** A foreign partial
schema (nullable `arrival_ordinal`, no `arrival_seq`, no UNIQUE) is now detected
as unmigrated and rebuilt; the verifier passes afterwards and `coordinate_axis`
is stamped. Rebuild confirmed by `sqlite_schema.rootpage` changing.

**4. Marker present + complete → genuinely cheap fast path.** The team asked
whether the fast path is actually cheap rather than a rebuild per open. It is:
three PRAGMAs per table (`table_info`, `index_list`, `index_info`) and return,
before any transaction. Confirmed empirically — after the call the **rootpages
are unchanged and the file is byte-identical**, so no table was recreated. (It is
also invoked once per handle, behind `self._coordinate_ready`.)

**F-6 ordering preserved.** The `ARRIVAL_LINEAGE_KEY` mis-mode check remains in
the first `meta_table_exists` block; the axis-marker check moved to a second block
after `existing_tables` is computed. On a store carrying **both** an arrival
lineage marker and `coordinate_axis`, the refusal that fires is still the
**lineage** one ("cannot apply mirrored coordinate schema to arrival-canonical
index"), not the structural one. My Round 2 ordering survived the rewrite.

## Independent break/restore

I re-introduced the exact defect, truncating `_verify_coordinate_schema` to bare
`arrival_ordinal` presence:

- before: `TestSolWp101StructuralVerification` 3 passed
- after: **FAILED** — `test_foreign_partial_schema_no_marker_rebuilt_correctly`
  with `sqlite3.OperationalError: table facts has no column named arrival_seq`,
  the precise downstream consequence of shallow detection
- after `git restore`: 26 passed

## Suite reconciliation

| Suite | Round 4 | Round 5 (`3f9fa7fb`) | Status |
|---|---|---|---|
| atoms | 517 | **517 passed** | OK |
| engine | 1833 + 1 skip | **1836 passed, 1 skipped** | OK — **+3, exact** |
| sdk | 324 | **324 passed** | OK |
| lang | 655 | **655 passed** | OK |
| store | 157 | **157 passed** | OK |
| arch | 98 | **98 passed** | OK |
| apps/loops | 2525 + 1 xfail | **2525 passed, 1 xfailed** | OK |

Engine's +3 reconciles exactly: the D0 file collects **26** (was 23), the three
additions being `TestSolWp101StructuralVerification`. Working tree clean.

---

## R5-1 — the refusal test under-covers the finding it was written for (non-blocking, but close it before the sol re-verdict)

**The production behaviour is correct** — I verified all five defect dimensions
above. This is purely about what the net would catch tomorrow.

`test_marker_present_structure_incomplete_refuses_loudly` builds its fixture with
`_create_legacy_db`, a table carrying **no coordinate columns at all**, and
asserts `"facts lacks arrival_ordinal column"`. So the marker-present refusal is
pinned only for the *shallowest* defect — the one case the old shallow code
already handled. The deeper dimensions SOL-WP1-01 was actually about (`arrival_seq`
absent while `arrival_ordinal` present, NOT NULL missing, UNIQUE missing) are not
exercised on the refusal path at all.

**Proven, not asserted.** I re-introduced SOL-WP1-01 on the marker-present path
only (reducing it to column presence) and ran the whole D0 file:

```
=== FULL D0 SUITE with the deep refusal broken ===
26 passed
=== probe against the same build ===
marked + STRUCTURALLY INCOMPLETE -> ACCEPTED SILENTLY
```

**All 26 tests stay green while the finding is regressed.** That is the definition
of an invariant living in review vigilance rather than in the suite — and this is
the second shallow-check incident in this work package, the first having survived
my own review.

**Fix:** parametrize the marked-but-incomplete refusal over the defect matrix in
the table above (nullable ordinal, nullable seq, missing seq, missing UNIQUE),
asserting the specific defect string each time and the unmodified-store property
at least once. Cheap, and it converts the ruling into a ratchet.

## Carry-forwards, still open (both out of this fence)

- **R4-1** — `_ensure_index_schema`'s `log` parameter remains dead: it appears
  only in the signature while `rederive_projections:480` still passes it.
- **R4-2** — `Iterator` remains imported but unreferenced in
  `arrival_projection.py`.

- **R5-2 (recurrence of R4-3)** — `WP1-SOL-FIX-REPORT.md`'s suite table again
  lists **six of seven** suites, omitting `libs/lang`. Same shape as Round 4 and
  the same low severity: lang is untouched and I verified it green (655), so this
  is incompleteness rather than concealment. Worth naming only because it has now
  happened twice; a seven-row table should be the standing template.

## Bottom line

**SOL-WP1-01 is cleared and the fix matches the arbiter's ruling point for
point** — deep structural verification on both paths, rebuild when unmarked,
loud non-destructive refusal when marked, F-6 ordering intact, and a fast path
that really is three PRAGMAs rather than a rebuild. I confirmed the
non-destructive property by byte-comparing the database file, and the fast path
the same way.

The one thing I would not ship silently is R5-1: the new refusal test would stay
green through a regression of the very defect it was written to prevent, and I
demonstrated that. It does not change today's behaviour, so it does not block the
verdict — but it should be closed before the sol re-verdict, so the next round of
this does not depend on someone re-running my probes by hand.
