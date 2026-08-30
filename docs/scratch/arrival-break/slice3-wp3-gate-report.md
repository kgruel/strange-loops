# Slice 3 / WP3 gate report — the compare-on-open seam

Gate branch `slice3/wp3-seam-gate`, worktree `~/Code/loops-s3wp3-gate`, fresh
`uv sync --all-packages`. **Target: `slice3/wp3-seam` @ `721dd6c6`** (4 commits over WP1's
`9ed893fe`). Everything below was re-run from scratch against that tip; the implementation
report was read from git bytes and treated as the target of review, not as evidence.

**Verdict at that tip: GATE: FAIL** — one BLOCKING finding. Eight of the nine oracle items
pass on their own evidence; item 8 fails on one sub-claim, and it is a sub-claim the report
and the module docstring both state as structural.

> **SUPERSEDED — see the re-check at the end of this document.** BLOCKING-1 was closed at
> `8c9a88cf`, verified by this gate against its own repro. **Final verdict: GATE: PASS**,
> with three non-blocking findings carried.

## Anchor

The gate was launched against `16b335a2` and re-anchored onto `721dd6c6` mid-run, after the
tip moved to absorb the arbiter's WP2-gate-NB1 closure. The diff between them touches
**only two files** — confirmed:

```
docs/scratch/arrival-break/slice3-wp3-report.md
libs/engine/tests/test_arrival_head_seam.py
```

No source file changed; `arrival_head_seam.py` is byte-identical across the two tips. Every
number below is from a run at `721dd6c6`. The BLOCKING finding was found at `16b335a2` and
re-verified at `721dd6c6`; because it is a property of unchanged source, it carries
forward untouched.

## The Oracle, item by item

### 1. The headline item (§E gate item 1) — **PASS**

Truncated log + stale-ahead index → typed refusal with the index bytes unchanged.
Byte-compared by the gate independently, not by reading the impl's assertion:

```
[ITEM 1] refusal: ProjectionAheadOfLedger
[ITEM 1] index sha before: 9a337de5053e3b3b9a23fdad66d7d088125b76cfe5bddca052dd3106816be781
[ITEM 1] index sha after : 9a337de5053e3b3b9a23fdad66d7d088125b76cfe5bddca052dd3106816be781
[ITEM 1] size before/after: 53248 53248
[ITEM 1] journal still absent after the refusal: True
```

sha256 identical, size identical, full `read_bytes()` equality asserted. Detection precedes
repair, and the no-journal framing is right: the projection evidence stands on its own on a
store this machine has never seen. The journal is still absent afterwards, so this cell also
leaves no memory — see item 8 for the cell where that does not hold.

### 2. Compare-on-open against real stores, all cells — **PASS**

Verified with the gate's own op-recorder against real minted logs with real sqlite
projections, not the suite's `Recorder`:

| Cell | Evidence |
|---|---|
| unchanged | ops **exactly `['verify:open']`**, outcome `unchanged` |
| advanced | ops `['verify:open', 'verify:full', 'head_at']` — the two walks §D.3 specifies |
| rollback | `HeadRollback` |
| same-height fork | `HeadFork` |
| first contact | `bootstrap`/`first-contact` written |
| replacement | `LineageReplaced`, including through a `..` detour path |

**The O(1) path is proved, not asserted.** `head()`, `read()`, `scan()` and `verify(Full)`
all walk, so their absence from the recorded op list is the claim. After a commit through
the wrapper the next open gathers only `verify:open`. Mutation (a) (journaling-on-commit
dropped) makes `test_commit_then_open_takes_the_o1_path_not_the_advance_path` fail
**deterministically — 5 of 5 runs** — so the walk cost is genuinely what the test detects.

Mutation (b) confirmed: `canonical_location` returning the location unchanged fails exactly
`test_the_binding_matches_through_a_non_canonical_path` (1 failed, 46 passed), i.e. the
replacement goes undetected and the store is trusted on first contact.

### 3. Journaling on commit and the concurrent-writer scenario — **PASS** (one NON-BLOCKING note)

Append through the wrapper produces an `advance`/`commit` entry carrying `commit.after`;
the next open takes the O(1) path. An unchanged open writes **zero** journal bytes
(byte-compared before/after).

