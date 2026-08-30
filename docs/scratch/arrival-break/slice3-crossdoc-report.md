# Cross-doc divergence report: witness-protocol.html vs. head-attestation implementation

Read-only check performed in `/Users/kaygee/Code/loops-s3wp1` against
`docs/architecture/arrival/witness-protocol.html` (682 lines) as it stands on
this worktree, compared to the six semantics ratified during implementation of
`libs/engine/src/engine/arrival_head_attestation.py` and
`libs/engine/src/engine/arrival_head_seam.py`.

## Root cause behind most of the gaps

The doc's one concrete, field-level section — §04 "The head attestation"
(lines 196–270) — specifies the **deferred signed** grammar (`v`, `type:
arrival-head`, `protocol`, `wire`, `lineage`, `ordinal`, `record_hash`,
`record_count`, `fact_count`, `tick_count`, `observed_at`, `issuer`, `key_id`,
`previous`, `sig`), explicitly the thing §13's adopted-minimum callout (lines
655–665) says is **deferred until a consumer forces it**: *"The
signed-attestation grammar, notary, and quorum apparatus is deferred until a
consumer forces it."* What actually shipped in slice 3 is a different,
**unsigned** artifact — the module docstring is explicit that the serialized
`type` is `arrival-head-observation`, distinct from the doc's `arrival-head`,
specifically so the future signed corpus is not encumbered (`arrival_head_
attestation.py:29-36`). Because the doc's only concrete schema is the deferred
one, it has **no textual home at all** for the shipped journal's actual shape
— header line, per-entry `kind`/`level`, `follows`, byte-dedup, epoch
scoping. That is why items 1, 3, 4, 5 below are mostly GAPs rather than
line-for-line contradictions: the doc is silent on the file format because it
was describing a different (still-future) artifact. Items 2 and 6 are more
often outright contradictions because the doc *does* make a concrete claim
about the shape of "the head" that the implementation revised.

---

## Item 1 — Three-way header classification

**No home in the doc at all — total GAP.** Nothing in witness-protocol.html
discusses a journal *file format*: no header line, no `kind`/`type` field
disambiguation, no notion of a kindless-vs-typed object, no doubled-header
tolerance. The closest candidate section, §04 (lines 210–233), is the signed
attestation's field table — a single object per attestation, not a
line-oriented append log with a distinct header record.

- §06 "Append-only receipt journal" card (lines 332–336): *"Chain signed
  attestations in a separately backed-up journal."* This is the doc's only
  mention of a "journal," and it describes chained **signed** attestations
  (via `previous`, §04), not an append-only JSONL of unsigned observations
  with a header line and per-entry `kind`. **GAP**: a foreign implementer
  reading only this doc would not know the shipped journal has a header line
  at all, let alone the three-way classification (kindless+type ⇒ header;
  type+kind ⇒ unclassifiable/ambiguous skip; kindless+no-type ⇒ ordinary
  entry) or that a doubled header from a create race is tolerated rather than
  refused.
- §13 "Required test vectors" (lines 617–629) lists vector categories
  (golden attestation bytes, comparison outcomes, attack scenarios, key
  rotation, projection audits, cross-backend verification) but nothing about
  header classification, race-created duplicate headers, or unreadable/
  unclassifiable line handling. **GAP**.

## Item 2 — Read states (EstablishedHead / HeadLowerBound / HeadUnreadable / None)

**CONTRADICTION.** §07 "Head comparison state machine" (lines 368–376)
states the model as strictly binary: *"Let K be the last known or attested
head and P the head now presented... Comparison uses lineage, ordinal, and
record hash."* The verifier pseudocode (lines 397–408) takes `known` as
either `None` or a single head — `if known is None: return FIRST_CONTACT`,
then unconditional field access (`known.lineage`, `known.ordinal`,
`known.hash`). There is no third or fourth state, no partial-read concept,
and no operation that is sound in one direction only.

