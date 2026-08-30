# Slice-3 doc catch-up: witness-protocol.html vs. the head-attestation implementation

Applied on `slice3/doc-catchup` (based at `eab3742c` on `slice3/arrival-witness`).
Input: `docs/scratch/arrival-break/slice3-crossdoc-report.md`. Implementation of
record: `libs/engine/src/engine/arrival_head_attestation.py` and
`libs/engine/src/engine/arrival_head_seam.py`. Ruling of record:
`design:arrival-break-slice3-witness-minimum` plus amendments #1–#3.

One file changed: `docs/architecture/arrival/witness-protocol.html`. No existing
section was renumbered. HTML re-verified balanced by an `html.parser` tag-stack
check, and every `href="#…"` resolves to a defined `id`.

## What changed, by crossdoc item

| # | Crossdoc item | Disposition | Where |
| --- | --- | --- | --- |
| 1 | Three-way header classification | **RESOLVED** — new §04b | §04b "Header, entry, or neither" |
| 2 | Read states (four, asymmetric bound) | **RESOLVED** — contradiction removed | §07 read-state table + pseudocode |
| 3 | Object-identity first contact | **RESOLVED** — new §04b + §02 + §07 pointer | §04b "First contact and the object behind a name" |
| 4 | Position-bound trust resets | **RESOLVED** — mechanism + callout reconciled | §04b "Position-bound trust resets"; §11 callout |
| 5 | Byte-dedup journal reads | **RESOLVED** — new §04b | §04b "A repeated line is a re-assertion" |
| 6 | Epoch semantics | **RESOLVED** — contradiction removed | §07 opening paragraphs |

### Item 1 — header classification

New §04b carries the file model: a header line naming grammar/protocol/wire
versions, then one observation per line, classified **by shape, never by
position**. A three-row table gives the ruling: type marker without a kind is a
header; type marker *and* a kind is unclassifiable (skipped and recorded, never
absorbed, never a refusal); anything else is entry-shaped. The prose states why
both two-valued repairs fail in opposite directions, and frames the middle row
as a location claim rather than a verdict. Doubled headers are named as a
tolerated create-race artifact — which is also why headers are exempt from
dedup (item 5).

The third leg the task named — headerless-with-entries ⇒ the read is bound — is
a `parse_journal_lines` consequence rather than a `_classify` outcome, so it is
stated as its own paragraph and explicitly linked to the incomplete-read
condition ("one of the two things that make a read incomplete") rather than
folded into the classification table.

### Item 2 — read states

§07's binary model is gone. A new "How much of a head the journal has"
subsection carries a four-row table: established head (all seven comparisons),
head lower bound (what it supports and what it declines), head unreadable
(nothing at all, and explicitly *not* first contact), no head (first contact).

The bound's supported set follows `_degraded` (`arrival_head_seam.py:1213-1222`)
rather than the task prompt's compressed summary: **rollback below the bound,
and same-height fork *at* the bound when the hash differs.** Only equal-with-
matching-hash and above are declined.

"Incomplete read" is defined by what the read lacked, not by cause, per
`HeadLowerBound`'s warning that the prose has drifted four times by naming one
cause as the definition. The word "torn" appears exactly once, in quotes, to
deprecate it (`"Incomplete," never "torn"`) — mention-to-deprecate, matching the
codebase's own idiom. The non-ascending write order is stated as the reason a
mid-file loss yields a lower bound *by construction* rather than by concession.

Note that the established state requires a complete read of the **whole file**,
not of the current epoch: `parse_journal_lines` accumulates `skipped` file-wide
(a line below the reset boundary, a missing header, and a rejected-reset note
all land in it), and any non-empty `skipped` weakens the read to a bound. The
table's "when" cell says so.

The pseudocode gained a state-acquisition preamble (`journal.read()` →
`established_head()`, which raises INDETERMINATE on the weaker two) and a
degraded arm. **`compare()` itself is byte-for-byte unchanged** — the seven
outcomes and the lineage-before-ordinal-arithmetic guard order are what the
`comparison` vectors pin and what the crossdoc report lists under "already
agrees." A "Degrade with a label; do not refuse" callout carries the posture
argument, including that a degraded open writes nothing.

### Item 3 — object-identity first contact

§04b's closing subsection: the binding key is a **resolved path — a spelling,
not an identity**; resolution normalizes a path without establishing which
filesystem object it names; a case-variant spelling or a second mount reaches
the same store through a still-distinct string. Before a location with no
binding of its own is minted as first contact, each recorded binding is
live-stat'd and device/inode compared, and a match routes through the existing
binding so a replacement meets a lineage-replaced refusal. States that the
identity is compared live and **never recorded** (inodes go stale and get
recycled), and why this detection is legitimate (the filesystem namespace is
ambient authority; the answer is a location claim about the host).

The dev/ino residual was added to §02's "Not claimed" list. §07's "First-contact
limitation" gained one sentence pointing at §04b, since the amendment names
first-contact coverage as part of the slice-close check.

### Item 4 — position-bound trust resets

