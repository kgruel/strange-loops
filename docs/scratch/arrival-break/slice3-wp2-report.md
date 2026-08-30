# Slice 3 / WP2 implementation report — the `comparison` conformance family

Branch: `slice3/wp2-vectors`, off `9ed893fe` on `slice3/arrival-witness` (merge-base
verified equal to `9ed893fe`). Worktree `~/Code/loops-s3wp2`.

Contract: `docs/scratch/arrival-break/slice3-wp2-brief.md`; design
`slice3-design-proposal.md` §C and §E's WP2 row; substrate
`engine/arrival_head_attestation.py` @ `9ed893fe` plus `slice3-wp1-report.md` and the
finding folds named in the brief. **Where the design proposal and the landed module
disagree, the module and the folds are the truth** — four rulings amended the design
after it was written, and the vectors encode the amended behavior.

## 1. The family-vector shape split — the brief's §4 design point, decided first

**Two vector forms inside one family, discriminated by an explicit `input.form`.**

| Form | Input | What it pins |
|---|---|---|
| `heads` | `known` entry, `presented` head, `at_known` head | the seven rows of the pure `compare` |
| `journal` | raw journal lines | every read rule, and the comparison that follows from it |

### Why not journal-only

§B.3's journal grammar is a **local cache format, not wire**. It is deliberately not
the record codec (the journal must stay readable when the store cannot be opened at
all), it versions independently of the record grammar, and no other implementation is
obliged to have one. Routing every comparison vector through a journal fixture would
pin *this repo's cache encoding* onto an implementation that owes only the state
machine — the same overreach the replicate family refuses when it declines to name a
Python exception class. The seven rows are the ratified §07 contract; they must be
statable without a journal.

### Why not heads-only

Every behavior the brief names from the finding folds lives in the **read**, not in the
classifier:

- reset-inclusive epoch scoping — `_epoch_of`
- the maximum-ordinal rule and journal equivocation — `_known_of`
- incomplete-read lower-bound semantics — `parse_journal_lines` → `HeadLowerBound`
- headerless-yields-a-bound — `parse_journal_lines`'s header-absence arm
- content-present-nothing-readable declines — `HeadUnreadable`
- the three-way header classification — `_classify`

None of them is reachable from `compare`, whose signature the lower-bound work left
untouched precisely so that the classifier rows would not have to change. A heads-only
family would pin the seven rows and **none** of the four rulings that were fought over.

So the split is not a convenience: the two forms answer questions the other form
structurally cannot ask.

### Why one family rather than two

The read and the classifier are two halves of one question — "is the log in front of me
the one this machine accepted?" — and the journal form's own `expected` includes the
comparison outcome. Splitting them into `comparison/` and `journal/` would put the
read rules in a family whose vectors state no comparison, which is the artifact that
would go stale first. One family, one inventory, two forms.

## 2. The `expected` schema, and the third honest answer

Applying `observation:practice/two-valued-classifiers-lie-in-one-direction` **to my own
vector schema**: if `expected.outcome` may only hold one of the seven ratified strings,
a journal whose comparison *declines* has no honest slot, and the schema would force
every vector to claim an outcome that was never produced.

The fix is two fields rather than a wider enum:

- **`expected.read`** — the state the read reached: `none`, `established`, `bounded`,
  `unreadable`, `equivocation`. This is where "why there is no outcome" lives.
- **`expected.outcome`** — one of the **seven ratified strings, or `null`**. `null`
  means `established_head()` refused and `compare` was never called, so there is no
  outcome to state. **Deliberately not an eighth string:** the brief's non-goals forbid
  new outcome strings, and a normative vector carrying `"declined"` would read to a
  foreign implementer as a value to return. The seven stay the only inhabitants of the
  outcome slot.

Two consequences of the closed-set naming lesson (WP1 sol r3/r4), applied to my own
field names:

- `read` names **what the read reached**, never why it got there. A bound produced by a
  torn line and a bound produced by a missing header are one state, and a new cause
  joins it without a new value — which is the whole point of WP1's "incomplete read"
  term. The vectors never enumerate causes.
- The consumer **fails loudly on an unknown `form` or an unknown `read`** (replicate's
  `KeyError` discipline), so a value this build does not know cannot be silently
  skipped into a green run.

### `sound_answer`, and why the bound vectors carry a positive claim

