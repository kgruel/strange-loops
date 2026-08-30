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

## Out of scope, with reason

- **§08 attack matrix** has no "replayed/duplicated journal line" row (crossdoc
  item 5's second paragraph). The mechanism and its rationale are covered
  conceptually by §04b; a matrix edit is a third kind of change the task did not
  authorize. Flagged here rather than applied.
- **§13's required-vector list** was not extended with journal-read entries. The
  list is the deferred signed corpus; the shipped rules already have a vector
  family, and the added paragraph says so rather than duplicating the entries.
- **Field tables were not duplicated.** `spec/conformance/SCHEMA.md` §11 and the
  `comparison` vector family remain the normative layer, and §04b points at them.
  Note that `follows` position-binding and byte-dedup are **not yet** pinned
  there (verified: no `comparison-reset-*` or dedup vectors exist), so §04b's
  pointer is scoped to the read rules and the state machine and does not claim
  every rule below it carries a vector.
