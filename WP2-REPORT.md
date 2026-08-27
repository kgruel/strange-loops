# WP-2 — Witness re-key (slice D, D1): completion report

Branch `slice/D-wp2`, worktree `wt-wp2`. Contract:
`docs/scratch/arrival-sliceD/design-proposal.md` §D1, plus the ratified
rulings carried in the work-package brief.

---

## 1. Checkpoint audit — verdict

The prior worker's checkpoint (`0996c112`) implemented the data-model
re-key correctly in the large, and got **one contract point materially
wrong**. Verdict per contract point:

| Contract point | Checkpoint | Action |
|---|---|---|
| `WitnessPosition` re-keyed (`arrival_lineage`, `ordinal`, `-1` empty prefix) | correct | kept |
| `at_rowid` → `at_ordinal` repo-wide, incl. spec/conformance call sites | correct (one miss, below) | one miss fixed |
| `WitnessAxisMismatch` exists, fires only when BOTH sides carry a real axis | **WRONG — placement** | fixed |
| A10 + both `verify_position_for_store` refusal branches byte-identical | messages yes, **structure no** | structure restored |
| engine `baseline` field on `diff_interval_report`, `fold.py` its only consumer | correct | kept |
| `WitnessAggregateUnsupported` docstring corrected, raise sites + messages byte-identical | correct | pinned (G-D1-2) |
| `durable_handle` output unchanged | correct | pinned (G-D1-5) |
| `handle.py` bootstrap `ordinal=-1, arrival_lineage=None` | correct | kept |
| fold-replay + event-cursor `ORDER BY arrival_ordinal, arrival_seq` | ORDER BY yes; **cursor still rowid-keyed** | flagged, §6 |

### 1a. The MAJOR: the axis guard was placed above the same-path branch

D1 rules the new guard as the **SAME-PATH** guard: "a store file replaced
in place under the same path". The checkpoint hoisted it above the
`if at.store == target:` early return, which made it a *cross-store* guard
as well. Two consequences, both contract violations:

1. **It preempts A10.** An unadopted or lineage-mismatched position moving
   between two arrival-canonical stores raised `WitnessAxisMismatch`
   instead of `WitnessLineageMismatch`. The contract requires both A10
   refusal branches to survive byte-identical — reachable, not merely
   present in the source.
2. **It breaks B1c re-resolution.** Two stores that legitimately share a
   declaration lineage have their OWN arrival logs, so their axes differ by
   construction. Re-resolution by fact id — the whole point of a portable
   lineage-qualified handle — became a refusal.

The existing `TestCrossStoreReResolution` did **not** catch this: its
hand-rolled stores carry no `arrival_lineage` meta key, so the guard
silently no-opped there. That is why G-D1-4 builds real arrival-canonical
stores.

