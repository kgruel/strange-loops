# Slice 3 / WP3 implementation report — the compare-on-open seam

Branch: `slice3/wp3-seam`, off `slice3/arrival-witness` @ `9ed893fe` (WP1's landed
module, four review rounds in). Worktree `~/Code/loops-s3wp3`. Merge-base verified
`9ed893fe98703ea9c0f1888c28e7e09b6dbc8eae`.

Contract: `docs/scratch/arrival-break/slice3-wp3-brief.md`; design
`docs/scratch/arrival-break/slice3-design-proposal.md` §D, §E-WP3, §0.4; ratified fact
`design:arrival-break-slice3-witness-minimum` @ `01M17S26ZC1JFC51VEVSG4ZA67`; WP1's
module and its report's two HANDOFF sections, which are the truth where the design
proposal lags.

## READ FIRST — the flagged design point

**The `IndeterminateComparison` posture: PROCEED UNDER AN EXPLICITLY LABELED
DEGRADATION, after firing every refusal the incomplete read still soundly
supports.** `finding:s3wp3-indeterminate-posture-proceed-labeled`; the argument
lives in `AttestedLedger._degraded`'s docstring, which is written for the gate.

The short form. Framed as proceed-versus-refuse this is the two-valued classifier
the review lens warns about, and the third answer is the whole of it:

- **Refusing outright is wrong**, and WP1 already proved it one level down. An
  incomplete read is *permanent* — the journal is append-only and WP1's own
  `_torn_tail_guard` **preserves** a crashed writer's fragment rather than removing
  it, so a line lost to a crash sits in `skipped` forever. A seam refusing on it
  makes one crashed writer a store that never opens again. That is verbatim the
  argument the amended ruling used to reject refusing on mid-file damage. Refusing
  at the seam would re-impose *at the composition boundary* the verdict the module
  removed — a rule relaxed in a module, re-tightened by its caller.
- **Proceeding alone would be dishonest, and this does not.** A bound is not
  nothing, and **two of the four refusals stay sound against it and both fire**:
  a presented head *below* the bound is a rollback; a presented head at the
  bound's *ordinal with a different hash* is a same-height fork. Only the region
  at-and-above the bound is genuinely indeterminate, and the seam claims neither
  answer there.
- **Never-silent, three ways, none of them a field somebody must remember to
  read.** The degraded report is its own type with **no `outcome` attribute** —
  WP1's unignorable-by-construction discipline applied one layer up. The
  `IndeterminateComparison` *instance* `established_head()` actually raised is
  carried, which is also what proves the seam went through WP1's door rather than
  around it. And **nothing is written**: a degraded open journals no entry and
  records no binding, so the degradation never launders itself into a memory. That
  third one is also what keeps `HeadUnreadable` clear of the gate's BLOCKING-2 —
  a journal whose content is unreadable gets no bootstrap receipt, so it is never
  trusted on sight *because* it became unreadable.
- **Adversarially it costs nothing.** Anyone who can corrupt a line can delete the
  journal instead and be met with first contact, so a refusal buys nothing against
  an attacker while costing everything against a crash. The refusals that survive
  are exactly the ones damage cannot evade.

## What landed

| File | What |
|---|---|
| `libs/engine/src/engine/arrival_head_seam.py` | NEW — `AttestedLedger`, the open report types, the bootstrap/audit/trust-reset producers, staleness, the canonical location form |
| `libs/engine/src/engine/arrival_registry.py` | `open` wraps the custody half, always |
| `libs/engine/src/engine/arrival_file_backend.py` | §0.4: `FileQuery` builds its reader lazily |
| `libs/engine/tests/test_arrival_head_seam.py` | NEW — 50 tests against real stores |
| `libs/engine/tests/test_arrival_registry.py` | state-root isolation; two tests updated honestly; one added |
| `tests/architecture/test_rule_18_arrival_vocabulary_denylist.py` | `_SCAN_TARGETS` enrollment (same commit, or the glob test fails) |

