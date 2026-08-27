# GATE REPORT — WP-2 (witness re-key, D1)

Independent gate. Target `dc03e64d` on `slice/D-wp2`; merge-base `1d8e64f5`
(**before** WP-5 merged — all baselines below are measured at that commit, not
inherited from the WP-5 round). Branch `slice/D-wp2-gate`.

**Provenance caveat.** The checkpoint `0996c112` is a flash-high worker's
recovered WIP; the completion commits (`450bfa5d`, `5bc27120`, `ae809e8f`,
`dc03e64d`) are a Claude opus agent's, same family as me. I re-derived the D1
contract from `design-proposal.md` §D1 **before** reading the implementation, and
verified the axis-guard placement against the proposal's own words rather than
against the report's account of what the checkpoint got wrong.

## VERDICT: **PASS** on contract conformance — every enumerated item holds.

**One MAJOR finding (W2-1) is escalated for ruling.** To be unambiguous: **it does
not block WP-2's merge** — the implementation does literally what §D1 specifies —
**but it must be ruled before the arc ships.** Details and reasoning in the
findings section.

---

## 1. Scope

Against the merge-base, the change touches the six fenced engine modules, the
`fold.py` consumer, engine + apps tests, and the four ruled conformance
call-sites. Two notes:

- **No frozen vector file moved.** `git diff --stat -- '*.json'` is **empty**, and
  the only `spec/` files touched are the two generators. The four renames are
  purely mechanical `at_rowid=pos.rowid` → `at_ordinal=pos.ordinal`.
- **`fold.py` is the ruled option (i)**, 12 lines in one function: it stops
  computing `pos1.rowid <= pos2.rowid` and reads the engine's new `baseline`
  field. Zero `rowid` references remain in the file.

**Scope note — `libs/sdk/tests/test_declare.py` is outside the stated fence.**
Ten lines, and legitimate: a hand-rolled `facts` table gains the coordinate
columns, because WP-2's read-path re-key makes a coordinate-less table
unreadable before the marker check the test is about. No assertion changed. The
fence should have named it; the edit itself is correct and minimal.

## 2. Suite reconciliation — measured baseline, exact

Baseline run by this gate in a separate worktree at the merge-base `1d8e64f5`:

| Suite | Baseline (`1d8e64f5`) | HEAD (`dc03e64d`) | Delta |
|---|---|---|---|
| atoms | 517 | 517 passed | 0 |
| **engine** | **1841 passed, 1 skipped** | **1861 passed, 1 skipped** | **+20** |
| sdk | 324 | 324 passed | 0 |
| lang | 655 | 655 passed | 0 |
| store | 157 | 157 passed | 0 |
| arch | 98 | 98 passed | 0 |
| apps/loops | 2525 passed, 1 xfailed | 2525 passed, 1 xfailed | 0 |

`test_witness_rekey_d1.py` collects exactly **20**; 1841 + 20 = 1861. Every other
suite is unchanged despite ~10 existing test files being modified in place, which
is the expected signature of a rename-and-adapt.

The WP-5 merge will follow and will move the engine baseline again (+9/+18); this
reconciliation is against WP-2's own merge-base only.

**No weakened assertions.** I read every removed assertion. Two looked like drops
and are both **strengthenings**:

- `assert any(s is not None for s in before)` → four assertions pinning that the
  two-row ceremony rides **one** record (shared ordinal, seq 0 and 1) and that
  therefore `all(s is None)`. See the A2 observation below.
- `assert forward == backward` → per-field equality **plus** `baseline == "pos1"`
  / `"pos2"`, which is stricter: the old assertion could not have caught a
  baseline that failed to flip.

## 3. Contract conformance

**Data model.** `arrival_lineage: str | None` added, `rowid` → `ordinal`,
empty prefix `-1`, storeless bootstrap `ordinal=-1, arrival_lineage=None`. Matches
§D1's block verbatim.

**The same-path axis guard — re-derived, not accepted.** §D1 specifies it as three
conjuncts: *"target is arrival-canonical, position carries a real
`arrival_lineage`, and it does not match"*, with *"fires only when **both** sides
carry a real axis."* The implementation places it **inside** the `at.store ==
target` branch, returns early when `at.arrival_lineage is None` (legacy keeps the
no-DB-hit fast path), and raises only when `target_arrival_lineage is not None
**and** the two differ. All three conjuncts present and ANDed, in the specified
position, with A10's branches below untouched. **This is correct placement by the
proposal's own definition**, independent of the report's account.