A bound vector that pinned only `outcome: null` would under-encode: it states what the
bound **cannot** answer and nothing about what it **can**. The amended ruling
(`s3wp1-mid-file-journal-damage-unstated`, arbiter amendment) and WP1's handoff both
say the bound is **rollback-only** — sound to refuse a presented head below it, never
able to answer `unchanged` or `advanced`. So a `bounded` vector carries
`expected.sound_answer`: `"rollback"` when the presented head is below the bound,
`null` when nothing is soundly answerable.

Scoped exactly to the ruling: `"rollback"` is the only non-null value a vector may
carry. Lineage-replaced against a bound is arguably also sound (the journal is keyed by
lineage, so every entry shares it), but asserting that in a normative vector would
**amend** a ruling, which is not WP2's to do. Noted here rather than encoded.

### `AbsentStoreOutcome` is deliberately excluded

WP1 choice 2 asked WP2 to decide this. **Excluded**, on the brief's own non-goal: the
family's coverage list is the seven outcomes plus equivocation, and
`compare_absent_store` returns a *different enum* whose values (`pre-genesis`,
`store-lost`) would be new outcome strings in this family's slot. The absent-store
question is also asked before there is a head to present, so it does not fit the
`(known, presented, at_known)` shape at all. Its forcing consumer is WP3's seam, and
WP3's empirical gate item 8 already covers both branches against real stores.

## 3. What landed

| File | What |
|---|---|
| `spec/conformance/generate_comparison.py` | the generator: 9 heads cases, 18 journal cases, deterministic |
| `spec/conformance/vectors/comparison/*.json` | 27 frozen vectors in five families |
| `libs/engine/tests/test_conformance_comparison.py` | the consumer: `VECTOR_INVENTORY` two-way, four further ratchets, one parametrized runner |
| `spec/conformance/SCHEMA.md` §11 | the area's normative description, both forms |

### The five families

| Family | Count | The question it answers |
|---|---|---|
| `comparison-classify-` | 9 | the seven §07 rows through the pure classifier, plus guard order |
| `comparison-epoch-` | 3 | reset-inclusive epoch scoping, across all the surfaces it governs |
| `comparison-journal-` | 6 | the maximum-ordinal rule, equivocation, and both negative controls |
| `comparison-incomplete-` | 6 | the lower bound (all three cells) and the third state |
| `comparison-header-` | 3 | the three-way classification |

### Every behavior the brief named, and the vector that encodes it

| Behavior | Vector |
|---|---|
| reset-inclusive epoch (`s3wp1-epoch-scope-is-reset-inclusive`) | `comparison-epoch-ends-at-the-reset-entry-is-unchanged`, and `-below-the-reset-head-is-rollback` for the half that proves *which* head |
| incomplete read is a lower bound, not refusal-of-the-file (amended `s3wp1-mid-file-journal-damage-unstated`) | `comparison-incomplete-a-torn-line-yields-a-lower-bound` — built on WP1's own refutation fixture, epoch `[reset 90, 92, 91]` with 92 torn |
| a bound is sound below itself | `comparison-incomplete-a-bound-still-refuses-below-itself` (`sound_answer: "rollback"`) |
| headerless-with-readable-entries is a BOUND (gate stale-oracle note) | `comparison-incomplete-a-headerless-journal-yields-a-bound` |
| content-present-nothing-readable declines everything (`s3wp1-gate-all-entries-unreadable-silent-tofu`) | `comparison-incomplete-nothing-readable-declines-every-comparison`, and the operator-facing consequence in `-a-re-mint-against-lost-content-is-not-first-contact` |
| first contact requires no surviving-or-skipped content claims | `comparison-journal-an-empty-journal-` and `-a-header-only-journal-is-first-contact` — the honest side of the same boundary |
| three-way header classification (`s3wp1-sol-l1-...`) | `comparison-header-both-markers-together-are-unclassifiable` (the middle row), `-a-kindless-object-is-not-absorbed` (BLOCKING-1), `-a-later-builds-header-is-still-a-header` (the mirror) |
| equivocation | `comparison-journal-equivocation-refuses-the-read`, scoped by `comparison-epoch-scopes-the-equivocation-check-too`, controlled by `-duplicate-entries-at-the-maximum-agree` |

**Where the design proposal would have produced a wrong vector:** §B.3 read rule 0's
literal wording ("the entries after the last one") pins `first-contact` on the
ends-at-the-reset journal where the module answers `unchanged`; §B.3's mid-file
prose and the round-0 oracle's `headerless-entries-refuse` both pin refusals the
module no longer raises. The vectors follow the module and the folds.

