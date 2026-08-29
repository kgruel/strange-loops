# Slice 3 / WP1 implementation report — the head-attestation module

Branch: `slice3/arrival-witness` (created off `main` @ `4c4bf148`, which includes the
design proposal at `1a29f200`). Worktree `~/Code/loops-s3wp1`.

Contract: `docs/scratch/arrival-break/slice3-wp1-brief.md`; design
`docs/scratch/arrival-break/slice3-design-proposal.md` §B, §C, §E-WP1; ratified fact
`design:arrival-break-slice3-witness-minimum` @ `01M17S26ZC1JFC51VEVSG4ZA67`.

## What landed

| File | What |
|---|---|
| `libs/engine/src/engine/arrival_head_attestation.py` | the record, the journal, the classifier, the refusal family, the transitional binding |
| `libs/engine/tests/test_arrival_head_attestation.py` | 87 unit tests |
| `tests/architecture/test_rule_18_arrival_vocabulary_denylist.py` | `_SCAN_TARGETS` enrollment (same commit as the module, or the glob test fails) |

## Counts

Baseline measured on `main` @ `4c4bf148`, the CI way (`uv run --package engine pytest
libs/engine/tests`, and `tests/architecture` in its own run — running both in one
process produces 29 cross-suite pollution failures on a clean tree, so it is not a
usable baseline):

| Suite | Baseline | After | Delta |
|---|---|---|---|
| engine | 2063 passed, 1 skipped | 2150 passed, 1 skipped | **+87**, all in `test_arrival_head_attestation.py` |
| architecture | 99 passed | 99 passed | **0** — Rule 18 is not parametrized per target, so enrolling a module adds no case |

