# Cut B — PROJECTIONS: independent gate report

Gate worktree `/Users/kaygee/Code/loops-wt/arrival-projections-gate`, branch
`slice/arrival-projections-gate`. Every command below was run by the gate in
this worktree. The implementation report was read as a TARGET, never as an
authority: each gate item was re-answered from scratch.

**FINAL VERDICT: FINDINGS NON-BLOCKING — with one item for the arbiter.**

Nothing in cut B is wrong. Both gate items hold under the gate's own probes
and the gate's own mutations. One deviation (#9, the Rule 18 allowlist +1)
breaches a verbatim green criterion for a reason the gate independently
confirmed is real and unavoidable, so it is referred rather than accepted:
**needs-arbiter-ruling**. Six non-blocking findings follow at the end.

## Step 0 — provenance

```
$ git rev-parse HEAD
ef1022bed3c2dc5a1aae54800b245921b1f9490f
$ git merge-base HEAD feat/arrival-libs
39ea67f5aab0acc014e1754d8afb1668fb8d1332
```

Both as briefed. `feat/arrival-libs` is itself at `39ea67f5`, so
`feat/arrival-libs..822c0891` is the whole slice.

---

## G1 — the rowid/witness ratchet. **PASS**

### The slice's own tests

```
$ uv run --no-sync --package engine pytest libs/engine/tests/test_arrival_rederivation_rowids.py -q
5 passed
```

### The gate's own probe (`gate_oracle.py`, written here, not by the implementer)

Builds an arrival store through the write path, resolves a `WitnessPosition`
for every fact, re-derives, re-resolves — then does the same over a store
that **received a merge**, and asserts the premise itself.

```
G1a — a store built through the arrival write path
  ok  fixture is not vacuous: 6 fact rows
  ok  fixture carries two ticks
  ok  the ceremony really landed as a batch record: ['genesis', 'fact', 'fact', 'fact', 'tick', 'batch', 'fact', 'tick']
  ok  every (rowid, id) pair is identical across re-derivation
  ok  every WitnessPosition re-resolves to the same (rowid, seq, lineage, handle)
  ok  the re-derivation reports what it replayed: 8 records, 6 facts

G1b — a store that RECEIVED A MERGE (the premise cut B establishes)
  ok  the merge actually moved rows: MergeResult(facts_added=6, facts_skipped=0, ticks_added=2, ticks_skipped=0)
  ok  a MERGED store's (rowid, id) pairs survive re-derivation
  ok  a MERGED store's witness positions survive re-derivation
  ok  the index carries rows from no source but the log (16 ids)
```

### Mutation verification — the gate's own edit, not the implementer's

The merge arm's `log.append_marked_many(...)` + `_rederive_after_append(...)`
was replaced with a direct index INSERT (the pre-cut-B anti-pattern), written
by the gate:

```python
# GATE MUTATION G1 — the pre-cut-B anti-pattern restored: write the
# rows straight into the sqlite index and never touch the log.
_c = _open(index_path_for(canonical))
for _e in entries:
    for _t, _row in records_from_object(_e.body):
        _c.execute(FACT_INSERT_SQL if _t == "fact" else TICK_INSERT_SQL, _row)
```

Result — the merged-store ratchet goes RED, and so does the gate's own oracle:

```
FAILED libs/store/tests/test_arrival_merge.py::test_merge_never_writes_the_index_directly
FAILED libs/store/tests/test_arrival_merge.py::test_rederivation_reproduces_every_rowid_over_a_merged_store
2 failed, 23 deselected in 0.11s

AssertionError: FAILED: a MERGED store's (rowid, id) pairs survive re-derivation
```

Restored:

```
$ git checkout -- libs/store/src/store/merge.py
$ git diff --stat -- libs/
(empty)
$ ... -k "rowid_over_a_merged_store or never_writes_the_index_directly"
2 passed, 23 deselected in 0.18s
```

The ratchet is real, it is load-bearing, and the premise it rests on is the
one this cut's merge rewrite establishes.

---

## G2 — the git merge driver, proven by real `git merge`. **PASS**

### The slice's subprocess tests