**Verbatim-preservation criteria — checked by byte comparison:**

| Criterion | Result |
|---|---|
| `WitnessAggregateUnsupported`, 3 raise sites | **3 at both revisions, messages byte-identical** (same md5) |
| A10 `WitnessLineageMismatch` raise blocks | identical except one **comment** word ("applied rowid" → "applied ordinal"); conditions, structure and message text unchanged |
| `durable_handle` | executable body **untouched**; the only change is one docstring line |
| `verify_position_for_store` cross-store branches | unchanged, including the same-lineage re-resolution |

**Fold-replay / event-cursor.** All four sites re-keyed to
`ORDER BY arrival_ordinal, arrival_seq`, as §D1 requires — and this is where W2-1
lives.

## 4. Residue audit

**`at_rowid` repo-wide — literal result: not empty, but not code.** The only hits
are in `libs/engine/tests/MUTATION-witness.md`, prose quoting **pre-rename mutant
names** (`x__id_at_rowid__mutmut_1`) while documenting a mutmut run. No source,
test, or spec file contains the identifier. Reporting the literal result rather
than silently passing the check; my disposition is that historical mutant names in
a mutation-testing writeup are not residue, but the ruled check said "EMPTY" and
this is why it isn't.

**`fold.py`** — zero `rowid`. Clean.

**Remaining `rowid` in `libs/engine/src`** — audited against the allowlist. All
uses are row-address UPDATEs, FTS plumbing (`fact_rowid`, `last_rowid`,
`facts_fts`), or axes §D1 does not enumerate. I traced the two that looked like
missed witness-prefix queries:

- `store_reader.py:418` `WHERE rowid > {boundary}` — `boundary` is itself a
  subquery selecting `f.rowid`. Both sides rowid; **no axis mixing**. Not an
  enumerated site (it is the unsealed-backlog count, not a witness prefix).
- `handle.py:439` `WHERE rowid <= ?` — fed by `fhead.rowid`, handle's own
  detection-cursor probe. Both sides rowid; **no axis mixing**.

**Arc-level observation (NOT a WP-2 finding):** `handle.py` deliberately retains a
rowid detection axis, and §D1 does not enumerate it, so it is correctly untouched
here. That the detection axis and the witness axis can in principle diverge is an
arc-level question, not this package's — recording it so the next gate does not
re-litigate it as residue.

## 5. Break/restore — two mutations, two different tests

Assigned proof (G-D1-4) plus the mutation the completion history implies:

| Mutation | Test that fails |
|---|---|
| Axis guard disabled entirely | `test_same_path_replacement_raises_witness_axis_mismatch` |
| **`and` → `or`** (guard fires when the target has *no* axis) | `test_axis_guard_needs_a_real_axis_on_BOTH_sides` |

Restored: 20 passed. **Different tests catch the two mutations**, so the refusing
side and the both-sides restriction are independently pinned — the "fires only
when both sides carry a real axis" clause is a real ratchet, not prose. This
independently confirms the completion's fix and its own row-5 re-verification.

**G-D1-5 re-run** (assigned): 9 passed with G-D1-4. Their permuted harness is
sound — an un-permuted control (which would pass for a no-op) *plus* a permuted
case with a divergence counter (which would not).

## 6. Behavioural observation — A2 is now structurally vacuous for single-record ceremonies

`receipt_group_span` continues a run on `ord_val in (prev_ord, prev_ord + 1)` —
equality included, because rows expanded from one arrival record share an ordinal.
A ceremony that rides **one** record therefore has `first == last`, and
`first <= ordinal < last` can never hold, so `MidReceiptGroupPosition` **cannot
fire** for it.

This is more correct, not less: an atomic batch at a single ordinal genuinely
cannot be split by an ordinal cutoff, so there is nothing to refuse — atomicity
became *structural* instead of *guarded*. Legacy/mirrored stores, where a ceremony
spans consecutive ordinals, still reach the refusal. Both paths remain covered,
and the strengthened test documents it. Recording it because a reader who knows
the old behaviour will otherwise read the guard as dead code.