Commits: `c99eae3b` the seam, `48671793` the report, `16b335a2` the fork-at-the-bound
deviation, `721dd6c6` the bound-semantics tests and their mutations, `24a2539d` the
gate's BLOCKING-1 fix, `2fd0e11e` the corrected claims and counts.

## Counts

Baseline measured on the branch point `9ed893fe`, the CI way (`uv run --package
engine pytest libs/engine/tests`, and `tests/architecture` in its own run).

| Suite | Baseline | After | Delta |
|---|---|---|---|
| engine | 2158 passed, 1 skipped | 2209 passed, 1 skipped | **+51** |
| architecture | 99 passed | 99 passed | **0** — Rule 18 is not parametrized per target |

Every delta accounted for: **+50** in `test_arrival_head_seam.py`, **+1** in
`test_arrival_registry.py` (`test_closing_a_query_that_never_read_does_not_build_a_reader`).
The last three of the fifty are the gate round's: the BLOCKING repro, the second
refusal behind the same write, and the AST ratchet.
The renamed §0.4 test is 1-for-1. `ruff check` passes on every file this WP wrote
or touched.

**Pre-existing lint, not mine:** `arrival_file_backend.py` has an unused
`collections.abc.Iterable` import. Verified present at `9ed893fe` by linting
`git show 9ed893fe:...` — recorded here so the gate does not attribute it to the
`close()` edit in the same file. Left alone as out of scope.

## Design choices

Places the design text underdetermined the code, or where the module and the
proposal disagreed and the module won.

1. **The seam is backend-neutral, and the per-backend evidence gatherer
   dissolves.** §D.3 posits "a small function beside the adapter"; it is not
   needed, because `verify(Open())`, `verify(Full(...))` and `head_at(...)` are all
   contract ops returning contract types. No wire field, no adapter type, no
   backend exception appears in the seam. Deviation, argued:
   `finding:s3wp3-evidence-gatherer-dissolves`. Cost stated at the site — the
   advance branch pays two verified walks where a backend-specific gatherer could
   have paid one, on a branch §D.3 itself argues is rare by construction.
2. **The seam never classifies WHY the ledger refused.** §D.4 needs an absent or
   empty log to branch rather than read as corruption, and the adapter says so with
   its own `GenesisRefused` — a backend exception. Importing it would drag the codec
   behind a wrapper that wraps any backend. It is not needed: WP1's
   `compare_absent_store` splits on **memory, not on the store**, so "did the ledger
   name a head" and "does the journal remember one" answer the four cells without
   asking why. A corrupt log lands on the no-head branch and lands correctly.
   See `finding:s3wp3-contract-refusal-families-unnamed`.
3. **The broad `except Exception` catches never land on an unearned proceed, and
   each says so at its site.** *Corrected per the gate's NB2 — the earlier
   wording, "every catch lands on the refusing branch", overclaimed.* Two of the
   three do: `_descent`'s catch gives `at_known = None`, which classifies REWRITE
   and refuses, and `_vouched_at`'s gives `None`, which makes a head unaccounted
   and refuses the audit. **`_present`'s catch does not** — it hands the
   absent-store split a "the ledger named no head", and that split refuses
   (`StoreLost`) only when something is remembered here; with nothing remembered
   it **proceeds** as `PreGenesis`. That is correct as designed rather than a
   leak: refusing there would make minting impossible, which is §D.4's whole
   point. What makes it safe is that proceeding on that branch claims *nothing* —
   no comparison was made, no entry is written, and the ledger's own refusal is
   carried on the report, so a corrupt log reaching this branch keeps refusing on
   its own account at every operation. The property that actually holds across all
   three is the weaker and true one: **no catch converts an unrecognized failure
   into an acceptance**, which is the silent-acceptance hazard.
4. **Ordering inside the open, and it is load-bearing at three points.** Present →
   binding (replacement must be caught before the presented lineage's journal is
   read, or the seam consults a journal that has never seen this location and
   answers first contact through the hole the binding closes) → **journal
   comparison** → **projection comparison**. Custody before projection, so an
   ahead-of-the-ledger index is never reported as a rollback it is not, and so the
   refusal an operator sees names the recovery they actually perform.