§04b covers `follows` = (physical line ordinal, predecessor identity), counted
from 1 over **every** line including skipped ones — with the reason an index
among parsed entries would be a judgment that silently voids resets below.
Covers why identity alone was insufficient (the ordered two-line replay
reproduces it), why position closes the class rather than the instance, and why
identity stays in the pair. Mismatch is skip-with-record and never a refusal,
with the crash-retry-duplicate argument and the safe failure direction.

Includes the consequence the advisor flagged as the best teaching moment: the
skip record is itself what weakens the read to a bound, so a journal holding a
replayed reset still refuses everything below that bound. Also covers the
judgment-free tail read (so the ceremony works on the equivocating journals it
exists to fix), the read-tail-then-append TOCTOU, and read-back verification
raising `TrustResetNotHonored` — with the point that the unsafe part is silence,
not the stale binding. The truncation-then-replay residual is stated, naming
§04's signed grammar as the upgrade, and was added to §02's "Not claimed" list.

The **§11 "Witnesses move forward" callout is reconciled**, not deleted. It now
names two explicit exceptions instead of one: a repair starting a *new* lineage
with a transition report, and — within the *same* lineage — the trust-reset
ceremony, which records the gap and opens an epoch that scopes later
comparisons. Closes on the distinction the implementation turns on: the
abandoned entries stay as evidence, so what moves backward is the read scope,
not the history.

### Item 5 — byte-dedup

§04b: a line whose stripped text duplicates an earlier line is skipped and
recorded **before** the head is computed. Type-agnostic, order-agnostic,
read-side only, headers exempt. A security callout carries amendment #3's
rationale construction intact: replayed advance → K names a genuinely abandoned
head → a store restored from the pre-reset backup presents exactly that head →
"unchanged" carries no descent check by design → silent re-acceptance. Byte
identity is complete against literal replay; a genuine-re-assertion collision
costs only the skip, which lowers K and so fails refusal-side.

### Item 6 — epoch semantics

§07's "the last known or attested head" is replaced. K is now stated as the
**maximum-ordinal entry of the current trust epoch**, with both halves argued:
not the last entry written (appends are serialized, journal writes are not — the
90/92/91 file, where last-write semantics would call a genuine restore to 91
unchanged), and not unscoped. The epoch is defined as the last honored
trust-reset entry and everything after it, **inclusive of the reset entry**,
with both deadlocks named: exclusive scoping empties a just-reset journal into
first contact; no scoping leaves the abandoned entries holding the maximum
ordinal and every later open refusing forever. Equivocation is stated as
epoch-scoped, so a ceremony can take effect over a conflict already resolved.
Duplicate entries at the maximum that agree are named harmless.

## Also changed, in service of the above

- **§04** gained a paragraph framing the signed grammar as the **deferred
  upgrade** of §04b's unsigned substrate — one design at two assurance levels —
  and naming the distinct `type` as deliberate corpus hygiene.
- **§13** — the adopted-minimum callout now says all four adopted artifacts
  dissolve into the one journal (remembered head = highest-ordinal entry,
  bootstrap receipt = first entry, audit entry = an entry). One paragraph after
  the required-vector list marks that list as the *deferred* grammar's corpus
  and points at the shipped `comparison` family. Both are consistency, not new
  claims.
- **TOC** gained one `<li>` for §04b. `.doc-toc` is `list-style: none`, verified
  in the vendored stylesheet, so no existing entry appears renumbered.

---

# Round 2 — amendments #4 and #5, the disclosure sentence, and the matrix rows

Engine semantics moved after this branch's base. Round 2 applied three
authorized edits plus the corrections they forced. Sources read: amendments #4
and #5 in full from the project store, `spec/conformance/SCHEMA.md`'s new
"Which skips weaken" section, and the engine diff `eab3742c..0a5aecce`
(`_Skips`, `_epoch_of`'s boundary return, the `trust_reset` disclosure
docstring). None of those commits are ancestors of this branch; they were read
via `git show`/`git diff` and the base was left where the task set it.

## What changed

### 1. Weighting (amendments #4 + #5)

New §07 subsection, **"Which skips weaken: weight is cause times position."**
Recorded ≠ weakening; both factors decided per skip, never per read (a journal
with one weightless and one weighing skip is bounded by the second alone).
Cause: a re-assertion carries zero weight, everything else full — with the
crash-retry-duplicate argument, and the narrow ruling that a **voided reset
still weighs** because the line's content is readable while the operator's
intent for it is not. Position: a weakening-class skip before the boundary
reset's line carries zero weight, or the ceremony heals nothing.

The three remaining pinned edges are in one paragraph (structural absence exempt
from position scoping; no valid reset means no boundary; the bound is
epoch-scoped like K itself, since a file-wide bound inflated by an abandoned
epoch would manufacture rollback refusals). The fourth — "below" means physical
line, never ordinal — is a **"Position is not ordinal"** callout placed directly
above them, because it is the point most likely to be misread against §07's own
90/92/91 example: ordinals do not ascend in file order because two writers
interleave them, while positions cannot interleave because the filesystem
serializes appends.

