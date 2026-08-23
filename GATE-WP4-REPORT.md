# GATE REPORT — WP-4 (audit re-base, D3)

Independent gate. Target `6ac0ae23` on `slice/D-wp4` (`15a9c65b` engine +
`c63509ba` dispatch arm), merge-base `e8a9b033`. Branch `slice/D-wp4-gate`.
Implementer: flash-high.

## VERDICT: **BLOCKING** — one finding (W4-1).

Everything else in the contract holds, and most of it holds well. The block is
the arc's own audit invariant: **L1 does unbounded work on a reachable path, and
G-D3-2 is structurally blind to it.** I found it by taking up the invitation to
try to evade the instrumentation, and it reproduces in nine lines.

---

## FINDING W4-1 — BLOCKING — L1 walks the whole log from zero when anchor validation fails, and the bounds instrumentation cannot see it

**The module states the invariant itself** (`canonical_audit.py:32`):

> L1 MUST NOT call `ArrivalLog.read` or `ArrivalLog.walk` (both walk from zero).

`_check_consumed_arrival` — reached from `audit_agreement` → `_audit_agreement_arrival:346`,
squarely L1 — calls **`log.walk_marked(None)`** in two branches (`:394`, `:396`).
`walk_marked(None)` resolves `_anchor_for(None) → None` and therefore runs
`_walk_marked_from_zero()` → `_verify_from(fh, expected=0, prev=None, lineage=None)`:
a full verification walk of the entire log. It is neither `read` nor `walk`, so
the stated invariant's two names do not cover it.

**Branch 1 is fine.** When `mark is None` the index has consumed nothing, so
"records behind" *is* every record — walking them all is the designed cost.

**Branch 2 is the violation.** When a mark exists but `anchor_record is None`
(anchor verification failed), the index may be fully current and the code still
walks from zero.

**Reproduced, on a store that is zero records behind:**

```
log: 200 facts, 126759 bytes | index mark ordinal=200 (fully caught up)
offset corrupted to 126754 (mid-record, still <= size) -> anchor validation fails

records verified via FROM-ZERO seam (_verify_from) : 201
records via _walk_tail  (the seam G-D3-2 counts)   : 0
ArrivalLog.read calls   (G-D3-2 asserts 0)         : 0
ArrivalLog.walk calls   (G-D3-2 asserts 0)         : 0
```

**L1 verified 201 records while the index was 0 behind, and every quantity
G-D3-2 instruments read clean.**

**Why the instrumentation misses it — structural, not incidental.** G-D3-2 counts
records at `ArrivalLog._walk_tail`, the *resumed-suffix* seam. The from-zero path
goes through `_walk_marked_from_zero` → `_verify_from`, a different seam that is
not counted. And its second assertion patches `ArrivalLog.read` and
`ArrivalLog.walk` **by name** — so a from-zero walk reached through a third name
is invisible twice over. This is the same shape as WP-3's `oid` finding: a
detector that enumerates spellings rather than measuring the quantity it claims
to bound. Third recurrence in this arc.

**Second aspect — the Check reports a false quantity.** The audit that results
from the reproduction above says:

```
[consumed]       ok=False behind_by=201
    index is behind arrival by 201 record(s), consumed through ordinal 200 — anchor verification failed
[counts]         ok=True  200 fact(s), 0 tick(s) accounted for
[consumed_edge]  ok=False record at consumed arrival ordinal 200 failed anchor verification
```

The index is **not behind** — the sibling `counts` check in the same report says
all 200 facts are accounted for. `behind_by=201` is the total record count
wearing a behind-ness label, and the report contradicts itself.

In fairness there is a defensible conservative reading: once the anchor fails, the
index's claimed position is untrustworthy, so "treat nothing as verified" is a
safe posture. But the arc's own scope-the-claim rule is that a detector emits
*location* claims, not invented magnitudes — the honest form here is
"anchor verification failed; consumed position unverifiable", which is exactly
what `consumed_edge` already says correctly. As written, an operator reading
`behind_by=201` on a current index will go hunting for 201 missing records.