```
$ uv run --no-sync --package store pytest libs/store/tests/test_derived_log_merge.py -q
15 passed
```

### The gate's own fixture repo

Built by hand in a temp dir — never against the live `.loops/` store or any
real checkout — with `HOME` redirected and `GIT_CONFIG_GLOBAL`/`SYSTEM` at
`/dev/null`, so no personal git configuration can decide the outcome. The
driver is registered in the **fixture repo only** (cut B adds no repo-root
`.gitattributes`, which is exactly why the gate must register its own):

```
*.jsonl merge=loops-derived-log
merge.loops-derived-log.driver = "<python> -m store.derived_log_merge %O %A %B"
```

```
G2 — a REAL git merge in a throwaway fixture repo
  ok  the two sides genuinely diverged above a shared base
  ok  clean union: git merge exits 0 (rc=0)
  ok  clean union: the merged file is BYTE-IDENTICAL to a fresh derivation of the union
  ok  FALSE-DRIVER CONTROL: with the driver replaced by `false` the same merge FAILS (rc=1) — the driver really ran
  ok  the tampered line really differs in bytes
  ok  same id / different bytes: git merge exits NON-ZERO (rc=1)
  ok  loss against base: git merge exits NON-ZERO (rc=1)
```

The false-driver control is the one that matters and it was reproduced
independently: with the real driver the same merge is rc=0, with `false`
substituted it is rc=1. The driver genuinely ran — the clean union is not
git's textual three-way merge succeeding by luck.

Byte-identity is asserted against a fresh derivation built through engine's
own `canonical_line` + `sort_key`, so driver output and fresh derivation are
compared on the grammar's own terms rather than on a restated one.

---

## G3 — scope. **PASS**

```
$ git diff feat/arrival-libs..822c0891 --stat -- apps/
(empty)
$ git diff feat/arrival-libs..822c0891 --stat -- spec/
(empty)
$ git diff feat/arrival-libs..822c0891 --stat -- '*canonical_audit.py' '*preflight.py' \
    '*residence.py' '*probe.py' '.gitattributes' '.gitignore'
(empty)
$ git diff feat/arrival-libs..822c0891 --stat -- '**/.gitattributes' '**/.gitignore'
(empty)
```

`apps/` and `spec/` diff-empty (invariants 19, 20). `canonical_audit.py`,
`preflight.py`, `residence.py`, `probe.py`, `.gitattributes` and `.gitignore`
untouched, anywhere in the tree.

**Tracked-ness.** All 22 changed files are TRACKED — verified individually
with `git ls-files --error-unmatch`. No `.jsonl` fixture was added, so the
root's `*.jsonl` ignore (`.gitignore:9`) has nothing to silently swallow;
every derived log in the suites is generated at runtime into `tmp_path`. The
only ignored-and-present file in the tree is `uv.lock`, which is outside the
diff.

**Ruling on `libs/store/src/store/__init__.py` (+8).** IN SCOPE and correct.
The hunk is purely additive — three new names (`DerivedLogMergeConflict`,
`DerivedLogMergeResult`, `merge_derived_log`) imported and added to
`__all__`, inserted in the file's existing case-insensitive alphabetical
position. Nothing was moved, renamed or removed. Exporting the new driver
from the package is what makes `store.derived_log_merge` a first-class
maintenance operation rather than a private module, which is libs/store's
charter. (One cosmetic consequence — see finding F2.)

**Note, not a finding:** `docs/scratch/arrival-sliceB/impl-report.md` appears
with +62 inside `822c0891` rather than only in `ef1022be`. That is expected:
the implementer describes committing part of the report at B7 after the Rule
17 prose ratchet fired on it. Not scope creep.

---

## G4 — the five suites and the baseline. **PASS**, with a correction

A clean detached worktree was created by the gate at `39ea67f5`
(`/Users/kaygee/Code/loops-wt/gate-base-39ea67f5`) and given its own
`uv sync --all-packages` before any run.

