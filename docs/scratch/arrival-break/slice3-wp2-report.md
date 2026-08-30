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