## 4. Four ratchets beside the inventory

The two-way `VECTOR_INVENTORY` is the replicate tier's own ratchet and it is carried
verbatim. Three more, because each pins something a reviewer would otherwise have to
notice:

1. `test_the_outcome_slot_holds_only_the_seven_ratified_strings` — the enum is exactly
   the seven, and no vector names a string outside them. The brief's "no new outcome
   strings" non-goal as an enumerable property rather than review vigilance.
2. `test_every_ratified_outcome_is_exercised_by_some_vector` — a row no vector reaches
   is a row this family does not test. Adding a row without a vector fails.
3. `test_every_cell_of_the_bound_is_exercised_by_some_vector` — **added in sol r1**
   (§9). The bound's answer surface has three cells and two of them answer `null`, so
   a family exercising only those two goes green against an implementation that
   answers `advanced` above the bound. A per-vector assertion cannot see this: each
   vector is individually correct and the hole is in which vectors *exist*.
4. `test_the_runner_stays_on_the_pure_surface` — the runner's namespace is checked for
   the impure names, so no test here can resolve a path into a real `$XDG_STATE_HOME`.
   Checked against the module's actual namespace, not its source, so it cannot be
   satisfied by a name that merely looks absent.

## 5. Oracle results

### 1. Vectors green; inventory exact in both directions

32 tests: 27 vectors + 5 non-parametrized. Both ratchet directions verified by doing
it, and each names the vector:

- **Drop a fixture** → `missing: ['comparison-epoch-below-the-reset-head-is-rollback']`
- **Add a stray** → `unclassified: ['comparison-stray-vector']` (and the envelope's
  name-equals-stem assertion fails alongside it, so a copied vector is caught twice)

### 2. Mutation demos at the module level, run THROUGH THE VECTORS

Each applied to the working tree, the vectors run, the mutation reverted, `git diff`
verified empty before the next.

| # | Mutation | Result |
|---|---|---|
| (a) | classifier: the rollback arm returns `UNCHANGED` | **3 failed, 27 passed** — `comparison-classify-rollback`, `comparison-epoch-below-the-reset-head-is-rollback`, `comparison-journal-the-known-head-is-the-maximum-ordinal`. Caught in both forms and across three families. |
| (b) | epoch reset-**EXCLUSIVE** (`entries[index + 1:]`) | **5 failed, 25 passed** — both `comparison-epoch-` reset vectors (the ends-at-reset journal falls to `read: none` and answers `first-contact`, which is the silent re-acceptance the fold named), plus the epoch counts on the equivocation-scope and two bound vectors. |
| (b2) | the trust-epoch filter dropped entirely | **5 failed, 25 passed** — and `comparison-epoch-scopes-the-equivocation-check-too` fails by raising a **spurious `JournalEquivocation` at ordinal 200**, the abandoned pre-reset pair. The two epoch mutations fail differently, which is what shows the vectors pin the scope rather than one arithmetic. |
| (c) | `established_head()` returns the bound instead of refusing | **5 failed, 25 passed** — every bounded vector: the two `comparison-incomplete-` bounds, the headerless one, and both `comparison-header-` bounds. `comparison-header-a-kindless-object-is-not-absorbed` fails with `assert 'unchanged' == None` against the head at ordinal 91 — which is BLOCKING-1's silent re-acceptance reproduced through a vector. |

Mutation (b2) is beyond the brief's three; it is cheap and it separates the two ways
epoch scoping can break, so it is reported rather than dropped.

### 3. Suites green, counts reconciled

Run the CI way, engine and architecture in **separate** processes (WP1 measured 29
cross-suite pollution failures when they share one).

| Suite | Baseline (`9ed893fe`) | After | Delta |
|---|---|---|---|
| engine | 2158 passed, 1 skipped | **2190 passed, 1 skipped** | **+32**, all in `test_conformance_comparison.py` |
| architecture | 99 passed | **99 passed** | **0** — Rule 17 scans generators by glob, so a new one adds no case |

Every delta accounted for: 27 parametrized vectors + 5 non-parametrized tests.
Rule 17 green with `generate_comparison.py` auto-enrolled by its `generate_*.py` name,
and Rule 18 unaffected (no engine module added).

