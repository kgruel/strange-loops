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
| `libs/engine/tests/test_arrival_head_attestation.py` | 94 unit tests |
| `tests/architecture/test_rule_18_arrival_vocabulary_denylist.py` | `_SCAN_TARGETS` enrollment (same commit as the module, or the glob test fails) |

## Counts

Baseline measured on `main` @ `4c4bf148`, the CI way (`uv run --package engine pytest
libs/engine/tests`, and `tests/architecture` in its own run — running both in one
process produces 29 cross-suite pollution failures on a clean tree, so it is not a
usable baseline):

| Suite | Baseline | After | Delta |
|---|---|---|---|
| engine | 2063 passed, 1 skipped | 2157 passed, 1 skipped | **+94**, all in `test_arrival_head_attestation.py` |
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
10. **RE-SCOPED at `1df5c8f4`.** An entry from a later build is skipped and reported,
    never refused **on its own account** — that half survives verbatim and is what keeps
    a shared journal from bricking an older build. What the promise never licensed is the
    stronger reading it was written as: that a comparison holding **zero** readable
    evidence should proceed. Declining there refuses no entry; it declines a question
    nothing left in the journal can answer. See the gate section below.
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
- **`.epoch` and `.entries` permit uniform `K` re-derivation.** §C.4's audit needs the
  raw entries, so they are exposed and a caller *could* recompute a maximum from them
  and bypass the bound. The unignorable-by-construction guarantee is therefore scoped to
  the `known` / `established_head()` pair, which is the path a comparison takes; the
  entry sequences are evidence for the audit, not a comparison surface. Non-blocking, and
  named so WP3 does not re-derive `K` by hand.
- **WP3 must treat `HeadLowerBound.at_least` as ROLLBACK-ONLY.** Implied by the type's
  docstring, explicit here: it may be compared to refuse a presented head below it, and
  it may never be used to answer `unchanged` or `advanced`. `HeadUnreadable` has no
  ordinal at all, so it answers nothing.
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


## Gate round 1 — two blocking findings, both closed at `1df5c8f4`

Both sat **upstream of the lower-bound type split**: in deciding whether a line was lost
at all, not in what the read does once it knows. The type design itself survived the
gate's adversarial shortcut attempt, and the epoch scoping, write-path fixes, refusal
rooting and test isolation all passed and are unchanged.

### BLOCKING-1 — a kindless dict was absorbed as a header

`finding:s3wp1-gate-kindless-dict-absorbed-as-header`. The reader treated **any** dict
without `kind` as a header and skipped it recording nothing. On the same out-of-order
journal that refuted the ascending-ordinal invariant, replacing the epoch maximum's line
with `{}` produced an `EstablishedHead` at the surviving ordinal, an **empty** `.skipped`,
and a comparison of `unchanged` where the truth is a rollback. The amended ruling's
"skipped and surfaced wherever it sits, never silently" defeated through a second byte
pattern — same demonstration as before, two different bytes.

Headers are now identified by **shape** rather than by "is it kindless". **The sentence
that first replaced it — "identified by type alone" — overclaimed, and sol r1 broke it;
the honest spelling is the three-way rule below.** The create-race two-headers test stays
green throughout.

### BLOCKING-2 — content present, nothing readable, silent trust-on-first-use

`finding:s3wp1-gate-all-entries-unreadable-silent-tofu`, ruled. Content present with
nothing readable (`skipped > 0`, epoch empty) fell through to `known = None` and was
answered with first contact — a journal trusted on sight *precisely because* it had become
unreadable.

That is a **third state, not the absence of one**. An empty journal says nothing was ever
accepted here, and TOFU is the honest answer to it. Unreadable content says heads *were*
accepted and their ordinals are exactly what was lost. `HeadUnreadable` carries no ordinal
by construction, so unlike a lower bound it cannot answer even `rollback` — every
comparison declines. First-contact TOFU now requires a journal with no surviving-or-skipped
content claims; a header-only journal still qualifies, and has its own test.

§B.3's forward-compatibility promise **re-scopes rather than breaks** (choice 10 above,
and the docstrings): individual later-build entries are skipped and reported, never refused
on their own account; a comparison holding zero readable evidence declines, which refuses
no entry. The version-skew consequence is stated openly rather than hidden — an older build
against a purely newer journal declines its comparisons, and resolution is operator work
(run the newer build, or the trust-reset ceremony).

### Third item

`HeadLowerBound.__doc__` completed with the second half of my own self-correction, which
the gate found missing: nothing bounds the accepted head from **above**, so a presented
head above the bound is not an advance either. Both proceed answers are unobtainable
without naming the case; only the refusal below the bound survives.

### Gate-round mutation demos

| # | Mutation | Result (91 tests) |
|---|---|---|
| (1) | kindless dicts absorbed as headers again | **2 failed, 89 passed** — `test_a_kindless_dict_is_not_absorbed_as_a_header`, `test_a_header_naming_another_type_is_not_this_journals_header` |
| (2) | the `HeadUnreadable` arm removed, so `known` falls through to `None` and TOFU | **3 failed, 88 passed** — `test_a_journal_of_nothing_but_later_build_entries_declines`, plus the two other reads that hold only unreadable content |


## Sol-LOW round 1 — the three-way classification rule (`9b616e28`)