The implementation instead has four states (`EstablishedHead`,
`HeadLowerBound(at_least, skipped)`, `HeadUnreadable(skipped)`, `None`), and
`HeadLowerBound` is asymmetric by design: sound for rollback/fork refusals
*below* the bound, unsound (declines) for unchanged/advanced *at or above*
it (`arrival_head_attestation.py:723-736`). The doc's pseudocode has no
analog to this asymmetry — it would (incorrectly, per the ratified rule)
treat `presented.ordinal == known.ordinal` as decidable UNCHANGED-or-FORK
even when the read that produced `known` was incomplete.

- Doc's §09 "Fast open checks" (line 472): *"comparison to the most recent
  cached witness"* — again singular, no partial-read qualifier. **CONTRADICTION**
  by omission of the asymmetric bound.
- Terminology: the doc uses neither "incomplete read" nor "torn" — it has no
  vocabulary for this condition at all. Not itself a contradiction (nothing
  to contradict), but a **GAP**: a foreign implementer has no cue that a
  read can be partial in the first place.
- Mid-file damage / out-of-order ordinals: the doc's model (§07, §09) implicit­ly
  assumes a single linear append with no concurrent-writer hazard. Nothing in
  the doc states or implies that journal writes can land out of file order
  (the ratified `[90, 92, 91]`-is-legal fact), so nothing warns that "the last
  line" and "the head" can diverge. This is the same fact the implementation's
  `_known_of` docstring calls out by name (`arrival_head_attestation.py:932-956`):
  *"Two writers append concurrently... Last-line semantics would then read
  K=5 and classify a genuine restore to 5 as unchanged."* **GAP** — concurrent
  writers to one authority are not modeled anywhere in the doc (§06's
  "topologies" are about multiple *witnesses*/notaries, not concurrent
  *writers* to one store).

## Item 3 — Object-identity first contact

**Total GAP.** The entire location-binding / alias-detection mechanism
(`canonical_location`, `_identity_of`, `match_identity`, `aliased_lineage`,
the transitional `bindings.jsonl`) has no counterpart anywhere in the doc.

- §07 "First-contact limitation" (lines 411–417) is the doc's only discussion
  of first contact, and it is entirely about migration/bootstrap-receipt
  provenance ("new devices should retrieve a checkpoint from an already
  trusted device or witness"), not about *this* location having been seen
  before under a different spelling.
- The doc's comparison table's "No known head → First contact" row (line
  384) says only *"Establish trust from migration receipt, pinned witness, or
  explicit trust reset"* — no mention that, before minting first contact, an
  implementation live-stats existing bindings and (st_dev, st_ino)-matches
  the presenting location, routing a match through the existing binding
  (yielding `LineageReplaced` when lineages differ) instead.
- `canonical_location`'s explicit scope-the-claim — *"a SPELLING, not an
  identity"* (`arrival_head_seam.py:363-382`) — and its stated residual
  (distinct-dev/ino aliases, e.g. two network mounts of one export, are
  undetectable) have no counterpart in the doc's threat model (§02) or
  "Not claimed" list (lines 129–139). The "Not claimed" list is a natural
  home for this residual and does not carry it. **GAP**.

## Item 4 — Position-bound trust resets

**GAP, plus one likely CONTRADICTION.**

- The entire replay-safety mechanism — `follows = (physical line, identity)`,
  read-time honor check against the entry actually preceding it,
  skip-with-record (never refusal) on mismatch, the ceremony reading the
  tail judgment-free, and the read-back verification raising
  `TrustResetNotHonored` — has no home in the doc. §11's "All witness state
  lost" row (lines 557–557) says only *"Perform explicit trust reset from
  archives or operator ceremony and record the gap"* with no mechanism for
  how a reset is bound to a position, how a replayed reset is detected, or
  that failure to bind is non-fatal (recorded, not refused). **GAP**.
- Residual (truncation-then-replay realigns positions, undetectable
  unsigned) has no counterpart in the doc's "Not claimed" list (lines
  129–139) or attack matrix (§08). **GAP**.