5. **No journal write precedes any refusal — and this claim was FALSE as first
   written.** *Corrected; see the BLOCKING section below.* The original build
   deferred the first-contact entry through `pending` and wrote the ADVANCE entry
   inline from `_judge`, so the claim held for one branch and not the other, and
   a refused open could and did move the witness. What makes it true now is a
   carrier rather than a promise: `_observe` returns an `_Earned` and the
   constructor's `_write` is the open path's only write site. What keeps it true
   is `test_only_the_constructor_and_the_producers_write_to_the_journal`, an AST
   ratchet with a shrink-only allowlist — a branch added later that writes inline
   fails by name. Mutation demos (e) and (h).
6. **`Compared | Indeterminate | PreGenesis`, with no uniform `.outcome`.** WP1's
   discipline carried up: the degraded case has no outcome attribute at all, and
   `PreGenesis` has no presented head, so no expression reads an answer off a
   report without first naming which case it is in.
7. **`canonical_location` is `Path.resolve()`, and it is part of the DELETE IN
   SLICE 5 unit.** Relative paths become absolute, `..` collapses, symlinks resolve
   — so two routes to one log present one binding key. Scope-the-claim: it assumes
   a location is a filesystem path, which §02 does not guarantee. Bounded and
   stated at the site — the value is only ever the binding key and the diagnostic
   `location` field, never a journal key, so a mangled DSN degrades to "no binding",
   which is first contact, the state the binding improves on rather than
   guarantees. The residual (a symlink whose target later changes is first contact
   again) is why path-keying is transitional.
8. **The audit's lookup cannot be supplied by a caller.** `unaccounted_heads` takes
   an injected `at_ordinal`, and an injection point is where a fabricated head can
   lie — a lookup answering from the journal, a cache, or the projection would
   "confirm" every entry without the store being asked anything. So `audit` accepts
   **no lookup parameter**; it builds one from `ledger.head_at`, a verified walk
   from ordinal 0, obtained through custody rather than around it. Mechanized by
   `test_the_audits_lookup_cannot_be_supplied_by_a_caller`, which pins the exact
   parameter set rather than asserting the property in prose.
9. **Delegation by explicit method, never `__getattr__`**, so `import_prefix` — a
   mutation in `LEDGER_MUTATIONS` that the Protocol does not declare — is not
   reachable through the attested handle, and neither is an op a future adapter
   adds. A behavior narrowing, flagged rather than silently taken:
   `finding:s3wp3-import-prefix-unreachable-through-the-seam`.
10. **`NotWitnessed` is deliberately NOT an `AttestationRefusal`.** Every member of
    that family means the operation did not happen; this one means the opposite —
    the data is committed and durable — so a caller catching the refusal root to
    mean "nothing changed" must not catch this. Propagating past those handlers is
    the never-silent mechanism. §05's committed-versus-witnessed distinction,
    uncollapsed.
11. **`bootstrap` admits only `MINT` or `FIRST_CONTACT`.** Every other level names
    evidence a first entry cannot have, because there was nothing before it to
    descend from. It also records the binding itself, so the canonical form is
    applied in exactly one place — a caller writing its own binding is how two
    spellings diverge.
12. **`trust_reset`'s `level` defaults to the WEAKEST claim.** A ceremony that
    verified from genesis should pass `Level.FULL`; one that took a head from an
    archive on an operator's word has proven nothing. A default that can only
    under-claim costs a later audit some work; one that over-claims is a lie the
    journal keeps forever. It also refuses an empty `reason` — recording the
    abandonment without the evidence for it is not the ceremony.
13. **Staleness is epoch-scoped**, like *K*: an audit that ran before a trust reset
    covered a history the reset abandoned. `None` means "no audit has covered this
    epoch", which is different from "the last one was long ago" — hence no age of
    infinity.
14. **`capabilities()` is delegated unchanged.** Everything it describes belongs to
    the backend holding the bytes; amending it to mention the witness would
    advertise a guarantee at the layer that does not provide it, and an over-claim
    there turns a deployment refusal into a runtime failure.