**The across-time race, reconstructed as instructed.** Mutation (d) — the re-observation
removed from `_not_older_than_the_journal` — fails both named pins every run:

```
FAILED test_a_commit_racing_the_open_is_not_reported_as_a_rollback
FAILED test_a_genuine_rollback_survives_the_re_observation
```

Restored, both pass. The second is what stops the fix from having been "stop refusing
rollbacks": it pins the op count, so a weakened refusal fails it.

The live concurrent test (two writer subprocesses + one opener subprocess) was run **8
times unmutated: 8 passes**, and its non-vacuity assertions are real — both writers must
land their full round count and the store head must equal their sum, so a run where one
writer never wrote fails rather than passing quietly.

**Residual window, characterized by the gate.** The store is observed at T1, the journal
read at T2, and the re-observation happens at T3 > T2, so the refusing observation is never
older than the journal. A writer committing between T2 and T3 is visible to the fresh store
read but not to the journal read, so *K* is lower than reality — that classifies advanced,
pays a verified walk, and journals a descendant entry. A writer committing after T3 is
invisible to both and is simply the next open's advance. Neither direction can manufacture
a refusal, so the window fails safe as claimed. The `fresh is None` fallback (line 743)
keeps the stale head if the store vanishes mid-open, which also refuses rather than
proceeding.

### 4. The IndeterminateComparison posture — **PASS**

The arbiter acceptance is confirmed at source: `finding:s3wp3-indeterminate-posture-proceed-labeled`
@ `01M182CC5H52YE7E8SKKN0ESD7`, `status=fixed`, `agent=arbiter`, ending "Gate verifies."

All four sub-claims hold:

- **Its own type with no `outcome` attribute.** Adversarially attempted: one expression
  reading `report.comparison.outcome` across a normal and a degraded report. Normal answers
  `Outcome.FIRST_CONTACT`; degraded raises
  `AttributeError: 'Indeterminate' object has no attribute 'outcome'`. No outcome is
  reachable uniformly.
- **Carries the actual instance.** `Indeterminate.refusal` is the `IndeterminateComparison`
  `established_head()` raised, which is what proves the seam went through WP1's door rather
  than around it.
- **Nothing is written on the degraded path.** Confirmed, and mutation (c) — the seam
  swallowing the refusal by re-deriving *K* from `read.epoch`, the bypass WP1 named as
  reachable — now produces **four** failures at this tip (three at `16b335a2`; the added
  bound test catches it too):
  `test_an_incomplete_read_proceeds_labeled_at_or_above_the_bound`,
  `test_an_incomplete_read_does_not_answer_advanced_above_the_bound`,
  `test_a_journal_with_no_readable_content_is_not_granted_a_receipt` (a receipt written for
  an unreadable journal — BLOCKING-2 reborn), and
  `test_the_carried_refusal_is_the_one_the_journal_itself_raises`.
- **Both sound refusals still fire against a bound.** See item 5.

### 5. The `.at_least` fork extension, and NB1's enforcement point — **PASS**

Arbiter acceptance confirmed at source: `finding:s3wp3-at-least-fork-extension` @
`01M182CCC35GZJWTZYR40ZW5DZ`, which amends WP1's handoff spelling from ROLLBACK-only to
**REFUSALS-only-from-a-bound** and ends "Gate verifies the soundness argument at source."
The three legs of that argument check out in the module:

1. **`at_least` is genuinely equivocation-checked.** `HeadLowerBound.at_least` is
   `_known_of(epoch)` (`arrival_head_attestation.py:937-942`), and `_known_of` raises
   `JournalEquivocation` when the maximum-ordinal entries carry more than one distinct
   `record_hash` (`:810-820`). So a bound that survives the read is a head this machine
   accepted at that ordinal, singular.
2. **Append-only means a missed line cannot un-accept it.** A skipped line can only add an
   entry, never remove one, so nothing the read missed carries information that reconciles
   two different hashes at the bound's ordinal.
3. **The proceed answers stay unobtainable at the seam.** Verified adversarially (item 4)
   and by mutation, below.

**The NB1 enforcement work at `721dd6c6`, verified rather than taken on report.**

`test_an_incomplete_read_does_not_answer_advanced_above_the_bound` was read and is sound: a
store advances to ordinal 3 while the bound sits at 1, and it asserts `Indeterminate` (not
advanced), `presented.ordinal == 3`, `at_least.ordinal == 1`, **and** that the journal bytes
are unchanged — so the bound cannot be raised on evidence the read did not have. That write
assertion is the half that matters most, and it is present.