### 4. `git ls-files` — the gitignore trap

`git check-ignore` reports the vectors are **not** ignored, and 27 vector JSONs are
tracked — matching the 27 the generator writes and the 27 the inventory names, three
independent counts agreeing.

## 6. Design choices

Each is a place the brief or the design underdetermined the vectors.

1. **The family-vector shape split** — §1 above. Both forms, one family, `input.form`
   discriminating, consumer failing loudly on an unknown one.
2. **`outcome: null` rather than an eighth string** — §2. The read state carries why.
3. **`sound_answer` is `"rollback" | null`, scoped to bounded vectors.** Encodes the
   positive half of lower-bound semantics. Deliberately NOT extended to
   `lineage-replaced`, which is arguably also sound against a bound (the journal is
   keyed by lineage) — asserting that in a normative vector would amend a ruling. See
   §7.
4. **`skipped` is a COUNT, not the reason strings.** One skip reason embeds the host's
   JSON parser error text, which is as language-specific as an exception class; the
   others are prose WP1 paid four sol rounds for drifting. The module's own
   documentation says non-empty *is* the weakening condition, so the count is the
   contract and the wording is not.
5. **`read` names what the read reached, never why** — the closed-set naming lesson
   applied to my own field. A bound from a torn line and a bound from a missing header
   are one value.
6. **`AbsentStoreOutcome` excluded** — §2, WP1 choice 2 answered.
7. **Well-formed fixtures are built through the real `append_entry`**, under a
   temporary `XDG_STATE_HOME` that the generator **asserts** before its first append
   (both `state_root()` and `journal_path()` are checked to resolve under the tempdir).
   Damage, ambiguity and foreign-build lines are spliced afterwards, since they are by
   definition what the writer would not produce. The consumer, by contrast, touches
   only pure functions and therefore resolves no path at all.
8. **The consumer names each read state's accessor separately rather than writing a
   helper.** There is deliberately no uniform way to reach a head across the three
   states — the weakened ones carry no `entry` attribute — and a helper here would have
   rebuilt the shortcut the type split exists to make unobtainable.
9. **Both negative controls carried**, per the replicate family's own pattern:
   duplicate entries at the maximum that *agree* are not equivocation, and unknown
   fields on a current-grammar entry are read normally. A refusal that fires on the
   control has stopped meaning what it says.
10. **One fixed lineage across the area** (replicate's rule: a reader comparing two
    vectors compares histories, not identifiers), with a second lineage existing only
    to be a different one. Record hashes are deterministic tag-derived digests — the
    journal validates no hash, so they must be well-shaped rather than real.
11. **`ruff check` clean.** One rule initially fired on `json.load(open(...))`; the
    sibling `test_conformance_replicate.py` trips the identical rule, so this is a
    pre-existing repo-wide pattern rather than something introduced here. Resolved
    inside the single `_read_vector` helper, so the rest of the runner still reads like
    its sibling.

## 7. Deviations and open notes

**No deviations from the brief's scope, oracle, or mechanics.** No module change was
made and none was needed: every behavior the vectors pin is the behavior the module
already has. Nothing rose to a finding fold — the four rulings had already amended the
design, and the vectors encode the amendments.

Two notes carried forward rather than encoded:

- **Lineage-replaced against a bound.** A journal is keyed by lineage, so every entry
  in it shares one; a presented head in a *different* lineage is therefore arguably
  soundly `lineage-replaced` even when the read was incomplete. The ruling and WP1's
  handoff both say the bound is ROLLBACK-ONLY, so the vectors do not assert it. If the
  arbiter wants it, it is a ruling amendment and then one more vector — not a change to
  the schema, which already has the slot.
- **The header's `protocol`/`wire` are still written and never read.** WP1 named this
  open with wire v2 as its forcing consumer. The area has the fixtures to pin it the
  day it lands: `comparison-header-a-later-builds-header-is-still-a-header` already
  carries a v2-shaped header whose versions are ignored today.

## 8. Receipts

Completion fact: `observation:implementation/arrival-slice3-wp2-comparison-vectors` @
`01M180VC8K6N0HJC2GJVN3ZJVC`.

Sol-round folds: `finding:s3wp2-l1-bound-above-cell-unpinned` @
`01M182MZ64KRPXGRXTAEZ3TW5B`, and
`finding:s3wp2-l2-hollow-occupancy-of-the-above-cell` @ `01M18369WBDCC52PNKP7R7CMBQ`.