| Suite | Gate @ base `39ea67f5` | Gate @ tip `822c0891` | Report's tip claim |
|---|---|---|---|
| `libs/engine/tests` | **1679 passed, 1 skipped** | **1739 passed, 1 skipped** | 1738 passed, 1 skipped, 1 failed |
| `libs/store/tests` | 131 passed | **170 passed** | 170 passed |
| `tests/architecture` | 98 passed | **98 passed** | 98 passed |
| `libs/sdk/tests` | — | **313 passed** | 313 passed |
| `apps/loops/tests` | — | **2525 passed, 1 xfailed** | 2525 passed, 1 xfailed |

Four of five reproduce exactly. The engine numbers differ from the report by
exactly one test, in both columns, and the difference is **not** a
discrepancy — it is the hypothesis corpus.

`test_fold_state_deterministic_given_append_sequence` is corpus-dependent:
it fails only where a saved example has found the shape. The gate's fresh
worktrees have no such example, so the test PASSES here and the totals read
1679/0f and 1739/0f instead of 1678/1f and 1738/1f. Same totals, same +60
delta. A raw count match would have been the wrong oracle.

**So the claim was verified by MECHANISM instead**, at the unmodified base
with zero edits applied (`git status --short` clean at `39ea67f5`):

```
$ uv run --no-sync --package engine python probe_hyp.py
DECL_GENESIS = _decl.genesis
RAISED: engine.declaration.UnadoptedLineage
MESSAGE: 1 _decl.genesis row(s) in .../store.db and no own_lineage marker — this
store predates the identity marker (or received a foreign genesis via merge). Run
`loops store adopt` to explicitly claim the store's own lineage; facts alone
cannot prove which genesis is self
```

Emitting a raw `_decl.genesis` fact through `store.append` — exactly the
shape the report names — raises `UnadoptedLineage` at the unmodified base.
The failure is pre-existing, it is reachable without any of this cut's code,
and it is unrelated to projections. The report's characterization is correct
and its refusal to claim more than it investigated is appropriate.

---

## G5 — the nine deviations

Each judged against the design fact, not against the report's own framing.

| # | Deviation | Verdict |
|---|---|---|
| 1 | `serialize_object` rebuilds field order rather than inheriting the caller's | **honest-and-correct** |
| 2 | Invariant 16 read as "absent or agreeing" | **honest-and-correct** |
| 3 | The `own_lineage` licence adds an id guard | **honest-and-correct** |
| 4 | A cut-A refusal test's match string updated | **honest-and-correct** |
| 5 | The derived-log audit is a SET comparison | **honest-and-correct** |
| 6 | The driver's union key is the ROW ID, not `(t, id)` | **honest-and-correct** |
| 7 | A pre-existing `catch_up` race fixed here | **honest-and-correct** |
| 8 | Fence departure: one stale Rule 17 allowlist entry deleted | **honest-and-correct** |
| 9 | Rule 18 allowlist gains one entry where B7 said zero | **needs-arbiter-ruling** |

**#1.** Q8 promises `serialize_object` is "byte-identical to the
`serialize_*` function that produced it". Rebuilding field order from
`_SPEC` delivers that promise unconditionally; inheriting the caller's key
order would deliver it only while a round trip happened to preserve order.
Strictly stronger, and the weaker reading was never the contract's point.