Both mutations re-run by the gate, restores byte-clean:

| Mutation | Gate's result | Impl's claim |
|---|---|---|
| (f) rollback arm removed from `_degraded` | 1 failed, 46 passed — `test_an_incomplete_read_still_refuses_a_head_below_the_bound` | 1 failed, 46 passed ✓ |
| (g) bound treated as an established head, so the seam answers from it | 4 failed, 43 passed — **both forbidden proceed answers** (`..._proceeds_labeled_at_or_above_the_bound` answers `unchanged`; `..._does_not_answer_advanced_above_the_bound` answers `advanced`), plus the receipt and carried-refusal tests | 4 failed, 43 passed ✓ |

The impl's diagnosis of the gap is also correct and the gate confirms it independently:
mutation (c) attacks how a caller *obtains* a head and leaves the rollback-from-a-bound test
**passing**, because the re-derived head is the same entry the bound rests on. (f) and (g)
attack what the bound may *say* once it has one. Before `721dd6c6` the gate had constructed
its own arm-drop mutations for exactly this reason and reached the same conclusion; the
landed (f) is identical to the gate's, and the landed (g) is the stronger answer-side form.
**WP2-gate-NB1 is satisfied.** No finding.

**Characterized, not a finding:** a *missed `TRUST_RESET` line* mis-scopes the epoch, so the
bound may be a head an operator deliberately abandoned, yielding a false fork or a false
rollback. This is strictly-more-refusing and is exactly the same class of exposure the
already-accepted rollback arm carries, so it is consistent with the arbiter's "fails
strictly safe" and adds nothing new for the fork arm to answer for.

### 6. §0.4, the lazy reader — **PASS**

A minted log with no index opens through the registry; `ledger.head()` answers ordinal 0;
`query.projected_through()` and `query.lineage()` report `None` rather than guessing;
`query.reader` **still** raises `FileNotFoundError` on access; and after
open + `projected_through()` + the refused `reader` + `close()`, **the index file does not
exist** — nothing materialises a projection. `close()` consults the field rather than the
property, so closing an unread query does not construct the reader the fix deferred.

**The two touched registry tests were diffed and the update is honest.**
`test_opening_a_store_whose_projection_is_absent_refuses` → `..._now_succeeds`: the
`pytest.raises(FileNotFoundError)` assertion is **retained and moved to `query.reader`**,
where the refusal actually lives now, and three assertions are added. Strengthened, not
weakened. `test_a_registered_opener_is_what_open_calls` drops
`registry.open(descriptor) == ("L","Q")` — an equality that also happened to pin the absence
of a wrapper, which is the one claim this WP legitimately invalidates — and replaces it with
the claim the test was written to make (`calls == [descriptor]`), plus `query == "Q"` and
the wrapper/report type checks. One test added
(`test_closing_a_query_that_never_read_does_not_build_a_reader`). The report's "two updated,
one added, +1 net" is accurate.

### 7. Remaining mutation demos — **PASS**

Re-run by the gate at `721dd6c6`, each applied to the working tree, suite run, reverted, and
`git diff --quiet` verified clean before the next.

| # | Mutation | Gate's result |
|---|---|---|
| (a) | journaling-on-commit dropped from `_witness` | 4–5 failed (see NON-BLOCKING-1); the two named leads fail every run |
| (b) | `canonical_location` returns the location unchanged | 1 failed, 46 passed |
| (c) | seam swallows `IndeterminateComparison` via `read.epoch` | 4 failed, 43 passed |
| (d) | across-time re-read removed | 2–3 failed (see NON-BLOCKING-1); both named pins fail every run |
| (e) | earned bootstrap written inside `_observe` | 1 failed, 46 passed — `test_the_refused_truncation_left_no_memory_claiming_it_was_accepted` |
| (f) | rollback arm removed from `_degraded` | 1 failed, 46 passed |
| (g) | bound treated as an established head | 4 failed, 43 passed |

Every restore byte-clean.

### 8. Design-choice audit — **FAIL** (BLOCKING-1); every other sub-claim passes