**Store housekeeping, so a reader grepping the store is not puzzled.** The first emit
of that observation passed the topic as a positional slug rather than `topic=`, and
`observation` folds by `topic` — so `01M180TKTHEG60TG43D5A4QJVM` is stored with **no
fold key** and carries an earlier, shorter draft of the same message. The store is
append-only so it stays as written; `01M180VC8K6N0HJC2GJVN3ZJVC` is the one that folds
and the one to read. No finding: an emission-form slip, not a work product.

The sol-r2 fold has the same shape of blemish for a different reason: its first emit
(`01M1835CFX54PCX2ZDZGPVQH0D`) passed a backticked message through the shell, which
substituted the backticks as commands and **silently dropped four words** — the two
outcome names the argument turns on. Re-emitted under the same fold name via `--stdin`
so nothing is interpreted, and `01M18369WBDCC52PNKP7R7CMBQ` is what the fold resolves
to (verified by reading it back). The general lesson is worth one line for whoever
emits next in this arc: **pass long fact bodies through `--stdin`, never as a shell
argument** — a mangled receipt is worse than a missing one, because it still looks
like a receipt.

## 9. Sol-LOW round 1 — the unpinned third cell of the bound

`S3WP2-L-1`, BLOCKING, and correct. Everything else passed, including the coverage
matrix and the foreign-implementer reading of SCHEMA.md.

**What was wrong.** Every bounded vector presented a head exactly AT the bound except
one, which presented below it. Nothing presented a same-lineage head **above** the
bound. Verified before acting, across all five bounded vectors:

| Vector | bound | presented | cell |
|---|---|---|---|
| `comparison-incomplete-a-torn-line-yields-a-lower-bound` | 91 | 91 | at |
| `comparison-incomplete-a-bound-still-refuses-below-itself` | 91 | 89 | below |
| `comparison-incomplete-a-headerless-journal-yields-a-bound` | 6 | 6 | at |
| `comparison-header-a-kindless-object-is-not-absorbed` | 91 | 91 | at |
| `comparison-header-both-markers-together-are-unclassifiable` | 91 | 91 | at |

So a foreign implementation doing **below → rollback, equal → decline, above →
advanced** passed all 26 vectors while violating the amended ruling's second half —
"nothing bounds the accepted head from above", which is WP1's own self-correction.
SCHEMA.md's prose forbade it in two places, and **prose is not executable**.

**This is my own review lens landing on me.** §2 records applying
`observation:practice/two-valued-classifiers-lie-in-one-direction` to the *outcome*
field, where I found the third honest answer and split the schema for it. I did not
apply it to `sound_answer`, which is the bound's own answer surface and is equally
three-valued — below, equal, above. Two of its cells agree on `null`, and that
agreement is exactly what hid the missing one: the family looked like it covered the
bound because every vector it had was right.

**The fix.** One vector, `comparison-incomplete-a-bound-cannot-answer-above-itself`.