**#2 and #3.** Invariant 16 says re-derivation stamps `own_lineage`
"unconditionally" and a PRESENT disagreeing marker REFUSES. Q5's
NON-NEGOTIABLE line is narrower and governs: the stamp is licensed by *a
consumed `_decl.genesis` fact row*. "Unconditionally" distinguishes
re-derivation from catch-up (which stamps only when ABSENT), not from the
licence. The implementation refuses a disagreeing marker before anything is
cleared and stamps only what the licence permits — which is what the two
lines together require. The id guard (#3) is the licence read carefully
rather than loosely: Q5 says the stamp must not flip a store to "adopted"
that never opened a declaration lineage, and after B6 a merged log can carry
a FOREIGN `_decl.genesis` row verbatim. Without the guard the NON-NEGOTIABLE
would be violated by the cut's own merge rewrite. Correct, and a good catch.

**#4.** A refusal message changed, so the test that pinned the old string
now pins the new one — and pins the verb name rather than a substring, which
is stronger. Ordinary maintenance.

**#5.** Q2 specifies the audit literally: "hash each side's lines to 32
bytes and take two set differences." A set audit is what was ordered. Making
the writer emit unique lines keeps writer and audit on one model. The named
consequence — a line duplicated inside the file is invisible — is coherent
with the NON-NEGOTIABLE that line order and therefore multiplicity carry no
meaning. Honestly named in a finding fact rather than buried.

**#6.** Q3's table is expressed per key, and every row of it is satisfied by
keying on row id. A batch line genuinely has no single `(t, id)` — it
carries several ids — so the literal reading is not implementable for the
batch case. Q3's REJECTED list rules out "union by whole line with **no**
`(t, id)` grouping"; this is grouping, by a finer key. It additionally
catches a row that is a plain fact line on one side and rides inside a batch
on the other, which the literal reading would have admitted as a silent
duplicate. Strictly stronger, in the direction the design was arguing.

**#7.** In scope. The race is in cut A's `catch_up`, but B6 is what makes
two concurrent catch-ups routine, and the design requires a two-process
merge test that cannot pass while the race is live. The fix is the small
one: the *consume* window escalates to `BEGIN IMMEDIATE` and re-reads its
mark under it, while the already-current case stays a lock-free read so
every ordinary open is not serialized. The arrival append lock is untouched,
as Q1 requires.

### #8 — the fence departure. Verified stale, verified ratchet-demanded.

The claim is that a Rule 17 allowlist entry became stale because Q4 requires
merge.py's R1 doctrine block to be swept, and that deleting it is the
ratchet's own prescribed maintenance rather than a convenience.

The excused prose existed at base and is gone at tip:

(The excused marker text is deliberately NOT quoted verbatim anywhere in this
report — see the note at the end of this section.)

```
$ git show 39ea67f5:libs/store/src/store/merge.py | grep -n "INSERTION order"
79:        # <the R1 insertion-order comment, present at base>

$ grep -n "INSERTION order" libs/store/src/store/merge.py
(GONE at HEAD — the prose the entry excused no longer exists)
```

The gate then put the deleted entry BACK at HEAD and ran the suite:

```
E       assert not [('libs/store/src/store/merge.py', '<the R1 insertion-order marker>')]
FAILED tests/architecture/test_rule_17_fold_order_prose_is_receipt_order.py::test_allowlist_has_no_stale_entries
1 failed, 97 passed in 2.85s
```

Removed again: `98 passed`, `git diff` empty.

**A note on this report, confirming the implementer's warning.** The gate's
first draft quoted the stale marker verbatim and Rule 17 turned
`tests/architecture` RED on `gate-report.md` itself — the prose ratchet scans
`docs/scratch/`. The prescribed fix is to relabel or avoid, never to
allowlist, so the quotations above are paraphrased. The implementer's warning
was accurate and now has a second data point: **anyone writing a brief or a
report in this directory must paraphrase the retired vocabulary.**

So the entry was genuinely stale, and Rule 17's own test *forces* its
deletion — the test's docstring says "A stale entry must be DELETED, which
is the only edit direction this list allows." Net Rule 17 change is **-1**, a
shrink. The file was outside the stated edit fence, and stopping to ask
would have been defensible; but the edit is the shrink-only list's sanctioned
direction, it was disclosed, and it was emitted as a finding fact. Correct.

### #9 — the Rule 18 allowlist +1. The conflict is real; the breach is referred.

The gate reproduced the conflict independently, driving the repo's own
detector with `_ALLOWED` emptied so the shipped entry could not mask the
raw verdict:

```
'named import + named raise (what the cut needs)'  -> ["libs/store/src/store/merge.py:3: 'jsonl_canonical' — the retired canonical-store name"]
'ALIASED (the evasion the impl rejected)'          -> CLEAN

-- the REAL merge.py at HEAD, allowlist EMPTIED --
   raw faults: ["libs/store/src/store/merge.py:116: 'jsonl_canonical' — the retired canonical-store name"]
-- the REAL merge.py at HEAD, allowlist AS SHIPPED --
   faults: CLEAN
```

Three things follow, all confirmed by the gate rather than taken on report:

1. **The conflict is real.** Invariant 8 is NON-NEGOTIABLE — "jsonl targets
   REFUSE" — and merge.py cannot raise `JsonlCanonicalUnsupported` without
   naming it. Naming it trips the detector. Q9 simultaneously adds merge.py
   to `_SCAN_TARGETS` and sets B7's green criterion as "no allowlist entry
   added". The two cannot both be satisfied.
2. **The rejected escape really would have worked, and really was an
   evasion.** Aliasing the import is CLEAN to the detector while changing
   nothing about the code — precisely what the rule's own evasion probes
   exist to catch. Rejecting it was right.
3. **The excuse is minimal and the reason is honest.** The marker matches
   exactly one line of the real file:
   ```
   lines matching the marker: [116]  (count=1)
   ```
   and the docstring was reworded to describe the refusal without spelling
   the class, so the module earns exactly one excused mention. The stated
   reason — the legacy mode's own exception family, whose name IS that
   mode's honest name — is the same reasoning Q6 uses to keep the three meta
   keys unrenamed. Shrink is still zero; net is +1.

**Why this is referred rather than accepted.** A NON-NEGOTIABLE line forcing
a breach of a negotiable one is the shape of an honest deviation, and
invariant 21 is not marked [NN]. But B7's green criterion says "with **no
allowlist entry added**" verbatim, and a gate that waives a stated criterion
because the reasoning is good is a gate that waives criteria. The
implementer verified the conflict before writing code, chose the minimal
excuse, refused the evasion, and emitted a finding fact — everything short of
the ruling itself. The ruling is Kyle's.

### The finding facts

```
$ sl read project --kind finding --plain | grep -i sliceB
sliceB-catchup-stamps-absent-only                     open
sliceB-derived-log-audit-is-set-not-multiset          open
sliceB-cut-a-refusal-test-rematched                   open
sliceB-rule18-merge-refusal-needs-an-allowlist-entry  open
sliceB-catchup-race-fixed                             open
sliceB-rule17-allowlist-shrink-outside-fence          open
sliceB-driver-union-key-is-row-id-not-t-id            open
sliceB-serialize-object-rebuilds-field-order          open
```

Eight facts, not nine — and the accounting is honest in the implementer's
favour. Deviation #3 is folded into #2 by the report's own statement (it is
the same ruling read carefully, pinned by
`test_a_foreign_genesis_row_does_not_license_the_stamp`). Deviations #1 and
#6 carry facts that the report's own consolidated table marks "—", so the
table understates what was emitted (finding F4).