| Sub-claim | Verdict | Evidence |
|---|---|---|
| Delegation by explicit method, no `__getattr__` | PASS | `"__getattr__" not in vars(AttestedLedger)`; `FileLedger` **does** have `import_prefix` (so the check is not vacuous) and `AttestedLedger` does not expose it |
| Audit's lookup non-injectable | PASS | `inspect.signature(audit).parameters` = `['ledger','presented','epoch','projection','location','observed_at']` — no lookup, no `at_ordinal` |
| `NotWitnessed` outside `AttestationRefusal` | PASS | MRO is `NotWitnessed → Exception → BaseException`; `ProjectionAheadOfLedger` **is** in the refusal family, so the split is deliberate rather than accidental |
| Custody before projection | PASS | An ahead-of-ledger index on a **remembered** store refuses as `ProjectionAheadOfLedger`, never as `HeadRollback` |
| **No journal write precedes any refusal** | **FAIL** | BLOCKING-1, below |
| WP1's module byte-identical to `9ed893fe` | PASS | `git diff --quiet 9ed893fe 721dd6c6 -- libs/engine/src/engine/arrival_head_attestation.py` is clean |

### 9. Counts, lint, artifacts, isolation — **PASS**

- **engine: 2206 passed, 1 skipped** at `721dd6c6` — matches the amended report (+48 over
  the `9ed893fe` baseline of 2158+1s).
- **architecture: 99 passed**, run separately.
- **ruff**: clean on every touched file except one error in `arrival_file_backend.py`
  (`collections.abc.Iterable` imported but unused). **Verified pre-existing** by linting
  `git show 9ed893fe:libs/engine/src/engine/arrival_file_backend.py` in isolation — the same
  F401 at the same line. Correctly attributed and correctly left alone.
- **`git ls-files`**: all seven changed paths tracked; **zero** `.loops/` paths across the
  four commits.
- **Isolation**: `~/.local/state/loops` did **not** exist before the runs and does **not**
  exist after the full engine suite. Autouse `XDG_STATE_HOME` fixtures are present in
  **both** touched suites (`test_arrival_head_seam.py:80`, `test_arrival_registry.py:42`),
  and the seam suite asserts the redirection itself. The gate's own probe tests carried
  their own fixture rather than relying on inheritance.

## Findings

### BLOCKING-1 — a refused open journals an acceptance on the advance branch

`finding:s3wp3-gate-advance-journaled-before-projection-refusal` @ `01M183A80E5Z5FR6EJ3159K135`

The module docstring states, as a structural property rather than a discipline:

> **No refusal is raised after a journal write, and no journal write happens before every
> refusal has had its chance.** `AttestedLedger._observe` is pure with respect to the
> journal — it RETURNS what should be written and writes nothing.

Report design choice #5 repeats it: "a store that passes the journal comparison and then
fails the projection one leaves no memory claiming its head was accepted."

**This is true only for the `FIRST_CONTACT` bootstrap entry.** That one is deferred through
the `pending` tuple and written by `__init__` after `_observe` returns. The `ADVANCED`
branch is not deferred: `_judge` calls `append_entry(kind=ADVANCE, level=DESCENDANT)`
**directly** (`arrival_head_seam.py:882-891`) and returns; `_observe` then evaluates
`self._projection(presented)` (line 699), which raises `ProjectionAheadOfLedger` (line 1090)
when the watermark sits above the presented head. So `_observe` is not pure with respect to
the journal, and an open that refuses can have already written an acceptance.

**Reproduced** with real stores through the registry path, at both tips:

1. mint; legacy-append to ordinal 1;
2. open through the registry → first contact, journal `[bootstrap/first-contact/1]`;
3. legacy-append to ordinal 3 — unjournaled, which is §D.3's **ordinary** slices-3-4 write
   path, so the cell is not contrived — building the index through 3;
4. truncate the log tail back to ordinal 2;
5. open through the registry.

```
before: [('bootstrap', 'first-contact', 1)]
after : [('bootstrap', 'first-contact', 1), ('advance', 'descendant', 2)]
journal bytes changed by the REFUSED open: True
```

`ProjectionAheadOfLedger` is raised and the journal has grown. This is the WP's own headline
cell — a truncated log with a stale-ahead index — in its remembered form.