- Same family shape as the existing torn-line fixture — reset, a torn higher entry, a
  surviving lower entry — but the **torn entry holds ordinal 200 rather than 92**.
  Reportable deviation from the routed wording ("same `[90-reset, 92-torn, 91]`
  shape"), and the reason is substantive: with 200, the fixture *exhibits* the hazard
  instead of merely asserting the rule. The head this machine actually accepted was
  200, so a store presenting 95 is a rollback of 105 ordinals, and the naive
  `advanced` answer is provably wrong **on this very fixture** rather than only
  disallowed by ruling. The read cannot see 200 — that is the point.
- `at_known` is supplied and valid (the bound's own head at 91), so descent from 91 to
  95 really is established. An implementation cannot excuse `advanced` by pleading
  missing evidence; descent verified *from the bound* says nothing about an entry that
  was never on the walk. This is also the first journal-form vector to use `at_known`,
  a field the schema already carried.
- Expected: `read: bounded`, `outcome: null`, `sound_answer: null`.

**And a ratchet, because sol found this by reading.** Reviewer vigilance caught the
hole once; the enumerable property keeps it caught.
`test_every_cell_of_the_bound_is_exercised_by_some_vector` asserts the bounded vectors
collectively reach all three cells. Demonstrated by restoring the hole — dropping the
vector *and* its inventory entry — which fails with
`unexercised bound cells: ['above']` rather than going quietly green.

SCHEMA.md's bound paragraph is now a **three-row table** stating each cell and its
reason, with the note that the area carries a vector for every row; the
`comparison-incomplete-*` family blurb says all three cells are pinned and why two of
them agreeing is the trap.

### Sol-round demo — the adversarial implementation, before and after

Sol's own foreign implementation (below → `rollback`, equal → `null`, above →
`advanced`), run as a throwaway shim over the family's bounded vectors:

| Family | Bounded vectors | Result |
|---|---|---|
| as it was at `9735ce3f` | 5 | **NOT CAUGHT** — the adversary passes every one |
| as it is now | 6 | **CAUGHT by 1** — `comparison-incomplete-a-bound-cannot-answer-above-itself`, `vector=None adversary=advanced`; the other five stay green |

Exactly the scoped demo: the new vector fails, the others do not.

### Counts after sol r1

| Suite | Before sol r1 | After | Delta |
|---|---|---|---|
| engine | 2188 passed, 1 skipped | **2190 passed, 1 skipped** | **+2** — one vector, one ratchet |
| architecture | 99 passed | **99 passed** | 0 |

Generator still byte-reproducible (regenerate → empty diff); `ruff check` clean; 27
vector JSONs tracked.

## 10. Sol-LOW round 2 — hollow occupancy of the above cell

`S3WP2-L-2`, and the behavioral fix from r1 passed fully; what failed was the
**ratchet's seeded defeat test**. Sol nulled the new vector's `at_known` and the cell
ratchet still counted the above cell as exercised. The cell was occupied
*nominally* — the hazard it exists for was unpinned.

**Same shape as r1, one level up.** Round 1 said my enumeration was incomplete.
Round 2 says the enumeration's **occupancy predicate** was too weak: it asked whether
*a* vector sits in the cell, never whether that vector does the work the cell exists
for. A ratchet is only as strong as its notion of "covered", and mine counted
presence.

**Why a hollow vector proves nothing.** The above-the-bound claim is a
**counterfactual**: *even with descent fully established from the bound*, the proceed
answer stays unobtainable. Strip `at_known` and that counterfactual is gone — the
ordinary classifier answers `rewrite` for want of evidence, and
`comparison-classify-rewrite-when-the-ledger-vouches-for-nothing` already pins
exactly that. A hollow above-the-bound vector is therefore a duplicate of a classify
row wearing an incomplete-read costume: it would pass an implementation that declines
here for the *wrong reason* while still answering `advanced` wherever descent is
genuinely proven.

**The requirement, sharpened past the routed wording.** The route said "valid
NON-NULL `at_known`". Non-null is not enough: a non-null `at_known` naming some
*other* head is also answered `rewrite`, so it is hollow in the same way. The
requirement is **equality with the bound's own coordinate and record hash** — the
unique value that makes `advanced` the answer a bound-ignoring implementation reaches
for. Both weakenings are demonstrated below.

**Where it lives, and why not in the cell ratchet.** As a **vector-envelope assertion
in the parametrized runner**, so it fails against the vector's own test id and can say
which fixture is hollow and why. Folding it into the cell ratchet would have reported
`unexercised bound cells: ['above']` about a cell that is not empty — a true alarm
with a false reason, and the scope-the-claim error of a check asserting a verdict
wider than what it observed. The two questions now fail differently on purpose:

| Failure | Named by | Message |
|---|---|---|
| the cell is EMPTY | `test_every_cell_of_the_bound_is_exercised_by_some_vector` | `unexercised bound cells: ['above']` |
| the cell's occupant is HOLLOW | `test_conformance_comparison[<the vector>]` | names the fixture, its `at_known`, and the reason |

The cell ratchet's docstring now states this division explicitly, so a reader of
either check finds the other.

SCHEMA.md carries the obligation normatively: the three-cell table is followed by a
paragraph stating that a vector occupying the third row must supply `at_known` equal
to the bound's coordinate and hash — a requirement on the *fixture*, not on
implementations — with the counterfactual spelled out.

### Sol-round demo — both weakenings

Applied to the vector JSON on disk (the true shape of a hollow fixture), suite run,
file restored byte-clean.

| # | Weakening | Result |
|---|---|---|
| (i) | `at_known` → `null` (sol's seeded defeat) | **1 failed, 31 passed** — `test_conformance_comparison[comparison-incomplete-a-bound-cannot-answer-above-itself]`, message naming `at_known=None` and the reason |
| (ii) | `at_known` → non-null but NOT the bound's head (ordinal 91, hash `0`×64) | **1 failed, 31 passed** — the same assertion, which is why the requirement is equality rather than non-nullness |

Restored: 32 passed, `git status` clean on the vector.

### Counts after sol r2

Unchanged: engine **2190 passed, 1 skipped**; architecture **99**. This round adds no
test and no vector — it strengthens an existing assertion — so the deltas from §9
stand. `ruff check` clean; generator untouched and still byte-reproducible; 27 vector
JSONs tracked.

### The general form, now twice

Both rounds are the same defect at successive levels, and it is worth stating once
rather than a third time. An enumerable ratchet has two parts — the set of cells and
the predicate for "this cell is covered" — and **both** can be too weak. Round 1
found a missing cell; round 2 found a predicate that accepted a fixture which
occupied a cell without discriminating anything. Writing the ratchet is not the end
of the work: the question to ask next is *what is the weakest artifact that would
satisfy this check*, and whether that artifact would actually have caught the thing
the check exists for. Sol's seeded-defeat method asks exactly that question, and it
is the reason r1's fix was not the end of it.

## 11. Integration round — amending the family to WP3's ruled semantics

Wave branch `slice3/arrival-witness`, worktree `~/Code/loops-s3wp1`. Routed as
`finding:slice3-integration-vectors-encode-preamendment-semantics`. Step 0 verified:
two merge commits (`eab3742c` WP3, `b94413de` WP2) over `886d5619`/`9a4b0fa3`
ancestry. (One untracked file, `slice3-crossdoc-report.md`, belongs to another agent
and was left alone.)

The family converged under WP1's journal semantics at `9ed893fe`. Amendments #2
(position-bound resets) and #3 (byte-duplicate dedup) changed the journal-read
contract the journal-form vectors execute, so its convergence does not carry. **The
vectors are amended TO the ruled semantics; nothing was relaxed.**

### Cause table — verified, and the routed diagnosis corrected in two places

| Vector | Routed diagnosis | Verified cause |
|---|---|---|
| `comparison-epoch-ends-at-the-reset-entry-is-unchanged` | reset lacks `follows` → epoch never opens | **Confirmed.** Reset skipped as unbound; epoch = all 3 entries; K = 100 (the abandoned head); `read` bounded, not established |
| `comparison-epoch-below-the-reset-head-is-rollback` | same | **Confirmed**, identical shape |
| `comparison-epoch-scopes-the-equivocation-check-too` | same | **Same root, different symptom.** The unhonored reset puts the abandoned pair at ordinal 200 back in scope, so the read **raises `JournalEquivocation`** rather than returning a bounded read. Lumped with the other two in the routed diagnosis; the distinction matters because a raised refusal and a weakened read are different failures |
| `comparison-journal-duplicate-entries-at-the-maximum-agree` | byte-identical duplicates now dedup | **Confirmed.** Line 4 byte-identical to line 3 → skipped; entries 2, bounded |
| `comparison-incomplete-a-torn-line-yields-a-lower-bound` | "known-state class assertions failing against the reworked scan" | **Not a known-state failure at all.** `read` was `bounded` and the bound was 91 — both exactly as expected. What drifted was the **counts**: `epoch` 3 (not 2) and `skipped` 2 (not 1), because these fixtures *also contain a trust reset* which was likewise unbound |
| `comparison-incomplete-a-bound-still-refuses-below-itself` | same | same |
| `comparison-incomplete-a-bound-cannot-answer-above-itself` | same | same |

**Six of the seven share ONE root cause** — fixture resets carry no `follows` — with
three distinct symptoms: bounded-instead-of-established, a raised
`JournalEquivocation`, and count drift. The three `comparison-incomplete-` vectors
were collateral: their torn-line fixtures happen to contain a reset, so the reset
defect showed up in their counts while the property each was written to pin (the
bound and its cells) was never actually broken. Only the duplicate vector is a
separate cause.

### The fixes

**1. Fixture resets are bound at write time.** `lines_for` now computes each reset's
`follows` from the journal as it stands at the moment of the append — the physical
line the previous entry occupies, and that entry's identity. This is the **same
computation** `arrival_head_seam.trust_reset` performs, spelled with the two
primitives the attestation module exports for it (`last_entry`, `entry_identity`)
rather than by importing the seam. **Justification for not calling the seam producer
directly:** it canonicalizes its `location` through `Path.resolve()`, which is a
function of the machine the generator runs on, and frozen vectors must not be. The
binding arithmetic is identical either way; only the location handling differs.

`reset()` no longer sets `follows` at construction: the claim is a fact about the
journal being built, not about the ceremony, and a reset constructed with a stale
binding is precisely what the read rejects.

**2. The duplicate vector became two vectors**, because dedup split one fixture into
two different claims and this family's discipline is one claim per vector:

- `comparison-journal-agreeing-entries-at-the-maximum-are-not-equivocation`
  (renamed from `-duplicate-entries-at-the-maximum-agree`). Two entries at ordinal 6,
  same record hash, **different `observed_at`**. Preserves the original negative
  control. The differing timestamp is now load-bearing rather than incidental: dedup
  takes byte-identical lines *before* the equivocation check sees them, so a
  byte-identical fixture would no longer reach the control it was written to be.
- `comparison-journal-a-byte-identical-line-is-a-re-assertion` (**new**). Pins
  amendment #3 directly: entries 2, skipped 1, `read` bounded.

Two vectors rather than one because "agreement is not equivocation" and "a replayed
line cannot count twice" are independent claims that a single fixture can no longer
carry — and the rename alone would have retired the first claim silently.

**3. SCHEMA.md caught up**, normatively: the `follows` field in the Entry Object
table, a section on the binding (physical-line semantics, `[0, ""]` at journal start,
why position closes the class where identity closes only the instance, unbound =
skipped-not-refused, no compat arm, the truncation-realignment residual), and a
section on the dedup rule (type-agnostic, order-agnostic, read-side only, **headers
exempt** as the tolerated create-race artifact, and the agreement-versus-byte-identity
distinction).

**4. Inventory** follows the rename and the addition. The cell-enumeration ratchet's
coverage claim stays true: the new dedup vector is `bounded` at the *equal* cell, and
the above cell is still held by `comparison-incomplete-a-bound-cannot-answer-above-itself`
with its valid `at_known`.

### Verification

| Check | Result |
|---|---|
| family suite | **33 passed** (28 vectors + 5 non-parametrized), from 7 failed / 25 passed |
| engine, wave worktree | **2266 passed, 1 skipped** |
| architecture, separate process | **99 passed** |
| generator byte-reproducible | regenerated twice, output digest **identical** |
| `ruff check` | clean on generator and consumer |

Post-fix values, each predicted before running and then confirmed:

| Vector | entries | epoch | skipped | read |
|---|---|---|---|---|
| `comparison-epoch-ends-at-the-reset-entry-is-unchanged` | 3 | 1 | 0 | established |
| `comparison-epoch-scopes-the-equivocation-check-too` | 5 | 2 | 0 | established |
| the three `comparison-incomplete-` bound vectors | 3 | 2 | 1 | bounded |
| `comparison-journal-agreeing-entries-…` | 3 | 3 | 0 | established |
| `comparison-journal-a-byte-identical-line-…` | 2 | 2 | 1 | bounded |

The three incomplete vectors return to exactly their pre-amendment expected values —
now for the right reason, since their resets are bound rather than ignored — and the
`skipped` set holds only the torn line.

### Position binding makes fixture ORDER part of the frozen output

Named in the generator's docstring rather than discovered later: a reset records the
physical line its predecessor occupies, so inserting, removing or reordering any line
in a fixture containing a reset changes that reset's `follows`. That is by design — a
binding that survived being moved would not be a position claim — but it means
regenerating after such an edit is mandatory, and a hand-edited vector JSON is
guaranteed stale.

### One finding, routed to the lead rather than fixed

Engine behavior is not mine to change. Reported in full in the completion message:
**a byte-identical crash-retry duplicate permanently weakens every subsequent read to
a bound.** Verified — after the duplicate and four later legitimate commits,
`established_head()` still raises, so `unchanged` and `advanced` stay unobtainable
for the life of the journal, while the bound itself is *correct*. It is deliberately
not emitted as a fold: the lead decides whether it enters the ledger, and it carries
an arbiter-facing question.

`comparison-journal-a-byte-identical-line-is-a-re-assertion` pins the ruled behavior
as of now regardless, and its own description says the weighing question is open and
that this vector is what would be regenerated if it is ruled the other way — a
foreign implementer reading the family should know which of its claims is settled and
which is under review.