---

## G6 — power-proof calibration. **PASS**

The gate picked PROOF B6-c (tick chain columns stripped), not re-run in
G1/G2, and broke it with its own edit:

```python
stripped = tuple(row)  # GATE MUTATION G6: chain columns carried verbatim
```

```
=== UNDER MY MUTATION ===
E           assert 'aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa' is None
FAILED libs/store/tests/test_arrival_merge.py::test_merged_tick_carries_no_foreign_chain
1 failed, 24 passed in 0.67s

=== RESTORED: production diff ===
(empty)
25 passed in 0.33s
```

Exactly the named test, exactly one test, red under the break and green after
restore. The self-reported proof is calibrated: it measures what it claims.

---

## G7 — concurrency. **PASS**

### Six runs of the concurrent-merge test

```
run 1: 1 passed, 24 deselected in 0.19s
run 2: 1 passed, 24 deselected in 0.23s
run 3: 1 passed, 24 deselected in 0.16s
run 4: 1 passed, 24 deselected in 0.16s
run 5: 1 passed, 24 deselected in 0.16s
run 6: 1 passed, 24 deselected in 0.16s
```

6/6.

### Does the exactly-once argument hold against an ordinary APPEND?

**Yes — reasoned from the code and then probed.** Two halves, both verified
by reading rather than by report:

*The CAS pin is checked under the lock, before any byte* (`arrival.py`,
`append_marked_many`):

```python
fcntl.flock(lock_fh.fileno(), fcntl.LOCK_EX)
self._truncate_torn_tail()
head = self._tail_record()
if following is not None and head["ord"] != following:
    raise AppendRejected(...)
```