**What this is not.** The ADVANCE entry is not false: descent was verified (`verify(Full)`
then `head_at`) before it was written. The defect is that a **refused open mutates the
witness**, which is the property the ordering exists to provide and which the report states
as structural. Nothing in the suite reaches it: the companion
`test_the_refused_truncation_left_no_memory_claiming_it_was_accepted` proves the property
for `FIRST_CONTACT` only, and mutation (e) only guards bootstrap-in-`_observe`.

Note the symmetry with the work `721dd6c6` just landed: the new bound test asserts zero
journal bytes precisely because "journaling a `DESCENDANT` entry at the presented head would
raise the bound on evidence the read did not have." The degraded path was given that
guarantee; the advance path still lacks it.

A second refusal path sits behind the same write: `_projection`'s lineage-mismatch branch
(line 1075) lets `head_at`'s `NotAuthority` out, also after the ADVANCE entry has landed.

**Fix shape** (the gate does not repair): carry the ADVANCE entry in `pending` exactly as
the bootstrap entry already is, so the constructor performs both writes after `_observe`
returns without raising. That makes the docstring's claim true as written rather than
narrowing it.

**Scope.** This does not touch item 1 (the no-journal headline cell passes on its own
evidence), does not touch the arbiter-accepted posture (the degraded path genuinely writes
nothing), and does not touch custody-before-projection ordering (verified separately).

### NON-BLOCKING-1 — the concurrent subprocess test is an intermittent participant in the mutation demos

The report records mutation (a) as "**5 failed**, 41 passed" and mutation (d) as "**2
failed**, 44 passed". Neither count is reproducible, and the variable member of both is
`test_two_writers_and_an_opener_leave_a_parseable_journal`:

| Mutation | Gate's observed spread |
|---|---|
| (a) | 5 failures in 2 of 5 runs, 4 in the other 3 |
| (d) | 3 failures in 3 of 6 runs, 2 in the other 3 |

The cause is structural rather than flakiness in the green state (8/8 passes unmutated, full
suite green). Mutation (a) removes journaling from `_witness` only, and the opener
subprocess's own `ADVANCED` branch still journals, so whether the journal's established head
ends up equal to the store's final head depends on whether the opener's last open lands
after the writers finish. The same timing decides whether the concurrent run notices (d).

Both demos' conclusions are unaffected — the deterministic failures kill each mutation on
their own, led by the tests the report names first — so this is reporting precision, not a
coverage hole. Recorded because the concurrent test's value is asserted in the report partly
on having caught these mutations, and because a future reader re-running the table will see
different numbers.

### NON-BLOCKING-2 — `_present`'s broad catch reaches a proceeding branch, and design choice #3 rounds that off

Design choice #3 opens "The broad `except Exception` catches are sound in exactly one
direction, and each says so", then lists `_present`'s as "a ledger that names no head takes
the absent-store split". The split proceeds as `PreGenesis` when the location has no memory,
so this catch does **not** land on a refusing branch the way the other two do — an
`AttributeError` from a malformed ledger becomes a successful pre-genesis open.

Observable in the repo's own suite: `test_a_registered_opener_is_what_open_calls` passes the
string `"L"` as a ledger and gets `PreGenesis` back.

Not blocking, and arguably not a defect: §D.4 requires the no-memory branch to proceed or
minting is impossible, `PreGenesis.ledger_refusal` carries the exception so the branch is
labeled rather than silent, and `_present`'s own docstring describes the behaviour
accurately. The finding is against the *summary* in the report, which generalises three
catches into one direction that only two of them have.

## Verdict

Per-item: 1 PASS, 2 PASS, 3 PASS, 4 PASS, 5 PASS, 6 PASS, 7 PASS, **8 FAIL**, 9 PASS.

The work is strong and unusually well-argued. Both flagged design points survive
verification at source, and the NB1 enforcement landed at `721dd6c6` is real work that
closes a real gap — the gate independently reached the same diagnosis before reading it. The
failure is narrow and specific: a structural claim the report and the module docstring both
make is true for one of the two branches that write, and the untrue half lands on the same
truncated-log cell the WP was built to detect.

**GATE: FAIL**

---

# Re-check at `8bd992b3` — BLOCKING-1 only

Scope of this round, per the gate's instruction: **only BLOCKING-1**. Nothing else reopens.
Gate worktree reset onto `8c9a88cf`, then onto `8bd992b3` when the tip moved once more.