The **two-mechanism healing story** is its own paragraph. Positioned damage heals
through the weighting; a voided ceremony attempt heals through the epoch walk
short-circuiting — the walk runs backward and returns at the first valid reset,
so a re-run ceremony's entry ends the walk before the failed attempt below it is
ever examined and no note is produced for it at all. Stated precisely that way
rather than as "the note drops below the new boundary," which is the wrong
mechanism: per the code comment in `parse_journal_lines`, a voided-reset note
can only come from *above* the boundary by construction, which is exactly why
position scoping never exempts one. Closes on the ruling's own line — unhealed
degradation is honest, healed degradation is decreed.

A pointer paragraph names `expected.skipped` vs `expected.weakening` in
SCHEMA.md §11 as the executable form. No field table duplicated.

**Corrections the weighting forced** (each was actively false as written):

- §07 read-state table, rows 1 and 2 — "the read was complete—nothing skipped,
  header present" → "nothing the read missed carried weight" / "the read missed
  something that carried weight."
- §07 incomplete-read definition — now "lacked something it needed *and* that
  loss carried weight," with the voided reset added to the cause list.
- §07 degradation callout — "an incomplete read is permanent" is no longer true
  now that a ceremony can heal one; reworded to "persists until an operator
  acts … keeps its weight until a ceremony decrees past it."
- §04b "What an incomplete read costs" — the sentence asserting that a non-empty
  skip record *is* the incomplete-read condition is replaced by the
  recorded-vs-weighing distinction.
- §04b header-absence paragraph — now names the absence as **structural** and
  says a structural absence weighs regardless of any boundary.
- §04b voided-reset paragraph — the reason a replayed reset still bounds the
  read changed from "any skip weakens" to "a voided reset keeps its cause
  weight," which is the narrow ruling.
- §04b dedup subsection — gained the weightlessness sentence, and the callout's
  tail was rewritten: with the skip weightless, the match predicate is
  **acceptance-load-bearing** (a false match discards a real line, lowers K, and
  still reads as established), held by advance demanding a verified descendant
  rather than mere height. That is amendment #4's knowingly-accepted
  consequence; the old "fails on the refusal side" tail no longer described the
  shipped behavior.
- §07's K paragraph — "both halves of that carry weight" → "are load-bearing,"
  since "weight" now has a technical meaning three paragraphs later.

### 2. Disclosure sentence

Added to §04b's position-bound-resets subsection as its own paragraph, matching
the docstring twin: a reset decrees trust in *N*; verified descendants of *N*,
including re-presentations of abandoned history, are accepted; fencing out
authentic history is not expressible unsigned. Attributed to the open ruling
`design:arrival-reset-descendant-acceptance`. The doc does not name individuals,
so it says "remains an open ruling" rather than naming the gate holder.

### 3. §08 attack matrix

Two rows added after the equivocation row, both cross-referencing §04b:

- **Replay a journal line verbatim** — store untouched; bytes already appear
  above it, so it is a re-assertion, recorded and weightless; remembered head
  unmoved.
- **Re-append an old trust reset to reopen a closed epoch** — store may present
  the abandoned head; a byte copy is a re-assertion, and any copy lands at a new
  line so its recorded position is stale; reset opens no epoch and the rollback
  refusal stands.

The second row was my judgment call and is worth the space because the two
sub-cases are caught by *different* mechanisms. It is phrased to cover both
without overclaiming: a byte-identical copy is taken by dedup, a non-identical
copy by the stale position claim, and forging fresh bytes at the correct current
position remains the signed grammar's territory (amendment #3's residual), so
the row does not claim protection against forgery.

### 4. Normative pointer widened

Last round's flag is resolved — the vectors caught up at `0918d119` and
`6954c0a0`. §13's pointer paragraph now lists the trust-reset binding and its
mismatch path, byte-duplicate re-assertions, and per-skip weighting alongside
what it already named. §04b's pointer was never narrowed and needed no change.

## Out of scope, with reason

> **Superseded by round 2 where noted.** The §08 matrix row and the
> vector-coverage caveat below were both resolved in round 2; they are kept here
> as the round-1 record rather than silently rewritten.

- **§08 attack matrix** ~~has no "replayed/duplicated journal line" row~~
  (crossdoc item 5's second paragraph). **RESOLVED in round 2** — two rows
  added once authorized. Round-1 reasoning follows. The mechanism and its
  rationale are covered
  conceptually by §04b; a matrix edit is a third kind of change the task did not
  authorize. Flagged here rather than applied.
- **§13's required-vector list** was not extended with journal-read entries. The
  list is the deferred signed corpus; the shipped rules already have a vector
  family, and the added paragraph says so rather than duplicating the entries.
- **Field tables were not duplicated.** `spec/conformance/SCHEMA.md` §11 and the
  `comparison` vector family remain the normative layer, and §04b points at them.
  ~~Note that `follows` position-binding and byte-dedup are not yet pinned
  there~~ — **RESOLVED in round 2**: the vectors caught up at `0918d119` and
  `6954c0a0`, and §13's pointer was widened accordingly. The round-1 caveat was
  accurate when written and is no longer.