- Possible **CONTRADICTION**: the "Witnesses move forward" callout (lines
  562–569) frames the *only* licensed way to move a witnessed ordinal
  backward as starting a **new lineage**: *"Normal operation never decreases
  a witnessed ordinal... A repair that intentionally starts a new lineage is
  explicit and retains a transition report; it does not rewrite the old
  witness into agreement."* The implemented `trust_reset()` ceremony instead
  operates **within the same lineage** — its own docstring example is *"an
  operator accepts a restore from ordinal 100 back to 90"*
  (`arrival_head_attestation.py:847-849`), i.e. the accepted head's ordinal
  is deliberately lowered for the *same* lineage, with the abandoned
  91–100 entries retained as evidence rather than superseded by a new
  lineage. A foreign implementer following the doc's callout literally would
  build a new-lineage-only repair path and miss the same-lineage,
  epoch-scoped walkback the implementation actually performs.

## Item 5 — Byte-dedup journal reads

**Total GAP.** Nothing in the doc anticipates that a duplicate (byte-
identical, stripped) line is treated as a re-assertion and skipped before
epoch/K computation, nor the stated rationale (a replayed historical advance
line could otherwise resurrect an abandoned head that a restored pre-reset
backup then presents as UNCHANGED). This is not addressed by the attack
matrix (§08, lines 420–454), which lists byte-flip, interior/tail deletion,
old-backup restore, and full re-chain, but no "replayed/duplicated journal
line" row. **GAP**.

## Item 6 — Epoch semantics

**CONTRADICTION on the model, GAP on the mechanism.**

- §07 (line 374) defines *K* as *"the last known or attested head"* with no
  epoch concept whatsoever — a single value, permanent for the lineage's
  lifetime. The implementation instead scopes *K* to *"the maximum-ordinal
  entry of the CURRENT trust epoch"*, explicitly **not** "the last line" and
  explicitly **not** unscoped across a trust reset (`arrival_head_attestation.
  py:932-941`, `_epoch_of` at 839-902). The doc's phrase "last known... head"
  is exactly the misreading the ratified rule corrects (last **written** vs.
  maximum **ordinal**, and unscoped vs. epoch-scoped) — a foreign
  implementer working only from the doc would build an unscoped, last-write-
  wins *K* and hit the deadlock the implementation's docstring names: *"the
  abandoned entries... still hold the maximum ordinal; unscoped, K would read
  as the head that was deliberately abandoned and every subsequent open would
  refuse a rollback forever."* **CONTRADICTION**.
- Trust-epoch reset boundary is **inclusive** of the reset entry itself
  (`_epoch_of` docstring, lines 852-857) — has no counterpart in the doc,
  which has no epoch concept to be inclusive or exclusive about. **GAP**.
- Equivocation detection scoped to the current epoch only (`_known_of` raising
  `JournalEquivocation` only across entries in `epoch`, not the whole journal)
  — the doc's "Same-height fork" comparison row (line 388) and the attack
  matrix's "Show two clients different descendants" row (line 439) describe
  equivocation in general terms but never scope it to "since the last trust
  reset," because the doc has no trust-reset/epoch model to scope against.
  **GAP**.
- Consequence already flagged under item 4: the comparison table's seven
  rows (§07) have no row at all for "a trust reset changed what counts as K,"
  i.e., no acknowledgment that the six comparison outcomes are evaluated
  against an epoch-relative K rather than a lineage-lifetime K. **GAP**.

---

## Where the doc already agrees

To be precise about what does *not* need correction:

- **The seven comparison outcomes** (first contact, unchanged, advanced,
  rollback, same-height fork, rewrite/history-rewrite, lineage-replaced) match
  §07's table (lines 383–393) and pseudocode (397–408) exactly, including
  guard order (lineage checked before any ordinal arithmetic) and the
  "never accept height as proof of continuity" principle for the
  advanced/rewrite split (matches the attack matrix's rehash-and-rechain row,
  lines 437, and the closing callout at 446-454).