**Result: BLOCKING-1 is CLOSED.** One new NON-BLOCKING finding on the ratchet's reach.

The behavioral evidence below was gathered at `8c9a88cf` and **re-run in full at
`8bd992b3`**; every result is identical. `8bd992b3` is a prose round — see the anchor note
at the end of this section.

## Diff scope — confirmed

`721dd6c6..8c9a88cf` is three commits (`24a2539d` the fix, `2fd0e11e` the count
corrections, `8c9a88cf` the landed table) touching exactly three files:

```
docs/scratch/arrival-break/slice3-wp3-report.md
libs/engine/src/engine/arrival_head_seam.py
libs/engine/tests/test_arrival_head_seam.py
```

The seam module, its tests, and the report. Nothing else.

## The fix, and the shape it took

`_observe` now returns an `_Earned` carrier and `AttestedLedger._write` is the open path's
single write site; the `ADVANCED` branch **returns** its entry instead of calling
`append_entry` inline. `_write` routes a bootstrap through `bootstrap()` rather than
straight to `append_entry`, so the canonical-form application stays on one path — the right
call, since a second spelling of the binding key is how the two diverge.

This is the structural form, not a per-branch repair: the rule is now carried by the return
type rather than restated in each branch.

## Evidence

| Check | Result |
|---|---|
| **The gate's own repro** (unchanged from the finding) | **PASSES.** Journal bytes identical across the refused open — `before: [('bootstrap','first-contact',1)]`, `after: [('bootstrap','first-contact',1)]`. The `advance/descendant/2` entry this gate demonstrated is **gone.** |
| Index bytes across the same refused open | identical (the impl's test asserts both; the gate re-ran its own) |
| `test_an_advance_is_not_journaled_when_the_projection_then_refuses` | passes |
| `test_an_advance_is_not_journaled_when_the_projection_disowns_the_log` (the `NotAuthority` arm) | passes — real ledger, doubled query half, `ContractRefusal` raised, journal unchanged |
| `test_only_the_constructor_and_the_producers_write_to_the_journal` | passes |
| **Mutation (h)** — inline write restored | **3 failed, 47 passed:** both behavior tests **and** the ratchet. Restore byte-clean. |
| Engine suite | **2209 passed, 1 skipped** — reconciles (+51 over the 2158+1s baseline; +3 this round) |

The second refusal path I named in the finding (`_projection`'s lineage-mismatch arm letting
`NotAuthority` out) was enumerated and tested rather than left to be found later. The sweep
table in the impl report covers every write site against every refusal that can follow it,
and the reasoning for `mint`/`_witness` is right: `_witness` runs after the append has
already committed, which is precisely what `NotWitnessed` exists to report, so there is
nothing refusable left to protect.

## Attacking the ratchet

The gate tried to slip an inline write past the AST matcher at the exact site the fix moved.
Two controls, five evasions; for each, the ratchet and the two byte-compare behavior tests
were asked separately.

| Spelling | Ratchet | Behavior tests |
|---|---|---|
| plain `append_entry(...)` — the fixed bug's own spelling | **CAUGHT** | CAUGHT |
| helper defined outside the allowlist calling `append_entry` | **CAUGHT** | CAUGHT |
| `from ... import append_entry as _ae` → `_ae(...)` | MISSED | CAUGHT |
| `from . import arrival_head_attestation as _aha` → `_aha.append_entry(...)` | MISSED | CAUGHT |
| module-level rebinding `_w = append_entry` → `_w(...)` | MISSED | CAUGHT |
| `getattr(_aha, "append_entry")(...)` | MISSED | CAUGHT |
| local rebinding inside the method | MISSED | CAUGHT |

Both controls are caught — including the helper-indirection case, which is the one that
matters most, since "extract a helper" is the ordinary refactor that would otherwise walk a
write out of the allowlist. Every evading spelling is caught by the behavior tests.

**The rot guard works as claimed.** Renaming `AttestedLedger._write` to `_commit_earned`
makes the stale-allowlist assertion fire. The allowlist cannot silently empty itself.

## NON-BLOCKING-3 — the ratchet detects direct-name calls, and its claim should say so

The matcher requires `ast.Call` with `func` an `ast.Name` whose `id` is in the writing set.
Any spelling that reaches the same function through an alias, an attribute, or `getattr`
is invisible to it. On today's code that costs nothing — every such spelling is caught by
the byte-compare behavior tests, and the realistic spellings are caught by the ratchet
itself.

The residual is the case the ratchet exists for: **a branch added later, which has no
behavior test yet**, written in an evading spelling. And its sharpest form is not
adversarial at all — it is a routine refactor. Switching the module to attribute-style
imports (`_aha.append_entry(...)`), a style change nobody would flag in review, makes the
ratchet **pass with zero offenders while every write site in the module is invisible to
it.** Verified: the ratchet goes green and stays green.

The only incidental tripwire is
`test_a_journal_write_failure_after_a_commit_says_the_records_are_committed`, which
monkeypatches `append_entry` in the module namespace and therefore breaks under that
refactor — but it reads as "fix the patch target", not as "the ratchet is now blind."

**Recommended disposition: scope the claim, do not widen the matcher.** Chasing aliases,
attributes and `getattr` grows a detector that will still never be complete, which is the
overreach the house rule warns about. The precise fix is one assertion: that each name in
the writing set is bound as a module-level `Name` (i.e. imported directly), so the
precondition the AST match depends on **fails loudly** the moment it stops holding. That
keeps the ratchet's claim ("no direct-name journal write outside the allowlist") true and
makes its blind spot unreachable without a test failing. The docstring should say
direct-name calls rather than implying it catches every write.

Not blocking: the defect it guards is fixed and behaviorally pinned, the ratchet catches
the spellings a person would actually write, and this is a claim-precision issue on a
defense-in-depth layer.

## Anchor note — the prose round at `8bd992b3`

The tip moved once more while this re-check was being written. `8bd992b3` touches two
files, the report and the seam module, and the module change is **prose only** — confirmed
mechanically rather than by reading the diff:

> Both revisions of `arrival_head_seam.py` were parsed, every docstring node stripped, and
> the resulting trees dumped and compared. **AST identical: True.** Comments do not appear
> in the AST at all, so the executable structure of the module is unchanged.

The change itself is an addition to `_Earned`'s docstring framing the degraded-path and
refused-path zero-write guarantees as one hazard — *a journal entry recording a head this
open did not actually establish* — closed one way down two branches. That is the same
symmetry this gate raised when it filed the finding, and stating it at the carrier is
where it belongs.

**Everything re-run at `8bd992b3`, all identical:** the gate's own repro (journal bytes
unchanged across the refused open), the three guard tests, mutation (h) at 3 failed / 47
passed with a byte-clean restore, engine at 2209 passed / 1 skipped, and
`~/.local/state/loops` still absent.