*The retry loop re-reads and re-dedups* — this is the part that matters, and
it is genuinely there (`merge.py`, `_merge_into_arrival`): `_target_state`
and `_entries_for` are both INSIDE the `for _ in range(_APPEND_ATTEMPTS)`
loop, so `continue` after an `AppendRejected` recomputes the held-id set
against the log as it now stands. A CAS that only detected staleness without
re-deduping would not be enough; this one re-derives its premise.

So the interleaving is: merger deduped at ordinal N → ordinary appender lands
N+1 → merger takes the lock, CAS sees head N+1 ≠ N, refuses → merger retries,
its re-open runs catch-up which consumes N+1, its dedup now sees that row,
and it appends only what is still missing, pinned to N+1. Exactly-once holds,
and nothing is lost.

### The gate's own probe of that case

One process appending 25 ordinary facts through `ArrivalStore.append` while
another merges a 25-row source into the same target, released together on a
barrier, six trials:

```
trial 0: merge=ok rows=53 dupes=NONE live_appends_present=25/25 -> PASS
trial 1: merge=ok rows=53 dupes=NONE live_appends_present=25/25 -> PASS
trial 2: merge=ok rows=53 dupes=NONE live_appends_present=25/25 -> PASS
trial 3: merge=ok rows=53 dupes=NONE live_appends_present=25/25 -> PASS
trial 4: merge=ok rows=53 dupes=NONE live_appends_present=25/25 -> PASS
trial 5: merge=ok rows=53 dupes=NONE live_appends_present=25/25 -> PASS

G7 RACE PROBE: PASS — no duplicate id, no lost append
```

53 rows = 3 pre-existing + 25 merged + 25 live, every trial. The log never
carried an id twice and no ordinary append was lost. The case the report
names as untested now has evidence. (It is evidence, not a proof of
impossibility — see finding F5 on the retry bound.)

---

## G8 — pyright delta. **PASS**, and the brief's two specifics are wrong

Run over `libs/engine/src/engine` and `libs/store/src/store` at both commits.

```
BASE (39ea67f5): 233 errors, 149 warnings
TIP  (822c0891): 235 errors, 149 warnings
```

Per-file, per-rule diff — the only three things that moved:

```
libs/engine/src/engine/jsonl_store.py   error  reportArgumentType          0 -> 1
libs/engine/src/engine/jsonl_store.py   error  reportOptionalMemberAccess  16 -> 15
libs/store/src/store/merge.py           error  reportArgumentType          0 -> 2
```

**Two claims in the brief do not survive checking.**

*`jsonl_codec.py:412 "unreachable" (new)` — does not exist.* There are zero
`unreachable` diagnostics at the tip, in that file or any other:
`grep -c unreachable` returns 0 on both reports.

*`jsonl_store.py` OptionalMemberAccess sites — these went DOWN, not up.* The
count fell 16 → 15. Cut A's gate classified 16 as pre-existing; cut B
resolved one of them.

**Classification of the three genuinely new diagnostics — all
pre-existing-class, none a reachable defect:**

1. `jsonl_store.py:685` — `Argument of type "Connection | None" ... in
   function "has_rows"`. This is the *same* pre-existing defect wearing a
   new rule name. `self._conn` has always been `Connection | None`; the B1
   dissolution moved the check from a method (where it read as
   `reportOptionalMemberAccess`, one of the 16) to a module function taking
   a `Connection` (where it reads as `reportArgumentType`). That is exactly
   why OptionalMemberAccess dropped by one as ArgumentType gained one. Net
   zero; the underlying `Optional` typing of `_conn` is untouched and
   pre-existing.

2–3. `merge.py:458` and `:459` — `Unknown | None` into `Entry(observer=...)`
   and `origin=...`. **False positives.** They come from untyped sqlite row
   tuples, and the schema forbids the NULL that pyright is speculating
   about:

   ```
   name         TEXT NOT NULL,
   origin       TEXT NOT NULL,
   ```

   `stripped[1]` is `ticks.name` and `stripped[4]` is `ticks.origin`, both
   `NOT NULL`. Same class as the 28 pre-existing `reportArgumentType`
   diagnostics elsewhere in these two packages.