Every delta accounted for. `ruff check` passes on both new files. (`ruff format` would
reflow them, but it reflows `arrival_contract.py` and `arrival_registry.py` too — the
repo does not enforce it on engine and CI lints only `libs/custody libs/sign`, so the
new files match their neighbors' hand-wrapping.)

## Design choices

Each of these is a place the design text underdetermined the code. None contradicts it;
where one refines a literal reading, the reason is stated.

1. **The trust epoch is reset-INCLUSIVE.** §B.3 rule 0 says "the read scope is the
   entries after the last one". Read literally, a journal *ending* in a trust-reset has
   an empty epoch, `K` is `None`, and the next open classifies `first-contact` — silent
   re-acceptance, the deadlock's mirror image. §E's WP1 exit disambiguates it ("the next
   open classifies against the reset head"), so the reset entry is the first entry of
   the epoch it opens. Pinned by `test_the_epoch_includes_the_reset_entry_itself`.
2. **`compare` keeps exactly seven rows; the §D.4 store-absent split is a separate
   function** (`compare_absent_store`) returning a separate `AbsentStoreOutcome` enum.
   Folding pre-genesis and store-lost into `Outcome` would make "the seven rows" WP2
   pins mean nine, and the absent-store question is asked before there is a head to
   present.
3. **Classifier guard order: known-is-None, lineage, full equality, then ordinal.**
   Lineage precedes ordinal arithmetic because heights across two lineages are unrelated
   number lines — reversed, a lower ordinal in a foreign lineage would answer `rollback`
   and send an operator looking for a backup of an uninvolved lineage. `at_known` is
   consulted only on the ascending branch, so the dominant unchanged case pays nothing.
4. **`bindings` is a reserved lineage name**, case-folded. `bindings.jsonl` and
   `<lineage>.jsonl` share one directory, so a lineage literally named `bindings` would
   write head observations into the binding file; case-folded because the filesystems
   this runs on are commonly case-insensitive.
5. **The reader identifies a header by the absence of `kind`, not by being line 1.**
   Two writers racing `O_CREAT|O_EXCL` can each land a header, so "line 1 is the only
   header" is not a property the reader may assume. Duplicate-entry tolerance sets the
   precedent.
6. **SUPERSEDED at `66df1e71`** — was "torn-line policy split", refusing damage above the
   last line. The refutation and the amended ruling are in their own section below. Every
   unreadable line is now skipped and reported wherever it sits, and the loss is carried
   in the read's type as `HeadLowerBound` rather than converted into a verdict.
7. **Skipped lines are reported on `JournalRead.skipped`**, not logged. A tolerated loss
   nobody is told about is just a loss; a field lets WP3's seam surface it without this
   module inventing a logging dependency.
8. **`protocol`/`wire`/`v` are literals with a comment, not imports.**
   `engine.arrival.GRAMMAR_VERSION` exists but importing it would drag the file codec
   into a module whose readability must not depend on the store's health — and the
   journal grammar versions independently of the record grammar anyway.
9. **Unknown *fields* need no code.** The journal is append-only and never rewritten, so
   fields this build does not name are preserved on disk by construction; the reader
   ignores them. That satisfies "preserved-and-ignored" without adding a field to the
   ratified record shape (§B.2's "nothing else").
10. **An entry from a later build — unknown `kind`, `level`, or `v` — is skipped and
    reported, never refused.** §B.3 requires that a later build's journal not make an
    older build refuse to compare. Degrading to a shorter view of the same history is
    honest; refusing outright would brick every older build against a shared journal.
11. **`Outcome`/`Kind`/`Level` are plain `Enum` with string values**, matching
    `arrival_contract.Profile`/`VerificationLevel`. The vectors pin `.value`, which is
    what "outcomes are strings" asks for; a `str` mixin would have departed from the
    sibling module for no gain.
12. **Four refusals beyond §C.2's five.** `UnsafeLineageName` is demanded by §A.3
    ("a typed refusal naming the lineage"); `StoreLost` is §D.4's "it must refuse";
    `JournalUnreadable` is structural damage; `IndeterminateComparison` is what makes the
    cheap shortcut unobtainable. All root in `AttestationRefusal`.
13. **`REFUSALS`/`refusal_for` — the outcome-to-refusal table lives in this module.**
    So WP3's seam does not re-implement the posture, and "which outcomes refuse" is one
    enumerable fact rather than a chain of `if`s in whatever calls the classifier.
14. **`unaccounted_heads(epoch, at_ordinal)` ships here with the lookup injected.** WP1's
    exit requires the audit's all-journaled-heads check not to fail on pre-reset entries,
    which needs the pure check at this level; injection keeps the neutral module from
    reaching for a backend or `canonical_audit` (D.5's own discipline).
15. **`state_root()` honors `XDG_STATE_HOME` only** — not `LOOPS_HOME`. `LOOPS_HOME`
    overrides the *config* root, and the whole threat-model argument is that state is not
    config; honoring it would let one variable move the memory back on top of the stores.
16. **A new journal's header and first entry land in one write** (`O_CREAT|O_EXCL`), with
    plain `O_APPEND` thereafter. A create race is cheaper to survive on read than to
    prevent on write — but see 17: the create must still carry `O_APPEND`.
17. **Every open carries `O_APPEND`, the exclusive create included** (fixed at
    `444f6b3b`). Without it the creating writer's descriptor sits at offset zero, so a
    writer that *lost* the create race can land a complete entry there first and have it
    overwritten. The journal would silently forget a head, and a later restore to the
    surviving ordinal would classify `unchanged` — the failure the maximum-ordinal read
    rule exists to close, reached through the write path instead.
18. **An append guards the line boundary** (same commit). A crash mid-append leaves a
    fragment with no trailing newline; appending onto it glued the next entry into that
    fragment, losing the new entry's bytes inside one unreadable line. The design
    promises a torn tail costs at most the newest observation, so a crash plus one
    commit must not cost the next one. `os.write`'s return is checked too — a short
    write is a torn line this process inflicts on itself.

## Deviations

**None from the brief's scope, oracle, or mechanics.** Two of the choices above depart
from a *literal* reading of the design prose, both arguing from the design's own exit
criteria, and both carry a finding fact so the gate and WP2 see them rather than
discovering them in a vector:

- `finding:s3wp1-epoch-scope-is-reset-inclusive` @ `01M17T5E7QNH221ZH9T05TJ5BH` —
  choice 1. **WP2 action:** vectors built from §B.3's literal wording would pin
  `first-contact` where the design wants `unchanged`.
- `finding:s3wp1-mid-file-journal-damage-unstated` @ `01M17TJQGWVVH3HZCKC9N1WQ8N`
  (sharpened; first entry `01M17T5EGH8K3ZJCWK3MFMV3XB`) — choice 6. **Arbiter action:**
  rule the policy. The sharpened entry carries the fact that changes the question: the
  mid-file case is reachable from an ordinary crash, not only from tampering, so the
  choice is whether a crash plus one commit escalates to a permanent incident. Three
  options are laid out there; the narrowest tolerates only a line that is a *prefix* of
  a well-formed entry.

One further finding records work that needed no ruling:

- `finding:s3wp1-journal-write-path-faults` @ `01M17TJQRND8G62YFXH7G5RWFG` — choices 17
  and 18, self-caught and fixed in build at `444f6b3b`. Its general form is worth
  carrying into WP3: **a read rule that closes a hazard can be reopened by the write
  path**, because the reader only ever judges bytes that survived the write. Gate item 5
  byte-compares an unchanged open; a concurrent-writer scenario deserves the same
  treatment.

Completion fact: `observation:implementation/arrival-slice3-wp1-head-attestation` @
`01M17T4S61XZ8Q3ST4P8QWQBYV`.

## Notes for WP2 and WP3

- **WP2: no comparison vector shape changes.** `compare`'s signature and its seven rows
  are untouched by the lower-bound work — the change is entirely in how a caller *obtains*
  the `known` argument. Vectors still supply `input.known` as an entry and pin
  `expected.outcome` as the state string. WP2 consumes `parse_journal_lines` (pure, raw
  lines in) and `compare` (pure); pin `Outcome(...).value`, not the enum members. One new
  input shape worth a vector if the family covers journal reads: a journal with an
  unreadable line yields a bound rather than a head. `AbsentStoreOutcome` is a separate enum
  on purpose — see choice 2 — so decide deliberately whether the family covers it.
- **WP3 seam contract, amended.** The seam calls `JournalRead.established_head()` to get
  its `compare` argument. On an incomplete read that call **raises**
  `IndeterminateComparison`, and the seam must handle it rather than route around it: a
  bound can still refuse anything below itself, but it cannot license proceeding. Note
  what does NOT work — gathering evidence from the store does not resolve the
  indeterminacy, because a walk verifies the store's chain while the missing fact is about
  what this machine previously accepted. Proceeding therefore needs an operator decision
  (journal repair or the trust-reset ceremony) or an explicitly labeled degradation; that
  posture is WP3's to choose and is worth a gate item. WP3 also gets `refusal_for()`
  (choice 13) so the seam does not re-implement the posture table,
  `unaccounted_heads(epoch, at_ordinal)` for the audit producer, and `JournalRead.skipped`
  for surfacing tolerated losses.
- **Open and named, not built:** the header's `protocol`/`wire` values are written but
  never read. §B.3 says a journal written under wire v1 must not be silently compared
  against a v2 head whose hashes derive differently, and today nothing enforces that. Out
  of WP1's scope as ruled; it belongs wherever wire v2 lands. `append_entry` returns the
  journal path, and raises `OSError` outward — journal write failure is the caller's to
  surface, never swallowed (§D.4).
- **`bindings.jsonl` matches `location` as an exact string.** The seam must pass one
  canonical form — the descriptor's resolved location — or a symlinked or
  relative path manufactures a first contact through the hole the binding exists to
  close. WP3's to handle; named here so it is not discovered at the gate.
- Nothing in this module reads the clock. `observed_at` is a caller-supplied argument
  everywhere, which is what keeps staleness reporting (WP3's) testable without freezing
  time here.

## Oracle results

1. **Suites green, counts reconciled** — see the table above.
2. **Import closure** — `test_reading_a_head_journal_does_not_drag_the_adapter_in`
   spawns a clean subprocess, imports the module, *and* calls `parse_journal_lines`,
   asserting neither `sqlite3` nor `engine.arrival` is in `sys.modules` either time.
   Pinned the WP1-slice-2 way (`test_importing_the_registry_does_not_drag_the_adapter_in`).
3. **Rule 18** — module auto-enrolled by name; `test_every_arrival_named_engine_module_is_scanned`
   green with the `_SCAN_TARGETS` entry, and the whole architecture suite green at 99.
4. **Mutation demos** — below.

### Mutation demos

Each mutation applied to the working tree, the suite run, the mutation reverted, and
`git diff` verified empty before the next one.

| # | Mutation | Result (77 tests) |
|---|---|---|
| (a) | classifier: the rollback arm returns `Outcome.UNCHANGED` | **2 failed, 75 passed** — `test_lower_ordinal_is_rollback` (`assert <Outcome.UNCHANGED: 'unchanged'> is <Outcome.ROLLBACK: 'rollback'>`) and `test_out_of_order_journal_writes_still_catch_a_restore` |
| (b) | trust-epoch scoping: `_epoch_of` returns all entries (the epoch filter dropped) | **6 failed, 71 passed** — `test_after_a_trust_reset_the_known_head_is_the_reset_head` (K reads 100, the abandoned head), `test_after_a_trust_reset_the_restored_store_opens_unchanged` (the deadlock: `rollback` forever), `test_the_epoch_includes_the_reset_entry_itself`, `test_only_the_latest_reset_opens_the_current_epoch`, `test_equivocation_is_scoped_to_the_current_epoch`, `test_the_audit_check_does_not_fail_on_pre_reset_entries` |
| (c) | journal read rule: `_known_of` returns `epoch[-1]` instead of the maximum-ordinal entry | **2 failed, 75 passed** — `test_the_known_head_is_the_maximum_ordinal_not_the_last_line` and `test_out_of_order_journal_writes_still_catch_a_restore` (a genuine restore to 5 classifies `unchanged`) |
| (d) | write path: `O_APPEND` dropped from the exclusive create (choice 17 reverted) | **1 failed, 79 passed** — `test_a_create_race_does_not_overwrite_the_other_writers_entry` |
| (e) | write path: `_torn_tail_guard` always returns `""` (choice 18 reverted) | **1 failed, 79 passed** — `test_a_torn_tail_does_not_glue_itself_to_the_next_entry` |
| (i) | the refusal on unreadable lines restored (amended ruling reverted) | **7 failed, 80 passed** (87-test suite) — every tolerate test, led by `test_damage_anywhere_is_tolerated_and_reported` and `test_the_deadlock_scenario_opens_cleanly_now` |
| (ii) | `HeadLowerBound` collapsed into a plain `EstablishedHead`, making the state ignorable | **8 failed, 79 passed** — including `test_an_incomplete_read_cannot_classify_a_restore_as_unchanged`, the cannot-claim-unchanged test the ruling named |

Demos (a)-(c) were measured against the 77-test suite before the write-path fix; (d) and
(e) against the 80-test suite after it. The three classifier and read-rule mutations are
unaffected by that fix — it touches neither `compare` nor `_epoch_of`/`_known_of`.

Each mutation is caught by the test written for it, naming the outcome; (a) and (c) are
each also caught by a second test stating the operator-visible consequence, and (b) is
caught across all three surfaces the epoch scope governs (K, equivocation, the audit).
After each restore `git diff` was verified empty, and the suite is back to 80 passed.

## Mid-file damage — refutation, amended ruling, and what was built

The lead ruled TOLERATE AND REPORT for mid-file damage, conditional on verifying in code
that within a trust epoch journaled ordinals ascend, so that a mid-file skip cannot lower
*K* while a later well-formed entry survives. **The invariant does not hold, so per the
ruling's own instruction the change was not applied.** Recorded as
`finding:s3wp1-epoch-ordinals-do-not-ascend-in-file-order` @ `01M17TT02KN9XBWE1AWCJB159Q`.

It fails for the reason this module documents in its own read rule 1. §B.3 rule 1 exists
*because* ordinals do not ascend in file order: "two writers append concurrently (the
arrival flock serializes their *appends*, not their journal writes), so lines can land
out of order: A commits ordinal 5, B commits 6 and journals it, A journals 5 last."
`append_entry` does no ordinal validation and cannot — the ordering it would have to
enforce is exactly the ordering the design says the journal does not have. No exotic kind
is needed; the plain `advance` path breaks it, and `audit` is a second instance, since
§D.5's producer journals the head the audit *covered*, which a concurrent advance can
already have exceeded.

Verified against the real module. One epoch, journal in file order `[90 trust-reset, 92,
91]`, true `K = 92`. Damage the ordinal-92 line — mid-file, with a later well-formed
entry surviving after it — and tolerate-and-report yields `K = 91`. A store presenting 91
after a genuine restore from 92 then classifies `unchanged` where the truth is
`rollback`: the silent re-acceptance the journal exists to prevent, and the same failure
the maximum-ordinal rule was written to close. A mid-file skip therefore *can* lower `K`,
and it is not strictly safer than the torn tail.

### The amended ruling, and what it changed

The lead accepted the refutation and amended the ruling to option (c), adding one
requirement: the weakened state must be **unignorable by construction** in the read's
type — not a boolean beside a plain `K` that WP3's seam could forget to consult. Built
at `66df1e71`:

- `JournalRead.known` is now `EstablishedHead | HeadLowerBound | None`. The weakened case
  has **no `entry` attribute at all** — its field is `at_least` — so there is no
  expression that reaches a comparable head without naming which case it is in.
- `JournalRead.established_head()` is the only way to obtain a `compare` argument, and it
  raises `IndeterminateComparison` on an incomplete read. The cheap "presented equals `K`,
  therefore unchanged" shortcut is **unobtainable**, not discouraged.
- A bound still answers `rollback` soundly (below the bound is below `K`), which is the
  one comparison it can make.
- **`compare`'s signature is untouched**, so no WP2 vector shape changes.

Two corrections to my own option (c) as originally worded, both now in the type's
docstring. First, "the seam gathers evidence instead" is **wrong as a repair**: a walk
verifies the store's own chain, and the missing fact is about what this machine
previously *accepted*, which the store never knew. Evidence gathering cannot resolve the
indeterminacy — only journal repair or the trust-reset ceremony can, and both are
operator work. Second, an unreadable line carries **no** information about the ordinal it
held, so the readable entries bound `K` from below and nothing bounds it from above; that
is why `advanced` is unsound against a bound too, not only `unchanged`.

### What dissolved

The positional torn-tail-versus-mid-file distinction is **gone**, and with it choice 6.
Position was only ever a proxy for "is this a crash artifact", and it was a bad one —
a fragment becomes mid-file the moment one commit follows it. Every unreadable line is
now skipped and reported wherever it sits, and the read rule no longer consults an index.

`JournalUnreadable` survives, rescoped to structural damage that breaks the read itself:
**entries with no header**. The header states the protocol and wire versions the record
hashes derive under, so without it a comparison is not a weaker answer but a meaningless
one. That made one write-path case reachable — a creator that won the exclusive create
and died before writing leaves an empty file — so an append now supplies the header when
it finds one, and a crashed creator cannot strand a journal headerless.