15. **The §0.4 fix moves the refusal, it does not remove it.** `FileQuery.reader`
    is built on first access, so *opening* stops requiring a projection while
    *asking for rows* still refuses with the same `FileNotFoundError` from the same
    place. Nothing creates an index — the F2 carve-out permits materialising one
    and permitted is not required. `close()` consults the field rather than the
    property, or closing would be the thing that constructs the reader the fix
    deferred.

## BLOCKING-1 — a refused open moved the witness (closed)

`finding:s3wp3-gate-advance-journaled-before-projection-refusal`. The gate was
right, and the defect was in the exact place my own design claim said it could not
be.

**What was wrong.** "Nothing writes until every refusal has had its chance" was
stated per-branch, and only one branch honored it. The first-contact entry was
deferred through `pending` and written by the constructor; the ADVANCE entry was
written *inline* from `_judge`, and `_projection` — which can refuse — runs after.
Reproduced before fixing: mint → append to 1 → open (first contact) → unjournaled
append to 3 → truncate to 2 → open ⇒ `ProjectionAheadOfLedger` raised **and** the
journal grew an `advance`/`descendant`/2 entry. The headline cell, in remembered
form: the witness permanently recorded that this machine accepted ordinal 2, at the
open that refused it, and the next open would have compared against the truncation
as though it were the accepted history.

**Why the per-branch form was the actual defect.** The rule was correct and the
first implementation of it was correct; the second branch simply did not know about
it. A rule that each branch must remember fails whenever somebody adds a branch —
which is the same shape as WP1's four-round prose lag and the same shape as the
ratchet principle: an invariant that lives only in review vigilance drifts.

**The fix, structural.** `_observe` now returns an `_Earned` for both branches and
writes nothing; `AttestedLedger._write` is the open path's single write site. The
rule is then held by
`test_only_the_constructor_and_the_producers_write_to_the_journal`, which walks the
module AST and fails any call to `append_entry`, `record_binding`, `bootstrap`,
`trust_reset` or `audit` from outside a shrink-only allowlist of six functions. A
branch added later that writes inline fails **by name**, and the fix it points at
is "return an `_Earned`", not "widen the list". The allowlist is itself checked
against the module's defined functions, so a rename cannot quietly empty it.

**The sweep the fix was scoped to — every write site against every refusal that can
follow it.** Enumerated rather than spot-checked:

| Write site | Entry | What can refuse after it | Verdict |
|---|---|---|---|
| open path, first contact | `bootstrap`/`first-contact` | `_projection`: `ProjectionAheadOfLedger`, `NotAuthority` | **was already deferred**; still deferred |
| open path, advance | `advance`/`descendant` | same two | **WAS THE DEFECT** — now deferred |
| open path, unchanged / degraded / pre-genesis | none earned | — | nothing to defer |
| `mint` | `bootstrap`/`mint` | nothing — the bootstrap is the last statement | safe |
| `append` / `replicate` → `_witness` | `advance`/`commit` | nothing — the append has already committed, which is precisely what `NotWitnessed` reports | safe |
| `audit` producer | `audit`/`full` | nothing — `verify(Full)` and the unaccounted-heads check both run *before* the append, and `AuditFoundUnaccountedHeads` replaces the entry rather than accompanying it | safe |
| `trust_reset` producer | `trust-reset` | nothing — the empty-reason refusal precedes the append | safe |

Everything upstream of the journal read (`_present`, the binding check,
`read_journal`'s own `JournalUnreadable` / `JournalEquivocation` /
`UnsafeLineageName`) refuses before any entry is earned at all, and
`days_since_audit` is pure and cannot raise.

