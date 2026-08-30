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
| `spec/conformance/generate_comparison.py` | the generator: 9 heads cases, 17 journal cases, deterministic |
| `spec/conformance/vectors/comparison/*.json` | 26 frozen vectors in five families |
| `libs/engine/tests/test_conformance_comparison.py` | the consumer: `VECTOR_INVENTORY` two-way, three further ratchets, one parametrized runner |
| `spec/conformance/SCHEMA.md` §11 | the area's normative description, both forms |

### The five families

| Family | Count | The question it answers |
|---|---|---|
| `comparison-classify-` | 9 | the seven §07 rows through the pure classifier, plus guard order |
| `comparison-epoch-` | 3 | reset-inclusive epoch scoping, across all the surfaces it governs |
| `comparison-journal-` | 6 | the maximum-ordinal rule, equivocation, and both negative controls |
| `comparison-incomplete-` | 5 | the lower bound and the third state |
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

## 4. Three ratchets beside the inventory

The two-way `VECTOR_INVENTORY` is the replicate tier's own ratchet and it is carried
verbatim. Three more, because each pins something a reviewer would otherwise have to
notice:

1. `test_the_outcome_slot_holds_only_the_seven_ratified_strings` — the enum is exactly
   the seven, and no vector names a string outside them. The brief's "no new outcome
   strings" non-goal as an enumerable property rather than review vigilance.
2. `test_every_ratified_outcome_is_exercised_by_some_vector` — a row no vector reaches
   is a row this family does not test. Adding a row without a vector fails.
3. `test_the_runner_stays_on_the_pure_surface` — the runner's namespace is checked for
   the impure names, so no test here can resolve a path into a real `$XDG_STATE_HOME`.
   Checked against the module's actual namespace, not its source, so it cannot be
   satisfied by a name that merely looks absent.

## 5. Oracle results

### 1. Vectors green; inventory exact in both directions

30 tests: 26 vectors + 4 non-parametrized. Both ratchet directions verified by doing
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
| engine | 2158 passed, 1 skipped | **2188 passed, 1 skipped** | **+30**, all in `test_conformance_comparison.py` |
| architecture | 99 passed | **99 passed** | **0** — Rule 17 scans generators by glob, so a new one adds no case |

Every delta accounted for: 26 parametrized vectors + 4 non-parametrized tests.
Rule 17 green with `generate_comparison.py` auto-enrolled by its `generate_*.py` name,
and Rule 18 unaffected (no engine module added).

### 4. `git ls-files` — the gitignore trap

`git check-ignore` reports the vectors are **not** ignored, and 26 vector JSONs are
tracked at `ebe8616e` — matching the 26 the generator writes and the 26 the inventory
names, three independent counts agreeing.

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

**Store housekeeping, so a reader grepping the store is not puzzled.** The first emit
of that observation passed the topic as a positional slug rather than `topic=`, and
`observation` folds by `topic` — so `01M180TKTHEG60TG43D5A4QJVM` is stored with **no
fold key** and carries an earlier, shorter draft of the same message. The store is
append-only so it stays as written; `01M180VC8K6N0HJC2GJVN3ZJVC` is the one that folds
and the one to read. No finding: an emission-form slip, not a work product.