### NB-1's corrected counts check out, and they correct this gate too

The report's re-measured ranges — **(a) 4 or 5**, **(d) 2 or 3**, with 4 and 2
deterministic respectively — match this gate's independent measurements exactly ((a): 5 in
2 of 5 runs, 4 in 3; (d): 3 in 3 of 6, 2 in 3). The intermediate "7 or 8" is correctly
retracted as an artifact of a contaminated window.

More usefully, the per-demo causes are now separated, and **the (d) cause corrects this
gate's own NB-1**, which had generalized one mechanism across both demos. Verified here
rather than accepted: under (d) the concurrent test fails on `assert proc.returncode == 0`
because the opener subprocess raised the false `HeadRollback` the re-read exists to
prevent — observed in 4 of 6 runs, with the refusal text naming a store presenting ordinal
*n* against a remembered *n+1*. That is a materially better signal than the bookkeeping
coincidence this gate described: under (d) the concurrent test is not a lucky extra
catcher, it is a third process actually reproducing the defect. NB-1's substance stands —
neither demo's conclusion rests on an intermittent member — but its explanation of (d) was
wrong and the report's is right.

## Verdict

**BLOCKING-1: CLOSED.** The behavior is fixed, the fix is structural rather than
per-branch, the gate's own repro passes, the second refusal arm is covered, and mutation
(h) demonstrates all three guards firing together.

Carrying forward, all non-blocking: NB-1 (the concurrent subprocess test is an intermittent
participant in the mutation demos — now corrected in the impl report), NB-2 (design choice
#3's characterization of `_present`'s catch — now corrected in the impl report), and NB-3
above.

**GATE: PASS**