**Both refusals behind the write are tested**, not just the one the repro used:
`test_an_advance_is_not_journaled_when_the_projection_then_refuses` (the gate's
exact repro, asserting the journal is **byte-identical** across the refused open,
and the index too) and
`test_an_advance_is_not_journaled_when_the_projection_disowns_the_log` (the
lineage-mismatch arm, where the adapter's own `NotAuthority` comes out). Mutation
(h) restores the inline write and fails all three — both behavior tests and the
ratchet.

## This seam is where bound semantics become enforced behavior

Raised by WP2's gate mid-build and folded in here. **Nothing upstream pins what a
`HeadLowerBound` may answer.** Verified in this tree rather than taken on report:

- `dir(HeadLowerBound)` has **no public names at all** — no methods, nothing that
  could refuse a misuse. It is a data carrier.
- `JournalRead.established_head()` *refuses* rather than answering on a bound, so
  the module's only comparison door is shut rather than guarded — a caller that
  goes around it meets nothing.
- WP2's `comparison` vector family is not in this tree (parallel WP, no file
  overlap), and per its gate the runner recomputes the bound arithmetic
  internally, so `compare` is never reached on a bound. The `sound_answer` field
  in those vectors is a statement *about* the semantics, not an enforcement of
  them.

So the seam is the first real consumer of bound semantics and, today, the only
place they are executable. Two behaviors are therefore load-bearing here and each
now has its own test **and its own mutation demo**, rather than resting on the
posture tests that happen to cover them:

| Rule | Test | Mutation |
|---|---|---|
| A bound MAY refuse below itself | `test_an_incomplete_read_still_refuses_a_head_below_the_bound` | (f) |
| A bound may NOT answer `unchanged` or `advanced` | `test_an_incomplete_read_proceeds_labeled_at_or_above_the_bound`, `test_an_incomplete_read_does_not_answer_advanced_above_the_bound` | (g) |

The gap this closed was real: mutation (c) — the *obtaining* bypass, re-deriving
*K* from `read.epoch` — leaves the rollback-from-a-bound test **passing**, because
the re-derived head is the same entry the bound rests on. (c) attacks how a caller
gets a head; (f) and (g) attack what the bound is allowed to say once it has one,
and only the latter two hold the semantics. The `advanced` half in particular had
no dedicated test before this: "below the bound is a rollback" is easy to believe
and get right, while "above the bound is an advance" *feels* equally safe and is
the unsound one, since nothing bounds the accepted head from above.

`HeadUnreadable` needs none of this. It carries no ordinal by construction, so
every comparison declines including rollback, and
`test_a_journal_with_no_readable_content_is_not_granted_a_receipt` pins the
consequence that matters.

## The defect the gate item found — and it was found by running it

`finding:s3wp3-open-compares-across-time`, resolved in build.

The concurrent-writer scenario WP1 suggested and the brief carried was not a
formality. Two writer processes appending through `AttestedLedger` while a third
opened produced a **`HeadRollback` on a store that had never rolled back**: the
opener's `verify(Open())` observed ordinal 6, then read a journal that by then
held ordinal 7 written by a peer's journaling-on-commit. The compare-on-open
compares **two files read at two different moments**, and a peer's commit in that
interval is bit-for-bit indistinguishable from a rollback.

This is not exotic. Multi-process-on-one-host under an advisory flock is the
concurrency this backend *advertises* in `capabilities()`, and the symptom is an
operator told their store lost data because two ordinary writes overlapped.

It is WP1's write-path lesson at the next layer up. There, a **read rule** closing
a hazard was reopened by a **write path**; here a **comparison rule** closed at
read time is reopened by somebody else's write **between the two reads**. Every
one of WP1's journal read rules is sound and none of them can see this, because
the defect is not in either file — it is in the interval.

**The fix**: the refusing observation must not be older than the journal. When the
presented head sits below what the journal already knows, the store is asked once
more and the fresher answer is classified. One extra constant-time tail read, on
the descending branch only — the dominant unchanged case pays nothing, and the
branch that pays is the one about to accuse an operator of losing data.
Terminating rather than a retry loop, and the residual window **fails safe**: a
writer committing after the re-read is invisible to the journal read that preceded
it, so its only effect is to make *K* lower than reality, which classifies
unchanged or advanced and pays a verified walk — never a false refusal.

A genuine rollback is stable across both reads and survives, pinned separately by
`test_a_genuine_rollback_survives_the_re_observation` so that the fix could not
have been "stop refusing rollbacks".

## Oracle results