The repo has no pyright gate on engine (233 pre-existing errors at base
confirms it), so none of this is a blocker. Recorded as finding F3.

---

## G9 — the production diff, read hunk by hunk

Read in full: `arrival_projection.py` (new, 548), `derived_log_merge.py`
(new), `merge.py`, `receive.py`, `jsonl_codec.py`, `arrival.py`,
`arrival_store.py`, `jsonl_store.py`.

**Silent behaviour changes outside the contract: none found.** Every
behaviour change traces to a numbered invariant. The sqlite merge arm is
untouched and the conformance vectors regenerate to an empty diff, which the
gate confirms is the right oracle for "byte-identical" rather than an
assertion. `receive.py`'s new guard fires only in the exact state invariant
15 names (target `.db` absent, `.arrival` sibling present) and returns
silently otherwise.

**Is the anti-pattern reintroduced under a new name?** Every direct
`facts`/`ticks` INSERT site in `libs/*/src` was enumerated:

```
arrival_projection.py:456   the re-deriver — this IS the deriving path
arrival_store.py:324        catch-up indexer — derives the index from the log
arrival_store.py:427,430    _write — stages under the same txn as the log append
jsonl_store.py:668,671,885  legacy .jsonl mode, its own cut
merge.py:164,171            inside _merge_into_sqlite — the SQLITE arm only
rebirth.py:419,425          mints a NEW store (see F1)
vertex_reader.py:2079       facts_fts, not a row table
```

No log-canonical path writes the index except by deriving it. The
anti-pattern is genuinely gone, not renamed.

**R1 residue.** `merge.py` no longer references `docs/RECEIPT_ORDER_FOLD.md`
or the R1 doctrine. The doc's R1 section reads "DISCARDED at the arrival cut
B" and its implementation-table row is gone; R2 and R3 are verbatim intact,
as invariant 22 requires. The remaining `receipt order` prose in
`vertex_reader`/`store_reader`/`witness`/`handle` is the fold-axis semantic —
R2/R3 territory, explicitly cut C's. Sweep is complete and correctly bounded.

**Vocabulary-ratchet candidates (standing review item).** The gate proposes
**no addition beyond `fold_order`**, which the design already ruled and which
the implementer added and proved. The two obvious next candidates were
checked and both fail the rule's own single-sense standard:

- `restamp` — appears at `arrival_projection.py:35` and
  `arrival_store.py:502`, both in PROSE, both using the word in its honest
  descriptive sense ("the marker is restamped from the log"). Denying it
  would fire on correct prose and require an allowlist, which is the
  verdict-claim overreach the rule's own scope note warns against.
- `rebuild` — Q9 already declined it as "a naming-consistency preference,
  not a retired model". The gate agrees.

This is the design's own discipline applied to itself, and it holds.

---

## Findings — all NON-BLOCKING

**F1 — `store/rebirth.py`'s create arm lacks the invariant-15 guard.**
`receive_store` now refuses to create a store by copy when the target's
`.arrival` sibling exists. `rebirth_store` has the same shape and no such
guard: `_create(target)` (`libs/store/src/store/_conn.py:65`) raises
`FileExistsError` only when the `.db` itself exists, and never looks at the
sibling. In the state invariant 15 names — index absent, arrival log live —
`_create` succeeds and mints a plain sqlite store at the derived-index
location of a log that holds custody. Cut B's contract names only
`receive_store`, so this is **out of scope, not a breach**; it is a gap the
cut makes newly visible. Location claim only: the gate did not construct a
rebirth transform to exploit it. Worth a follow-up alongside `rebirth.py`
joining `_SCAN_TARGETS` when custody reasoning reaches it.

**F2 — the driver's `python -m` entry emits a RuntimeWarning on every
invocation.** Because `store/__init__.py` now imports `derived_log_merge`,
running it as `python -m store.derived_log_merge` double-imports it:

```
<frozen runpy>:128: RuntimeWarning: 'store.derived_log_merge' found in sys.modules
after import of package 'store', but prior to execution of 'store.derived_log_merge';
this may result in unpredictable behaviour
```