- **The four-layer audit posture** (§09, lines 462–480: preventive controls,
  fast open checks, incremental verification, periodic full audit) matches
  the implementation's shape: `verify(Open())` for the O(1) fast check
  (`_present`), the ascend-only `verify(Full(...))` + `head_at(K)` descent
  check for incremental verification (`_descent`), and `audit()`'s full
  genesis walk plus `unaccounted_heads` for the periodic full audit.
- **§11's recovery table** (lines 546–560) — safe response vs. unsafe
  shortcut per finding — is faithfully mirrored in `_refusal_text`'s
  `responses` dict (`arrival_head_seam.py:1381-1399`) essentially verbatim
  ("never move the witness backward," "never pick the taller branch,"
  "the licensed way to accept it is the explicit trust-reset ceremony").
- **§05's "committed" vs. "witnessed" distinction** (lines 292–309) is
  implemented as the `NotWitnessed` exception's whole reason for being
  (`arrival_head_seam.py:170-197`) — data can be committed and durable while
  its journal entry failed, and the caller is told which happened rather than
  a collapsed "saved." (Caveat: the doc's "witnessed" implies a signing
  *quorum*, §06; the shipped "witnessed" is a single local, unsigned journal.
  Consistent with the adopted-minimum deferral in §13, not a contradiction.)
- **§05 "Unsigned memory is still useful"** (lines 311–317) correctly
  anticipates, in spirit, exactly what shipped: a cache of a previously seen
  head, scoped to lineage, kept outside the authority's rewrite boundary.
  It just has none of the concrete mechanism (read states, epochs, dedup,
  position-bound resets) that turned out to be necessary to make that
  anticipation correct — which is the throughline connecting items 1–6.
- **§13's adopted-minimum callout** (lines 655–665) correctly scopes what
  slice 3 was supposed to build (cache one head, bootstrap receipt, compare
  on every open, periodic full audit; signed grammar deferred) — the
  divergences above are about the doc's total silence on *how* that minimum
  was actually made safe, not a disagreement about *what* was in scope.

---

## Compressed divergence list

1. **Header classification** — GAP (total). Doc has no journal-file model at all; §04/§06 describe the deferred signed grammar, not the shipped unsigned header+entry format.
2. **Read states** — CONTRADICTION. §07 (line 374) and its pseudocode (397-408) model K as binary (head-or-None); ships as four states with an asymmetric `HeadLowerBound`. GAP on terminology ("incomplete read") and on concurrent-writer out-of-file-order ordinals — unmodeled in doc.
3. **Object-identity first contact** — GAP (total). `canonical_location`/`aliased_lineage`/stat-based identity matching and the dev/ino-alias residual have no doc counterpart; doc's first-contact discussion (§07, 411-417) is about migration provenance only.
4. **Position-bound trust resets** — GAP (total, mechanism). Possible CONTRADICTION: doc's "Witnesses move forward" callout (562-569) frames backward movement as licensed only via a *new lineage*; the implemented ceremony walks the *same* lineage's K backward within a bounded epoch.
5. **Byte-dedup journal reads** — GAP (total). No mention of line-level replay/dedup anywhere, including the attack matrix (§08).
6. **Epoch semantics** — CONTRADICTION. §07's K as "the last known... head" (line 374) has no epoch scoping; ships as max-ordinal-of-current-epoch, inclusive reset boundary, epoch-scoped equivocation. GAP on the inclusive-boundary and epoch-scoped-equivocation details specifically.

Agreement (no correction needed): the seven comparison outcomes and their
guard order (§07); the four audit layers (§09); the §11 recovery-response
table; the committed/witnessed split (§05, modulo quorum vs. single-witness
scope already deferred by §13); the general shape of "unsigned memory is
still useful" (§05); and §13's adopted-minimum scope statement itself.