**1. The item that matters (§E.1).**
`test_a_truncated_log_with_an_index_ahead_refuses_and_leaves_the_index_alone`:
a store truncated to ordinal 1 with an index still accounting for ordinal 3 opens
through the registry, refuses with `ProjectionAheadOfLedger`, **and the index file
is byte-identical afterwards** (sha256 before/after). Deliberately with no journal,
so the projection evidence stands entirely on its own — the only signal available
on a store this machine has never seen. Two companions:
`test_the_refused_truncation_left_no_memory_claiming_it_was_accepted` (the refused
open wrote no bootstrap receipt — the ordering invariant) and
`test_a_truncation_below_a_remembered_head_refuses_as_a_rollback` (the same
truncation on a remembered store answers with the custody claim first, index still
untouched, journal not advanced).

**2. Classification against real stores.** Every row, against real minted logs with
real sqlite projections: first contact (labeled, receipt written), unchanged,
advanced (verified walk, journaled at `DESCENDANT`), rollback, same-height fork,
rewrite (with the refused store asserted to `verify(Open())` cleanly — the refusal
is about continuity, not integrity), lineage replaced via the binding, and the
binding matching through a non-canonical path. **O(1) proved by evidence gathered,
not wall clock**: `test_an_unchanged_open_gathers_only_the_open_verification`
asserts the recorded op list is exactly `["verify:open"]` — `head()`, `read()`,
`scan()` and `verify(Full)` all walk, so their absence *is* the claim.

**3. Journaling on commit.** `test_an_append_through_the_wrapper_journals_its_commit`
(entry at `ADVANCE`/`COMMIT` carrying `commit.after`);
`test_commit_then_open_takes_the_o1_path_not_the_advance_path` (op list is exactly
`["verify:open"]` — unchanged, not advanced). **Concurrent-writer run**:
`test_two_writers_and_an_opener_leave_a_parseable_journal` spawns two writer
processes and one opener process against one lineage. Verified independently that
contention is real — 40 records land from two processes, 43 journal lines (header
+ 40 commits + 3 racing first-contact bootstraps), all independently parseable, the
read is complete (`skipped == ()`), and the journal's established head equals the
store's actual head. The test asserts both writers landed their full round count
and that the head equals their sum, so a run where only one writer ever wrote fails
rather than passing vacuously. This is the run that found the across-time defect.

**4. The §0.4 fix.** `test_opening_a_store_whose_projection_is_absent_now_succeeds`
— a minted log with no index opens, `ledger.head()` answers, `projected_through()`
reports `None` rather than guessing, and `query.reader` **still** raises
`FileNotFoundError`. The WP4 finding's pinning test was updated **honestly**: it was
born as its own negation, recording observed behavior rather than a policy anyone
chose, and the rename plus the retained-refusal assertions say exactly what changed
and what did not. `test_closing_a_query_that_never_read_does_not_build_a_reader`
covers the trap of moving the refusal into `close()`.

**5. The IndeterminateComparison posture.** Six tests, listed in the finding.
`test_the_carried_refusal_is_the_one_the_journal_itself_raises` is the one that
proves the seam went through `established_head()` rather than around it.

**6. Mutation demos** — below.

**7. Suites green, counts reconciled, `git ls-files` clean.** Above and below.

### Mutation demos

Each applied to the working tree, the suite run, the mutation reverted, and
`git diff --quiet` verified clean before the next.