---

## FINDING W2-1 — MAJOR, escalated for ruling — mixed axes in the re-keyed cursor queries

**Not blocking WP-2's merge. Must be ruled before the arc ships.**

**What.** Four statements now filter on one axis and order on another:

```sql
SELECT ... FROM facts WHERE rowid > ? ORDER BY arrival_ordinal, arrival_seq
```

(`sqlite_store.py:1744`, `:1780`, `:1802`, and `:2604` for ticks.) The **set** is
chosen by rowid; the **order** is arrival. Before WP-2 both were rowid and the
statement composed. §D1 names only the `ORDER BY` for these queries, so the
implementer did exactly what was specified — **the gap is in the specification,
not the implementation.** That is why this is escalated rather than filed against
the package.

**Live callers.** `SqliteStore.since()` is not dead: `projection.py:102`
(`advance()`, an incrementing cursor), `replay.py:31`, `vertex.py:950`.

**Demonstrated.** On a permuted corpus, incremental folding through
`projection.advance`'s count-based cursor diverges from full replay:

```
arrival order   = [0, 1, 2, 3, 4, 5, 6, 7]
full replay     = [0, 1, 2, 3, 4, 5, 6, 7]   match=True
incremental     = [0, 1, 2, 3, 1, 3, 4, 6]   match=False
```

Rows 1 and 3 are **re-delivered**; 5 and 7 are **dropped**. On an un-permuted
corpus both match exactly, which is why every suite is green.

*Probe-methodology correction, stated as in the WP-5 round:* my first probe
advanced the cursor to the rowid of the last returned row and reported
re-delivery. **No production caller does that** — both use count-like cursors. The
count-cursor probe above is the accurate demonstration. The finding stands; the
mechanism is the one shown here.

**Why it is latent, and why it still matters.** The axes cannot diverge naturally
today: mirrored migration sets `ordinal = rowid`, rederivation replays in arrival
order, merges append suffixes, and batch rows insert in seq order. My probe needed
a hand-built permuted corpus *and* a persisted mid-corpus cursor — double-latent,
and no user reaches it. But the arc's central claim is deterministic fold order on
the arrival axis, and this makes incremental folding disagree with full replay
under **G-D0-1's own permuted harness** — the oracle this arc built. Whether that
contradiction is acceptable in an intermediate state is Kyle's call, not mine;
hence escalation rather than a verdict either way.

**The obvious fix is wrong — verified, so nobody applies it as a drive-by.**
Re-keying the `WHERE` to `arrival_ordinal > ?` breaks under batches with the
existing count cursors, because a batch shares one ordinal. On a corpus of
`ord 1 = 1 row, ord 2 = a batch of 3, ord 3 = 1 row`:

```
step0: cursor->2, got ['f0', 'b0']
step1: cursor->3, got ['f1']
delivered: ['f0', 'b0', 'f1']   MISSING: {'b1', 'b2'}
```

A correct re-key must change cursor **semantics** to `(ordinal, seq)` pairs. That
is a design decision, which is the strongest reason this is a ruling and not a
finding-with-an-exact-fix.

**Recommended alongside the ruling:** an *incremental-equals-full-replay*
equivalence test on the permuted harness. That invariant is exactly what I checked
by hand and nothing in the suite pins it — the same shape as the R5-1 coverage
gap from the WP-1 rounds.

---

## What I could not verify

Nothing in the protocol list was left unchecked. One limit: I did not exercise
concurrent writers against the re-keyed cursor queries; the divergence above is a
single-writer, single-reader property.

## Bottom line

**WP-2 conforms.** The re-key is complete across the enumerated sites, the
verbatim-preservation criteria survive byte comparison, the axis guard sits where
§D1 puts it with both of its failure modes independently ratcheted, residue is
clean apart from one documented prose carve-out, and the suites reconcile exactly
against a baseline I measured rather than inherited. The two assertion changes
that looked like drops are stricter than what they replaced.

W2-1 is the one thing I will not wave through silently: a demonstrated
incremental-vs-full-replay divergence in live code paths, spec-conformant,
double-latent, and un-pinned by any test. It needs Kyle's ruling before the arc
ships, and it needs a ratchet whichever way he rules.
