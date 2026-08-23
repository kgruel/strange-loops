# GATE REPORT — sol-HIGH r5 remediation (SOL-HIGH-11, deep-audit coordinate comparison)

Independent gate. Target `8629c98e` on `slice/D-solhigh-r5` (fix `11ec5c31`),
merge-base `55fb4e21`. Branch `slice/D-solhigh-r5-gate`.

## VERDICT: **PASS** — SOL-HIGH-11 closed. No findings.

---

## 1. Scope and suites

In-fence: `canonical_audit.py` (+20/−4), `test_audit_rebase_d3.py`, report.

| Suite | Baseline (`55fb4e21`) | HEAD | Delta |
|---|---|---|---|
| **engine** | **1911 + 1 skip** | **1913 passed, 1 skipped** | **+2** |
| store | 176 | 176 | 0 |
| apps/loops | 2530 + 1 xfail | 2530 + 1 xfail | 0 |

`test_audit_rebase_d3.py` collects **18** (16 at base) — +2, the only test file
touched. Matches the claimed figure.

*Reconciliation note:* I first computed +3 by differencing against r3's 1910.
The merge-base here is `55fb4e21`, which carries an extra test from the r4/r5
brief work, so the true baseline is **1911** and the delta is **+2**. Measuring
the actual merge-base resolved it — the same class of error I made once before in
this arc, and the reason I measure rather than inherit.

## 2. The fix, read

`_index_cursor_arrival` now selects the coordinate columns alongside the content
columns — through `_present`, so a pre-coordinate index still works — and the
row-by-row loop gains `enumerate(records)` to carry the 0-based expansion `seq`.
The comparison splits cleanly:

- content: `tuple(stored[:arity]) != _trim(row, arity)` (unchanged semantics,
  now slicing because the row is wider);
- coordinate: `(stored[arity], stored[arity + 1]) != (ordinal, seq)`, guarded by
  `len(stored) >= arity + 2`.

The coordinates ride the **existing** cursor SELECT, so the comparison reads no
additional records — the property §3 confirms.

## 3. The 1 + N bound is untouched

Instrumented at both seams on a 20-fact store (N = 21 records):

```
anchor=1  walk=21  total=22  == 1+N (22)? True
```

The coordinate comparison adds zero record reads.

## 4. Sol's reproduction — deep refuses, L1 stays green

A batch at ordinal 2 (seq 0/1/2); the middle row's stored coordinate rewritten
from its true `(2,1)` to `(1,1)`:

```
L1   ok=True    <- correctly still green
deep ok=False
  [content] log record at ordinal 2 (fact …DD) disagrees with index fact …DE
            at the same position — the index rows are out of log order
```

**Both directions of the L1/deep boundary are pinned**: the tamper is below the
mark and L1's checks legitimately cannot see it, while deep refuses.

**A precision point worth stating.** This particular tamper is caught by the
*content* check, not the new coordinate check — moving a row's coordinate also
moves it in the cursor's `ORDER BY arrival_ordinal, arrival_seq`, so the
positional content comparison trips first. To exercise the new check in isolation
I used an **order-preserving** tamper (shift every coordinate by +10, leaving
content and relative order intact):

```
[content] log record at ordinal 1 (fact …EF) coordinate (1, 0)
          disagrees with index coordinate (11, 0); …
```

That is the claim format the fix promises — row id, log coordinate, stored
coordinate. (On that fixture L1 also goes red, via `rewound`, which is correct:
coordinates shifted past the consumed ordinal are exactly what that check is for.
So the two properties are demonstrated by two fixtures rather than one, and I am
reporting them separately rather than conflating them.)

## 5. My own variant — ticks are genuinely covered

The fix claims facts *and* ticks. I built the tick case myself: a properly
appended tick (via `append_tick`, so the chain is valid), rederived, then shifted
the tick's coordinate by +7:

```
[content] log record at ordinal 3 (tick …KQ) coordinate (3, 0)
          disagrees with index coordinate (10, 0)
```

Caught, with the same claim shape. The ticks half is real, not aspirational.

## 6. Mutation proof — re-run independently

I removed the coordinate-comparison branch outright:

```
2 failed, 1911 passed, 1 skipped
  …test_sol_high_11_deep_audit_detects_interior_coordinate_tamper_below_mark
  …test_sol_high_11_deep_audit_detects_tick_coordinate_tamper_below_mark
```

Restored: 1913 passed. Two tests, and **one of them is the tick case** — so the
facts and ticks halves are pinned by separate tests rather than one standing in
for both.

## Bottom line

SOL-HIGH-11 is closed. The deep audit now carries each expected row's true
coordinate from the log walk and compares it against what the index stored, for
facts and ticks alike, with a location claim that names the row and both
coordinates. It costs nothing on the bound — the coordinates ride the cursor that
was already being read, and 1 + N still holds exactly.

The one thing I would flag for the record is not a defect but a reading caution:
sol's reproduction is caught by the *content* check rather than the new one,
because a coordinate tamper usually perturbs cursor order too. The new check earns
its keep on the order-preserving case — which is the harder one, and which nothing
before it could see.

**PASS.** Ready to merge, and for sol r6 to make the convergence call.