| # | Mutation | Result (46 tests) |
|---|---|---|
| (a) | journaling-on-commit dropped from `_witness` | **7 or 8 failed** — see the note below — led by `test_commit_then_open_takes_the_o1_path_not_the_advance_path` (the next open observes an ADVANCE and pays two walks) and `test_an_append_through_the_wrapper_journals_its_commit`; also the `NotWitnessed` test and the race pin |
| (b) | `canonical_location` returns the location unchanged | **1 failed, 69 passed** (with the registry file) — `test_the_binding_matches_through_a_non_canonical_path`: the replacement goes undetected and the store is trusted on first contact |
| (c) | the seam swallows `IndeterminateComparison` by re-deriving *K* from `read.epoch` — the bypass WP1 explicitly named as reachable | **3 failed, 43 passed** — `test_an_incomplete_read_proceeds_labeled_at_or_above_the_bound`, `test_a_journal_with_no_readable_content_is_not_granted_a_receipt` (a receipt is written for an unreadable journal — BLOCKING-2 reborn), `test_the_carried_refusal_is_the_one_the_journal_itself_raises` |
| (d) | the across-time re-read removed | **2 failed, 44 passed** — `test_a_commit_racing_the_open_is_not_reported_as_a_rollback` and `test_a_genuine_rollback_survives_the_re_observation` (which pins the op count, so the fix cannot be faked by weakening the refusal) |
| (e) | the earned bootstrap entry written inside `_observe`, before the projection comparison can refuse | **1 failed, 45 passed** — `test_the_refused_truncation_left_no_memory_claiming_it_was_accepted` |
| (f) | the rollback-from-a-bound arm removed from `_degraded` | **1 failed, 46 passed** — `test_an_incomplete_read_still_refuses_a_head_below_the_bound` |
| (g) | the bound treated as an established head, so the seam answers from it | **4 failed, 43 passed** — `test_an_incomplete_read_proceeds_labeled_at_or_above_the_bound` (answers `unchanged`), `test_an_incomplete_read_does_not_answer_advanced_above_the_bound` (answers `advanced`), plus the receipt and carried-refusal tests |
| (h) | the pre-fix inline ADVANCE write restored in `_judge` | **3 failed, 47 passed** — `test_an_advance_is_not_journaled_when_the_projection_then_refuses`, `test_an_advance_is_not_journaled_when_the_projection_disowns_the_log`, and the AST ratchet `test_only_the_constructor_and_the_producers_write_to_the_journal` |