`finding:s3wp1-sol-l1-header-classification-three-way`, blocking, and the fix was ruled
three ways because the obvious repair has a mirror hazard. Everything else passed,
including a two-process 2×2000-observation concurrency run that produced 4001
independently parseable lines, and the equivocation seeds.

**What broke.** Classification required the type marker **and** the absence of `kind`. A
later build's header carrying a `kind` of its own was therefore unrecognized, fell through
to the entry path, was skipped — and then the file was refused for holding entries with no
header. An uncontracted version-skew refusal of the whole journal. My tests only covered
headers with *added* fields, never one whose added field was named `kind`.

**Why type-alone is not the fix.** It would let a future ENTRY that happens to carry the
type marker be absorbed as a header, silently — the kindless-dict failure of BLOCKING-1
reborn from the other side. The two obvious repairs fail in opposite directions, which is
what makes the rule three-way rather than a predicate.

**The rule, and it states its own limits:**

| Line | Verdict |
|---|---|
| Kindless, bearing the type string | Header. Unchanged. |
| Bearing **both** the type marker and an entry `kind` | **Unclassifiable by this build.** Skipped and reported naming the ambiguity. Never absorbed, never a header, never a reason to refuse the file. |
| Anything else | Entry-shaped: read as an entry, or skipped as before. |

The middle row is the whole point. It is a location claim about this build's ability to
read the line — *not* a verdict about what the line is, which is exactly what this build
cannot know. Classification never absorbs and never refuses the file.

**Readable entries with no recognized header are now tolerated.** The entries are
self-describing evidence that heads were accepted, and a weakened claim is available, so
`known` falls to `HeadLowerBound` with the header's absence reported in `.skipped` —
proceed-answers decline, rollback stays sound. Refusing there would be a verdict where a
bound would do, which is the error `HeadUnreadable` was added to correct. The absence is
reported without a line number, because an absence does not have one.

**What still triggers `JournalUnreadable`, and why it is now the only thing.** Every
structural condition the *parser* meets yields a weakened claim rather than a verdict, so
the parser no longer raises it at all. What remains is the one case that leaves nothing to
parse: the journal is there and cannot be read as text — a directory, a permission wall,
bytes that are not text. Those previously escaped `read_journal` as raw `OSError` and
`UnicodeDecodeError`, straight past any caller catching `AttestationRefusal`, so this
narrowing also closes a latent gap rather than merely relocating the class. Its own test
pins it.

### Sol-round mutation demos

| # | Mutation | Result (94 tests) |
|---|---|---|
| (i-a) | the kindless precondition restored, so there is no ambiguous verdict | **2 failed, 92 passed** — `test_a_header_carrying_its_own_kind_does_not_refuse_the_file`, `test_a_type_bearing_entry_is_never_absorbed_as_a_header` |
| (i-b) | headerless entries refuse again (ruling 3 reverted) | **1 failed, 93 passed** — `test_entries_with_no_header_are_tolerated_as_a_weakened_claim` |
| (ii) | type-plus-kind classified as a header (the absorption arm) | **2 failed, 92 passed** — the mirror test, plus sol's own demonstration |

Both directions of the mirror are pinned: (i-a) removes the ambiguity verdict and (ii)
resolves it toward absorption, and each fails the test written for it.


## Sol-LOW round 2 — the prose sweep (`959e6d41`)

`finding:s3wp1-sol-l2-stale-journal-unreadable-prose`. Runtime was fully verified this
round; the finding is prose. Three contract-facing statements still documented the
`JournalUnreadable` scope from two rounds ago — the exception's own docstring, the
parser's docstring, and the write-path comment all said the reader refuses a journal whose
entries have no header. It tolerates that now, reports the absence, and weakens the claim
to a bound.

**The sweep the finding asked for turned up four more.** Answering the question directly:
yes, there were others, and one of them was worse than the three that were named.

| Site | What it still said |
|---|---|
| `JournalRead.skipped` | "Lines this build could not use." A missing header is reported there too and is not a line. Now says so, and names non-empty as exactly the condition that weakens `known`. |
| `established_head` | Refuses "when any epoch line was unreadable" — narrower than the code, which also refuses on an unclassifiable line and on a missing header. |
| `_parse_entry`'s kindless branch | Still called a kindless object "the header, or a future sibling of it". **The most dangerous of the seven**: classification takes headers before this function is reached, so this comment described precisely the absorb-everything-kindless behaviour BLOCKING-1 removed. A reader trusting it would have restored the defect. |
| `_PROTOCOL_VERSION` | Claimed a v1 journal "is never silently compared against a v2 head". Nothing reads these values back, so the promise is half kept. Not classification prose, but the same defect class — a comment asserting an enforcement the code does not perform — so it is fixed and the open gap is named at the site with wire v2 as its forcing consumer. |

**Prose only, and mechanically checked rather than asserted:** the module's AST is
identical to the previous commit once docstrings, attribute docstrings and comments are
stripped. No test changed. Engine 2157, architecture 99, both unmoved.

The pattern is now three-for-three in this file: every classification fix left prose
behind that described the behaviour it replaced. That is the same overcorrection loop
recorded after sol r1, seen from the documentation side — which is why the `_parse_entry`
comment matters more than its size suggests. A stale comment at a branch is a defect with
a delay.
