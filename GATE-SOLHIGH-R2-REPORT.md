# GATE REPORT — sol-HIGH r2 remediation (findings 06 / 07 / 08)

Independent gate. Target `f4a5e7df` on `slice/D-solhigh-r2` (fix `a925c697`),
merge-base `7c248673`. Branch `slice/D-solhigh-r2-gate`.

## VERDICT: **PASS** — all three findings closed, no blocking findings.

One observation recorded; it does not block.

---

## 1. Scope and suites

In-fence: `sqlite_store.py`, `arrival_store.py`, `test_arrival_coordinate_d0.py`,
report. Nothing else.

| Suite | Baseline (r1 final) | HEAD | Delta |
|---|---|---|---|
| atoms | 517 | 517 | 0 |
| **engine** | **1900 + 1 skip** | **1906 passed, 1 skipped** | **+6** |
| sdk | 324 | 324 | 0 |
| lang | 655 | 655 | 0 |
| store | 176 | 176 | 0 |
| arch | 98 | 98 | 0 |
| apps/loops | 2530 + 1 xfail | 2530 + 1 xfail | 0 |

`test_arrival_coordinate_d0.py` collects **40** (34 at the end of r1) — +6, and it
is the only test file touched, so the engine delta is fully accounted for. The fix
report's table matches mine on every figure.

## 2. SOL-HIGH-06 — the fast path now mode-matches, and the correction cannot be reached with rows

**A fresh `ArrivalStore` stamps `'arrival'`.** Minted a log, opened a store,
appended a fact:

```
marker = ('arrival',)
```

**The fresh-empty correction rule — I tried to reach it with rows present.** The
precondition is `all(COUNT(*) == 0 for t in existing_tables)`, and `existing_tables`
is both tables when both exist. Driven across the row-population matrix with a
marker (`'arrival'`) deliberately mismatching the requested mode (`'mirrored'`):

| rows | outcome |
|---|---|
| facts=0, ticks=0 | **corrected** to `'mirrored'` — the permitted fresh case |
| facts=2, ticks=0 | **REFUSED** — *"marker 'arrival' disagrees with requested mode 'mirrored' on non-empty store"* |
| **facts=0, ticks=2** | **REFUSED** | 
| facts=1, ticks=1 | **REFUSED** |

The third row is the discriminating one: a `facts`-only emptiness check would have
silently corrected the marker on a store holding tick rows. It refuses. **Both
tables are checked, and the correction is unreachable with any row present.**

## 3. SOL-HIGH-07 — an empty arrival index consults the provider

Reproduction: build a 3-fact arrival store, then delete the index rows while
retaining the arrival mark and dropping the `coordinate_axis` marker — an empty,
unmarked index over a populated log.

```
index rows 3 -> 0, arrival mark retained
REFUSED: index content does not match arrival log coordinates
         (facts has 0 rows, log has 3) — run …rederive_projections
```

Refused with a counted location claim naming both sides, pointed at the repair
path. Empty no longer means "nothing to disagree with".

## 4. SOL-HIGH-08 — the empty legacy arrival index opens, migrates and appends

Reproduction: mint an arrival log, hand-seed an **empty legacy** index (no
coordinate columns, zero rows), open it through the public `ArrivalStore`
constructor:

```
opened+migrated; marker = ('arrival',)
coordinate columns present: True
append landed: [('01M0P9V0X67R3JKXS3BPHY2JJG', 1, 0)]
```

Opens, migrates, stamps the right axis, and the subsequent append lands at a
correct coordinate.

## 5. Mutation proof 07 — re-run independently, and it took two attempts

**First attempt (reported for the record, not as the proof).** I re-introduced the
deleted early-return block verbatim. Two tests failed — but with a **`TypeError` at
`sqlite_store.py:584`**, because the deleted block contained
`_rebuild_table(conn, t, "arrival", validate=False)`: a positional `"arrival"`
against a signature whose `is_final` and `mode` are keyword-only. So the failures
came from a crash, not from the provider bypass, and the proof did not isolate what
it claimed to.

That misfire is itself informative: **the deleted block could never have run** —
it would have raised `TypeError` on every reach. That is finding 08's substance,
independently corroborated: the empty-arrival path was dead on arrival and no
fixture exercised it.

**Isolated attempt (the actual proof).** Re-introduced the bypass with a *correct*
keyword call, so the only behavioural change is skipping the provider:

```
1 failed, 1905 passed, 1 skipped
FAILED …TestSolHigh07EmptyIndexConsultsProvider::test_empty_index_with_populated_log_refuses_rederive
```

Restored: 1906 passed. Exactly one test, and the 08 fixture **passes** under this
mutation — so 07 and 08 are pinned by different tests rather than one masking the
other.

## Observation (not a finding) — `_meta_get` now swallows every `OperationalError`

The fix reorders `_ensure_meta_table()` ahead of `_ensure_coordinate_schema()` in
`ArrivalStore.__init__` (correct — the marker read needs the table) and, separately,
wraps `_meta_get`'s SELECT in:

```python
except sqlite3.OperationalError:
    return None
```

That catch is broader than the case that motivated it. `OperationalError` covers a
locked database and several corruption modes as well as "no such table", so a
transiently locked store now reads as *"this key has no value"* rather than
raising — and the values read through `_meta_get` are markers like the lineage and
the coordinate axis, where "absent" is a meaningful and consequential answer.

Non-blocking, and the reordering makes the missing-table case largely moot anyway
— which is the argument for narrowing the catch rather than keeping it: matching
on `"no such table"` would preserve the intent without silencing lock and
corruption errors on a marker read.

## Bottom line

All three findings are closed against fixtures I built rather than replayed. The
06 correction rule holds under a deliberate attempt to reach it with rows present,
including the `facts`-empty/`ticks`-populated case that a single-table check would
have let through. 07 refuses with a counted claim, and 08's public-constructor path
works end to end.

The mutation proof is worth reading twice: my first pass conflated the two findings
because the code I re-introduced crashed before it could bypass anything — which
incidentally confirmed that the block finding 08 removed had never been executable.
The isolated re-run pins 07 alone.

**PASS.** Ready to merge, and for sol-HIGH r3 to make the convergence call.