**Mutation (a)'s failure SET is nondeterministic, and the earlier "5 failed" was a
single observation reported as though it were stable** (the gate's NB1). Measured
over five runs: seven failures every time, plus
`test_two_writers_and_an_opener_leave_a_parseable_journal` in one run of the five.
The cause is structural rather than flakiness in the fix — with
journaling-on-commit dropped, the concurrent run's journal holds only whatever
ordinal the *opener* process happened to observe at first contact, so its
`established.head == head` assertion passes exactly when the opener is scheduled
after both writers finish. The conclusion is unchanged and does not rest on that
test: the two deterministic catchers fail on every run, and the concurrency test
is a bonus catcher rather than a load-bearing one. Recorded because a mutation
demo reporting one sampled count as a fact is the same defect class as prose
asserting an enforcement the code does not perform.

(b) and (c) each also have a mirror pinned: (b)'s canonical form is asserted
directly through `bound_lineage(canonical_location(detour))`, and (c)'s two sound
refusals are pinned separately from its proceed branch, so a mutation resolving the
posture toward blanket refusal fails
`test_an_incomplete_read_proceeds_labeled_at_or_above_the_bound` while one
resolving it toward blanket proceed fails the rollback and fork tests.

## Test isolation

Every test in both touched suites runs under an autouse fixture pointing
`$XDG_STATE_HOME` at `tmp_path`. **The registry suite needed one added**: slice 3
made `BackendRegistry.open` compare on open, so every pre-existing test there that
opens a store now reads — and on first contact writes — a head journal. Without the
fixture the suite would have written into the developer's real
`~/.local/state/loops`. Autouse rather than per-test, because one forgotten opt-in
is invisible until after it has happened.

`test_the_state_root_is_redirected_for_this_suite` asserts the redirection itself,
so a fixture that silently stopped applying fails loudly instead of leaving every
other test writing to the real root. Verified empirically after every full-suite
run: `~/.local/state/loops` does not exist.

## Deviations

1. **The per-backend evidence gatherer was not built** — it dissolves into three
   contract ops. `finding:s3wp3-evidence-gatherer-dissolves`, argued above.
2. **`import_prefix` is not reachable through the attested handle** — a deliberate
   narrowing, flagged for slice 5's rewiring:
   `finding:s3wp3-import-prefix-unreachable-through-the-seam`.
3. **One behavior fix beyond the brief's scope**, self-caught by a gate item and
   fixed in build: the across-time comparison
   (`finding:s3wp3-open-compares-across-time`). Not a module change — WP1's module
   is untouched.
4. **`.at_least` is used for one refusal beyond ROLLBACK, and this is a declared
   extension of brief item 7.** The brief says "`.at_least` is ROLLBACK-ONLY"; the
   seam also raises `HeadFork` when the presented head sits at the bound's ordinal
   with a different `record_hash`. Stated plainly so the gate rules it rather than
   discovers it.

   Why it is inside the handoff's actual rule. WP1's rule is about which **answers**
   a bound may license: "it may be compared to refuse a presented head below it,
   and it may **never be used to answer `unchanged` or `advanced`**." Both
   forbidden answers are *proceed* answers, and the reason is stated in
   `HeadLowerBound`'s docstring — nothing bounds the accepted head from above, so
   equal-may-be-a-rollback and higher-may-be-below-a-lost-entry. A fork refusal is
   neither: `at_least` is a real entry that survived the read and passed
   `_known_of`'s equivocation check, so it *is* a head this machine accepted at
   that ordinal, and a store presenting a different record at that same ordinal is
   two records at one height. The lines the read missed cannot make that agree,
   because they carry no information about **this** ordinal that could reconcile
   two different hashes at it.

   And it fails in the safe direction: the extension is strictly *more* refusing,
   so a wrong call here costs an operator a false incident, never a silent
   acceptance — the opposite of the direction every other rule in this module
   guards. If the arbiter prefers the literal reading, deleting the fork arm in
   `_degraded` is a four-line removal and `test_an_incomplete_read_still_refuses_a_fork_at_the_bound`
   is the test that would go with it; nothing else depends on it.

   **`HeadUnreadable` needed no such judgment and got none** — it carries no
   ordinal by construction, so every comparison declines, rollback included. That
   half is honored exactly as written.

**No module changes.** `arrival_head_attestation.py` is byte-identical to
`9ed893fe`; everything WP3 needed from it was already on its API, including
`refusal_for`, `unaccounted_heads`, `JournalRead.skipped` and the
`established_head()` refusal the handoff named.

## Findings emitted

| Fact | What |
|---|---|
| `finding:s3wp3-indeterminate-posture-proceed-labeled` @ `01M181V303MA4RVMG4H3XFXEV6` | **the flagged design point**, chosen with its argument |
| `finding:s3wp3-open-compares-across-time` @ `01M181TDTDABT9YAREQAGF9ZKD` | the false-rollback race; found by the gate item, fixed in build |
| `finding:s3wp3-contract-refusal-families-unnamed` @ `01M181VZ7WBAHV29TC0122KZAT` | `head_at` and `verify(Open())` refuse with backend-native exceptions; a contract gap for slice 5 |
| `finding:s3wp3-evidence-gatherer-dissolves` @ `01M181VZDXS806VPHW5V36B4AE` | deviation from §D.3, with its cost stated |
| `finding:s3wp3-import-prefix-unreachable-through-the-seam` @ `01M181WC800RA81DVZXBRFZTYR` | deliberate surface narrowing, for slice 5 to rule |

## Left for later, named rather than papered over

- **The audit's cost.** One verified walk per journaled epoch head. Named at the
  site with its forcing consumer (a store whose epoch holds enough entries to
  notice) rather than pre-paid with a backend-specific single-walk table.
- **`protocol`/`wire` in the journal header are still written and never read** —
  WP1 named this and it is still open; its forcing consumer is wire v2, and the
  seam does not close it because nothing here can.
- **A location with no log but an index holding a watermark** reads as pre-genesis:
  the index is inside the rewrite boundary the witness exists to sit outside, so it
  is not treated as memory. Consistent with the threat model, noted because it is
  the one place a reader might expect the projection to testify.
- **The `bindings.jsonl` unit and `canonical_location`** carry the same DELETE IN
  SLICE 5 marker and the same sweep obligation as WP1's half and the registry's
  transitional inference arm.