**Required fix (shape, not prescription — the cost decision is the arbiter's):**

1. Make L1's bound real on branch 2 — do not walk from zero to produce a count
   the caller cannot trust anyway. Reporting "consumed position unverifiable"
   costs O(1) and is more honest than an O(N) walk that yields a wrong number.
2. Move G-D3-2's instrumentation off the name list and onto the **quantity**:
   count records at the verification seam itself (`_verify_from` covers both
   paths) and assert the total, rather than asserting that two specific method
   names went uncalled. A quantity bound cannot be evaded by a third name.
3. Re-scope the `consumed` Check message when the anchor fails.

---

## What passes

### Scope and the preflight constraint

In-fence: `canonical_audit.py`, `arrival.py`, `arrival_projection.py`,
`preflight.py`, `apps/loops/commands/store.py` (dispatch region — the ruled D-Q2
exception), engine + apps tests, report.

**`preflight.py` is exactly one docstring sentence** — a single line replaced
(`2 +-`), no code:

```
-    """Arrival-canonical: the agreement audit for this mode is a later cut.
+    """Arrival-canonical: agreement audit lives in canonical_audit, not preflight.
```

### `ArrivalLog.anchor` is a pure surfacing — no new validation

The `arrival.py` diff is +14 lines: a public `anchor()` that delegates to the
**pre-existing** `_anchor_for` (present at base, `arrival.py:1122`) and returns
`adopted[1]`. It mirrors the sibling method immediately above it, which returns
`adopted[0]`. **No new validation logic**, and the docstring states the limit the
contract requires: *"Anchor validation checks self-consistency only, never
chaining back to genesis."*

### Scope-the-claim — clean

A grep of `canonical_audit.py` for verdict words in Check strings
(`clean|intact|safe|valid|healthy|correct|trustworthy`) returns **nothing**. The
strongest positive form in the file is the accounted-for count
(`"200 fact(s), 0 tick(s) accounted for"`), exactly as specified. Aside from
W4-1's `behind_by`, the messages are location claims.

### Byte-offset custody — one citation, and it is not a custody claim

The mandate was that no Check cites an offset. **Literally, one does**: the
truncation branch at `:388-393` emits *"index claims to have consumed N byte(s)
through ordinal X, but the log holds only {size} — the log was truncated or
replaced"*. My disposition: this is not a byte-offset **custody** claim. It is
`ok=False`, and the offset appears as evidence of an inconsistency between what
the index claims and the file's actual size, not as grounds for asserting the log
is intact. No Check asserts custody *because* an offset matched. Reporting the
literal result with the reasoning rather than silently passing the check.

### Dissolution residue — renamed, not stranded

`_check_offset`, `_suffix_unindexed`, `_last_line` and `_check_last_line` were
unsuffixed at the merge-base and are now **`*_jsonl`-suffixed**, living only in
the legacy jsonl arm:

| Base | Now |
|---|---|
| `_last_line` | `_last_line_jsonl` |
| `_suffix_unindexed` | `_suffix_unindexed_jsonl` |
| `_check_offset` | `_check_offset_jsonl` |
| `_check_last_line` | `_check_last_line_jsonl` |

The arrival arm carries none of them. That is the right outcome rather than
deletion: a jsonl log genuinely *is* byte-addressed, so its audit legitimately
keeps byte machinery — and the rename makes the arm boundary explicit instead of
leaving shared byte-offset helpers bleeding across. `beyond_offset` survives as a
`Check` property used by the jsonl arm. The grep is non-empty; the residue is
scoped, not stranded.

### G-D3-4 multiset audit — verified independently

I built my own derived log and mutated it rather than running their fixture:

| Mutation | Result |
|---|---|
| untouched | `ok=True, missing=0, extra=0` |
| **reordered** | `ok=True` — multiset agrees, order is not custody |
| **duplicated line** | `ok=False, extra=1` — detected |
| **removed line** | `ok=False, missing=1` — detected |

Real detection, both directions, and reordering correctly does *not* alarm.

### Break/restore — G-D3-2 refuses an explicit walk

Inserting `list(log.walk())` into `_audit_agreement_arrival` (L1):

```
3 failed, 8 passed
  test_healthy_store_verifies_exactly_anchor_plus_zero_suffix
  test_k_behind_store_verifies_exactly_one_anchor_plus_k_suffix
  test_deep_audit_verifies_full_n_records
```

Restored: 11 passed. So the instrumentation does work **for the names it knows** —
which is precisely why W4-1 matters: the same cost by a third name passes.

*(My first attempt at this mutation inserted `log.walk()` into
`_check_consumed_edge_arrival`, which has no `log` parameter — a `NameError` that
failed all 11 tests for the wrong reason. Recording the misstep; the run above is
the valid one.)*

### Dispatch arm — minimal, legacy unchanged

`canonical_agreement` swaps `is_jsonl_canonical` for `canonical_mode` and gates on
`mode not in ("jsonl", "arrival")`, then branches to `ensure_arrival_index` or the
existing `ensure_index`. The **jsonl path is byte-identical in behaviour**; the
docstring generalises "JSONL-canonical" to "log-canonical" and keeps the
verification-vs-recovery seam argument intact. It sits in the ruled D-Q2 dispatch
region. Minimal and in the house style.

### Suite reconciliation — measured baselines, exact

| Suite | Baseline (`e8a9b033`) | HEAD | Delta |
|---|---|---|---|
| atoms | 517 | 517 | 0 |
| **engine** | **1878 passed, 1 skipped** | **1889 passed, 1 skipped** | **+11** |
| sdk | 324 | 324 | 0 |
| lang | 655 | 655 | 0 |
| **store** | **176** | **176** | 0 |
| arch | 98 | 98 | 0 |
| **apps/loops** | **2526 passed, 1 xfailed** | **2529 passed, 1 xfailed** | **+3** |

`test_audit_rebase_d3.py` collects exactly **11**; 1878 + 11 = 1889. The apps
delta is **+3**, matching the implementer's claim — I initially suspected +4
because I was differencing against WP-3's 2525 rather than the merge-base's 2526,
and measuring the baseline resolved it in the implementer's favour.

---

## Bottom line

The audit re-base is well built. The anchor verb is a genuine surfacing with no
smuggled validation, the byte-offset machinery is correctly quarantined into the
jsonl arm rather than deleted or left shared, the multiset audit really is a
multiset audit, the Check messages are location claims with no verdict words, the
dispatch arm is minimal, and the suites reconcile exactly against baselines I
measured.

The one thing I cannot pass is the invariant the package exists to establish.
L1's bound is stated in terms of two method names, and a third name —
`walk_marked(None)` — walks the whole log from zero on a reachable path while
every instrumented quantity reads clean. On a 200-record store that is 201 records
verified for an index that was zero behind, reported to the operator as
"behind by 201". Fixing the bound and moving the instrumentation from names to a
counted quantity closes both halves.

---
---

# ROUND 2 — re-gate of the W4-1 fix (`65e1adcb` + `c3b8dcd4`)

Scoped to W4-1. Gate branch rebased onto `c3b8dcd4`.

## ROUND 2 VERDICT: **PASS** — W4-1 closed, and no second evasion exists.

The production fix is five lines: branch 2's `walk_marked(None)` and its
`suffix_count` are deleted, and the Check becomes an O(1) location claim with no
magnitude. Exactly the recommended shape, and nothing else in the module moved.

## 1. My Round-1 reproduction, re-run verbatim

Same fixture: 200 facts, index mark current at ordinal 200, offset corrupted
mid-record so anchor validation fails.

| Quantity | Round 1 | Round 2 |
|---|---|---|
| records via from-zero seam (`_verify_from`) | **201** | **0** |
| records via `_walk_tail` | 0 | 0 |
| `ArrivalLog.read` / `.walk` calls | 0 / 0 | 0 / 0 |

The audit now reports:

```
[consumed]       ok=False behind_by=0
    anchor verification failed; consumed position unverifiable at ordinal 200
[counts]         ok=True  200 fact(s), 0 tick(s) accounted for
[consumed_edge]  ok=False record at consumed arrival ordinal 200 failed anchor verification
```

Both halves of the finding are closed. The walk is gone, and the invented
magnitude is gone — `behind_by=0`, and the message is a location claim
("unverifiable at ordinal 200") rather than a fabricated behind-count. The
self-contradiction is gone too: `consumed` no longer claims 201 records missing
while `counts` in the same report accounts for all 200.

## 2. Second evasion attempt — none found, and I can say why

I enumerated every record-reading primitive in `arrival.py` and traced which
bypass the quantity seam:

| Primitive | Routes through `_verify_from`? |
|---|---|
| `walk()` | yes — `_records_only(_walk_marked_from_zero())` |
| `read(ordinal)` | yes — via `walk()` |
| `head()` | yes — via `walk()` |
| `walk_from` / `walk_marked` | yes — **both** arms (`_walk_marked_from_zero`, `_walk_tail`) |
| `_record_ending_at` | **no** — but reads exactly ONE record (seek, `_last_newline_before`, one `decode_record`) |
| `_tail_record` | **no** — reverse scan, constant-time by design, and called only from `append_record` (`arrival.py:1463`), never from an audit path |

So the two bypasses are structurally incapable of O(N) work: one reads a single
record at a byte boundary, the other reads the last record for the append path.
`_record_ending_at` is the anchor read, and it is the quantity the instrumentation
counts separately.

**Confirmed empirically on a healthy 50-fact store (51 records):**

```
L1 audit_agreement   _verify_from records=  0   _record_ending_at calls=1
--deep audit_deep    _verify_from records= 51   _record_ending_at calls=1
```

L1 verifies zero records through the seam and reads exactly one anchor; `--deep`
routes the entire history through the seam. **The quantity seam genuinely covers
all multi-record verification** — an answer, not a "found nothing". This also
fixes the class weakness I flagged in Round 1: the instrumentation no longer
asserts that two method names went uncalled, it counts records at the one place
records are verified, so a third name cannot slip past it.

## 3. Mutation proof — verified independently

Rather than re-running theirs, I re-introduced **my own** Round-1 defect: the
branch-2 `walk_marked(None)` and its `behind_by=suffix_count`.

```
1 failed, 11 passed
FAILED …TestGateD3_2_BoundedWorkInstrumentation::test_anchor_failed_corrupted_offset_verifies_single_record_no_walk
```

Restored: 12 passed. The test that catches it did not exist in Round 1 — it is my
reproduction turned into a fixture, which is the right outcome: the finding is now
pinned by the suite rather than by my having looked.

## 4. Suite reconciliation

| Suite | Round 1 (`6ac0ae23`) | Round 2 (`c3b8dcd4`) | Delta |
|---|---|---|---|
| engine | 1889 passed, 1 skipped | **1890 passed, 1 skipped** | **+1** |
| apps/loops | 2529 + 1 xfail | **2529 + 1 xfail** | 0 |
| store | 176 | **176** | 0 |

`test_audit_rebase_d3.py` collects **12** (was 11) — the +1 is exactly the new
anchor-failed bound test. The fix report's suite table matches mine on every
figure, and lists two suites I had not been running (`libs/custody` 13,
`libs/sign` 37) — more complete than my set, not less.

## Bottom line

W4-1 is closed on both halves and the fix is minimal — five deleted lines and a
re-worded Check, with no other production change. More importantly the
instrumentation moved from a name list to a counted quantity, which is what makes
the bound defensible rather than merely asserted: I went looking for a second way
past it and found that every path verifying more than one record funnels through
the seam, with the only two bypasses bounded to a single record by construction.

WP-4 passes. Ready for sol-low.