Fixed by moving the check inside the same-path branch, gated on
`at.arrival_lineage is not None` so an axis-less position keeps the
documented no-DB-hit fast path (`declaration.py`'s "Same-store returns the
position unchanged (no DB hit)" comment stays true), and restoring the
`_open_readonly` call to its original position below the unadopted branch.

---

## 2. File-by-file

### Source

- **`libs/engine/src/engine/witness.py`** — restructured
  `verify_position_for_store` per §1a; gave `WitnessAxisMismatch` a real
  docstring stating what separates it from A10; rewrapped nine lines the
  checkpoint pushed over the 100-column limit (baseline `witness.py` is
  ruff-clean; the checkpoint was not); lifted the equal-ordinal contiguity
  disjunct in `receipt_group_span` into a named `contiguous` local with a
  comment saying why equality continues a run (rows of ONE arrival record
  share an ordinal and differ only in `arrival_seq`). No behavior change
  beyond §1a.
- No other source file was edited. `declaration.py`, `store_reader.py`,
  `vertex_reader.py`, `sqlite_store.py`, `handle.py`,
  `apps/loops/src/loops/cli/views/fold.py` are the checkpoint's, audited
  and kept.

### Tests

- **`libs/engine/tests/test_witness_rekey_d1.py`** — NEW. G-D1-2..G-D1-6,
  20 tests. See §3.
- **`libs/engine/tests/test_arrival_rederivation_rowids.py`** — the
  `test_rederivation_preserves_receipt_group_contiguity` non-vacuity probe
  was structurally dead under record granularity (see §4); replaced with a
  positive, stronger assertion.
- **`libs/engine/tests/test_vertex_reader.py`**,
  **`test_ordering_checkpoint_dispatch.py`**,
  **`apps/loops/tests/test_surface.py`**, **`test_integration.py`**,
  **`libs/sdk/tests/test_declare.py`** — fixture conformance only:
  hand-rolled `CREATE TABLE facts/ticks` scaffolds gained the two
  coordinate columns, and their inserts populate them (dense
  `MAX+1`, `seq 0` — the legacy-mirrored allocator). No assertion touched.
  `test_ordering_checkpoint_dispatch._append` also lost a
  `PRAGMA table_info` conditional that only existed to tolerate the
  column-less scaffold it now no longer has.
- **`apps/loops/tests/test_durable_handle.py`** — one missed
  `pos.rowid` → `pos.ordinal` rename (the checkpoint's only rename miss).
- **`libs/engine/tests/MUTATION-witness.md`** — stale-record header. See §5.

---

## 3. The gates

`libs/engine/tests/test_witness_rekey_d1.py`, 20 tests, all passing.

- **G-D1-2** (5 tests) — the three `WitnessAggregateUnsupported` raise-site
  messages and both A10 messages pinned by **whole-string equality**. The
  pre-existing suites match these by substring (`match="UNADOPTED handle"`),
  which cannot see an edit to the rest of the sentence — and the re-key
  rewrote the surrounding prose of both modules. A10's messages still say
  "rowid"; that is deliberate, the contract says byte-identical.
- **G-D1-3** (3 tests) — the ruled cost of D1-Q1's record-granular arm. A
  real two-row `absorb_edit` ceremony rides one arrival record; both rows
  resolve to the same `(ordinal, seq)`, so `seq:N` round-trips to the
  RECORD's last row, not to the addressed mid-batch row. The converse is
  pinned too: every single-row record round-trips exactly, so the cost is
  confined to multi-row records.
- **G-D1-4** (4 tests) — same-path replacement (`shutil.copyfile` of a
  different arrival-canonical store over the path) raises
  `WitnessAxisMismatch`; the guard needs a real axis on both sides; A10's
  two refusals are reachable and unchanged across two arrival-canonical
  stores; a same-lineage sibling still re-resolves to the TARGET's
  coordinate and the TARGET's axis. The last three are the regression net
  for §1a.
- **G-D1-5** (5 tests) — position equivalence on a 12-row corpus in two
  representations: un-permuted (rowid order == arrival order) and permuted
  (physically written in a scrambled order). On the un-permuted store the
  arrival-resolved prefix selects exactly the row-set rowid selection did;
  on the permuted store arrival governs, rowid does not, and the test
  asserts the divergence is non-zero so it cannot pass vacuously. Plus:
  `durable_handle` output unchanged (`fact:<lineage>/<id>` for adopted,
  `None` for genesis and unadopted); and the SELECTION path
  (`StoreReader.facts_by_kind(at_ordinal=...)`) proved to ride the arrival
  axis, which the first draft of this gate missed — see §6b.
- **G-D1-6** (3 tests) — a reversed `--diff` reports identical content and
  flips only `baseline`; `baseline` is present on the empty interval; the
  app's engine-name → CLI-label mapping is pinned so it cannot silently
  invert.

---

## 4. The one semantic change I had to make honest

`test_rederivation_preserves_receipt_group_contiguity` asserted
`any(s is not None for s in before)` — "some probe lands strictly inside
the ceremony". Under RECORD-GRANULAR that is **structurally impossible**:
the ceremony's two rows share ordinal 6 (`seq` 0 and 1), so
`receipt_group_span` sees `first == last` and no cutoff can land inside.
The mid-ceremony hazard the guard exists for is *dissolved* by the record
boundary rather than detected.

I did not weaken the assertion to `assert True`-shaped noise. The probe was
replaced with a stronger positive claim: the ceremony is two rows, they
share ONE ordinal, their seqs are `[0, 1]`, every span probe is `None`
*because* of that, and rederivation preserves all of it. The docstring says
why. This is the ruled cost of D1-Q1 surfacing in an existing test, not a
defect.

Observed coordinates for that store (facts): ordinals
`1, 2, 3, 5, 6, 6, 7, 9`; ticks take `4` and `8`. Note the fact axis is
**sparse** — the ordinal is shared across record types, as D0 specifies.

---

## 5. Residue sweep

### `rg -n "at_rowid"` — zero in source and test code

Every remaining substring hit is one of two non-code classes:

1. `docs/scratch/arrival-sliceD/*` (design proposal + codex review logs) —
   documents that *describe the rename*. Editing them would falsify the
   design record.
2. `libs/engine/tests/MUTATION-witness.md` — four hits, all inside verbatim
   mutmut identifiers of the OLD `_id_at_rowid` function
   (`x__id_at_rowid__mutmut_2` etc.). These are ids mutmut actually emitted
   against the pre-re-key module.

**Declared deviation.** The brief asks for a literally empty `rg`. I did
not rewrite those mutant ids: the report would then claim a run that never
happened. Instead I added a STALE header naming exactly what D1 invalidated
(`_resolve_address_rowid`/`_id_at_rowid` renamed AND their logic changed —
`_id_at_ordinal` is now a `<= ?` descending pick, and its empty guard moved
from `rowid <= 0` to `ordinal < 0`, so survivor `mutmut_1`'s equivalence
argument no longer holds as written; `receipt_group_span`'s condition was
rewritten around row 5's mutant; `verify_position_for_store` gained a
branch and moved its conn open, invalidating survivor `mutmut_24`), and
stated that no number in it has been re-measured. **The gate should rule
whether the file is re-run under D1 or retired.**

Note the parameter `at_rowid` itself — the thing D1 calls forbidden residue
— is at zero occurrences repo-wide.

### `rg -n "\.rowid"` over `libs/engine/src` + `fold.py`

`fold.py`: **zero**. `libs/engine/src`, 27 hits, three allowlisted classes:

| Site | Class | Justification |
|---|---|---|
| `store_reader.py:962` | FTS plumbing | `JOIN facts f ON f.rowid = fts.fact_rowid` — `facts_fts` keys on rowid by construction |
| `store_reader.py:406` | row address (seal window) | tick `fact_cursor` → rowid boundary; this is the seal window resolution D2 re-bases, explicitly not D1 |
| `sqlite_store.py:764, 807` | row address (D0 migration) | the rowid-PRESERVING rebuild copy — naming `rowid` in both column lists is the D0 requirement, not residue |
| `handle.py` × 23 | in-memory checkpoint cursor | `FactHead.rowid`/`TickHead.rowid` are the handle's own incremental cursors, which D1 explicitly leaves alone ("`handle.py`'s checkpoint machinery holds heads in memory only") |

---

## 6. Residues I did NOT fix, and why

**(a) `sqlite_store` mixed-axis cursors.** `since_raw`, `fold_replay`,
`fold_replay_iter`, `ticks_since` now read
`WHERE rowid > ? ORDER BY arrival_ordinal, arrival_seq` — a cursor in rowid
space with an ordering in arrival space. On a store where the two axes
agree this is benign; on one where they diverge (a rebuilt or permuted
index) an incremental replay can select the wrong suffix. D1's enumerated
change is the `ORDER BY` only ("they are the ordering-authority read
path"); re-keying the *cursor space* changes the caller contract and is
D2/WP-3 work. **Named here so it is a decision, not an oversight.**

**(b) `handle.py`'s rowid checkpoint.** Same shape as (a), one layer up:
`fact_cursor`/`tick_cursor` are rowids while the fold they extend is now
arrival-ordered. D1's text licenses leaving it ("holds heads in memory
only"), so it stays — but it is the same coherence gap and should be ruled
with (a).

**(c) `query_facts` pagination under record granularity.** `before`/`after`
use strict `arrival_ordinal < / > ?`. Rows sharing an ordinal (one batch
record) cannot be split across pages — a page boundary falling inside a
record skips the rest of it. This is the record-granular arm's known cost
(D1-Q1) applied to pagination; the composite-cutoff alternative was the
arm Kyle did not take.

---

## 6b. Break / restore proofs

Run AFTER the commit (`450bfa5d`), one mutation each, every mutation
reverted with `git checkout` and re-verified green.

| Gate | Mutation | Result |
|---|---|---|
| G-D1-3 | `witness.py` seq count cutoff `arrival_ordinal <= ?` → `< ?` | **2 of 3 FAILED** — `SeqOutOfRange: seq:0 is out of range` on the mid-batch round-trip, plus the single-record converse. Restored: 3 passed. |
| G-D1-4 | re-hoist the axis guard above the same-path early return — i.e. **reintroduce the prior worker's exact bug** | **2 of 4 FAILED** — `WitnessAxisMismatch: ... (AXIS-A) does not match ... (AXIS-B)` raised where A10 and B1c re-resolution belong. Restored: 4 passed. |
| G-D1-5 | `witness.py` id→position resolution `SELECT arrival_ordinal` → `SELECT rowid` | **1 FAILED** — `At index 0 diff: 1 != 2`. Restored: passed. |
| G-D1-5 | `store_reader.facts_by_kind` witness cutoff `arrival_ordinal <= ?` → `rowid <= ?` | **initially SURVIVED — see below**; after the gate was extended, **FAILED** with `assert ['corpus-007'] == ['corpus-000']`. Restored: 5 passed. |
| existing pin (row 5 of `MUTATION-witness.md`) | `receipt_group_span`'s ts/lineage conjunction `and` → `or` — the mutant that pin exists to kill, inside the expression the checkpoint rewrote | **FAILED** — `assert (1, 3) is None`. The pre-existing pin still kills it under the equal-ordinal rewrite. Restored: passed. |

### A real gap the proofs found, and closed

The fourth mutation is the one worth reading. With `facts_by_kind`'s
witness cutoff silently reverted to the **rowid** axis, the **entire engine
suite passed — 1860 passed, 1 skipped**. G-D1-5 as first written tested
position *resolution* and the prefix row-set via hand-rolled SQL; the
**selection** path (`StoreReader.facts_by_kind(at_ordinal=...)`, which is
what every `at=` fold actually reads through) has its own cutoff clause and
was unguarded. A regression there would have shipped silently.

G-D1-5 gained
`test_the_reader_selects_on_the_arrival_axis_not_the_rowid_axis`: it
selects through the real reader on the permuted store, asserts the result
is exactly the canonical arrival prefix in arrival order, and asserts
non-vacuously that rowid order genuinely disagrees there. The mutation now
dies. Engine is **1861 passed, 1 skipped**.

This is why the break/restore step is run after the commit and not skipped:
the gate that passed on the first write was not yet a gate.

---

## 7. Suite results — all seven, foreground, exact

| Suite | Result |
|---|---|
| `libs/atoms/tests` | **517 passed** |
| `libs/engine/tests` | **1861 passed, 1 skipped** (1841 + 20 new gates) |
| `libs/sdk/tests` | **324 passed** |
| `libs/lang/tests` | **655 passed** |
| `libs/store/tests` | **157 passed** |
| `tests/architecture` | **98 passed** |
| `apps/loops/tests` | **2525 passed, 1 xfailed** |

Every count matches the brief's expected numbers, with engine at
1841 + 20 gates. No assertion was weakened anywhere; every red was fixed by
fixture conformance, one missed rename, or §1a's product fix — except the
one documented semantic change in §4, which was made STRONGER.

`uv.lock` was copied in from the main checkout (it is gitignored, so the
worktree had none and `--frozen` could not resolve); it is not committed.

---

## 8. Fence deviations, declared

- **`libs/sdk/tests/test_declare.py`** — outside the fence (which names only
  `libs/sdk/tests/test_conformance.py`). Its
  `test_inspect_declaration_unadopted_lineage_error` hand-rolls a
  column-less `facts` table; post-D1 that store reads as "not a usable
  store" and returns `None` before reaching the `no own_lineage marker`
  error the test is *about*, so the test went red. The edit is two
  coordinate columns on the CREATE TABLE and their values on the INSERT —
  fixture conformance, the blessed class, with a comment saying why. No
  assertion changed.
- **`libs/engine/tests/MUTATION-witness.md`** — inside the fence, but the
  change is a staleness header rather than the mechanical rename the brief
  implies. Rationale in §5.

Everything else stayed inside the fence. No `spec/` change beyond the
checkpoint's existing renames.