Harmless here (the module holds no import-time state), but a git merge
driver's stderr is user-visible, so every real merge will print this once
registration rides wave 2. Cosmetic, cheap to fix then.

**F3 — three new pyright errors, all pre-existing-class.** Detailed under
G8. One is a rule-name reclassification of an untouched `Optional` field;
two are false positives contradicted by `NOT NULL` schema columns. No
pyright gate exists on these packages.

**F4 — the report's consolidated deviation table understates what was
emitted.** It marks deviations #1 and #6 as having no finding fact ("—"),
but `sliceB-serialize-object-rebuilds-field-order` and
`sliceB-driver-union-key-is-row-id-not-t-id` both exist in the store. The
error is in the conservative direction; worth correcting so the table and the
store agree.

**F5 — `_APPEND_ATTEMPTS = 8` is a liveness bound with no test at its
limit.** Acknowledged by the implementer. Correctness does not depend on it
(the gate's G7 probe shows exactly-once holds through the retry path), but a
sustained writer can exhaust it and surface a `RuntimeError` whose message
has never executed. Low priority; the failure mode is a loud refusal, not a
corrupt log.

**F6 — the doc-side residue sweep is not ratchet-enforced.** Acknowledged
and correctly reasoned by the implementer: Rule 17 allowlists
`docs/RECEIPT_ORDER_FOLD.md` wholesale on the `"(ts, id)"` marker, so
restoring R1-shaped prose there leaves the suite green. The code-side residue
IS ratcheted — Rule 17's stale-entry test is what caught merge.py's R1 prose
disappearing, which the gate reproduced in G5 #8. Declining to invent a doc
ratchet the design did not ask for is the right call; noting it as a real gap
is also right.

---

## What the gate did NOT verify

Stated so the next reader does not over-read this report.

1. **Performance.** No measurement of the O(n)-per-merge derived-log
   regeneration or the consume-forward catch-up. The implementer flags this
   too, and given this arc's O(n²) ingest history it deserves a benchmark
   before the wave ships. Not a cut B blocker.
2. **`sdk` and `apps/loops` behaviour.** Counts reproduce and `apps/` is
   diff-empty; the gate did not audit whether their behaviour depends on
   merge semantics in ways the suites miss.
3. **More than three concurrent mergers**, and no adversarial scheduling. The
   race evidence is 6/6 on the suite test plus 6/6 on the gate's own
   appender-vs-merger probe.
4. **The driver in a real repository.** It is unregistered by design (wave
   2), so both the slice's tests and the gate's proof run against purpose-built
   fixture repos.
5. **The pre-existing hypothesis failure is characterized, not diagnosed.**
   The gate established it is reachable at the unmodified base by mechanism;
   whether it is a strategy gap or a product hole is still open.

---

## Final verdict

**FINDINGS NON-BLOCKING**, with one item referred to the arbiter.

- Gate item 1 (rowid/witness ratchet): **PASS** — holds under the gate's own
  probe and goes red under the gate's own mutation, on both a written and a
  merged store.
- Gate item 2 (git merge driver): **PASS** — proven by real `git merge` in
  the gate's own fixture repo, with the false-driver control reproduced.
- Scope, suites, power-proof calibration, concurrency, pyright, diff read:
  **PASS**.
- Deviations 1–8: **honest-and-correct**. Several are strictly stronger than
  the letter of the design, in the direction the design was arguing.
- Deviation 9 (Rule 18 allowlist +1): **needs-arbiter-ruling**. The conflict
  is real and was confirmed independently; the excuse is one line; the reason
  is honest; the evasion was correctly refused. It still breaches a verbatim
  green criterion, and waiving that is not the gate's call.
- Six non-blocking findings (F1–F6), none in cut B's contract, all recorded
  above.

The work is honest. Where the report and the gate disagree it is on the
brief's pyright specifics and on the finding-fact count, and in both cases the
report is closer to right than the brief was.

```
$ git diff -- libs/
(empty)
$ git diff -- tests/
(empty)
```

Every mutation the gate made was restored exactly.
