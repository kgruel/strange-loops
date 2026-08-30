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
| engine | 2158 passed, 1 skipped | 2233 passed, 1 skipped | **+75** |
| architecture | 99 passed | 99 passed | **0** — Rule 18 is not parametrized per target |

Every delta accounted for: **+57** in `test_arrival_head_seam.py`, **+1** in
`test_arrival_registry.py` (`test_closing_a_query_that_never_read_does_not_build_a_reader`),
and **+13** in `test_arrival_head_attestation.py` (sol r1's replay repro and its
siblings, plus sol r2's context-replay family). Three of the seam file's are the gate round's — the BLOCKING repro,
the second refusal behind the same write, and the AST ratchet — and seven are sol
r1's alias work.
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

## S3I-L-3 — the fence's own probe failed open

`finding:s3-fence-probe-fails-open`. The fence I built to close sol's
acceptance loop contained a probe that lied on the acceptance side, and sol
reproduced the entire self-erasing cycle through a transient `OSError`: descent
verifies, the anchor probe raises, the advance is accepted **and journaled**,
and the next open — on a perfectly healthy ledger — reads UNCHANGED.

**The comment I wrote on that catch stated the error out loud**: *"no answer is
no evidence of a touch."* Evidence absent is not absence of evidence. Every
other broad catch in this seam is justified in the report by landing on the
refusing branch, and I had written that rule three separate times without
applying it at the one site where the fallback direction was acceptance.

**The fix**: an unanswered probe raises `FenceProbeUnanswered`. A **sibling** of
`AbandonedHistoryFenced` rather than an arm of it, because the claims differ and
so do their remedies — one says *your history touches decreed-away ground* and
is answered by the ceremony; this says *I could not determine whether it does*
and is answered by retrying. Named for what the read lacks rather than for what
failed, because a cause-name does not survive a second cause.

**Not the degradation posture**, by that posture's own rule: it proceeds only
after firing every refusal the evidence soundly supports, and an uncertified
fence path is a refusal the evidence demands. Being wrong here costs one retried
open; being wrong the other way costs silent re-acceptance of decreed-away
history.

### Probe audit — the fence

The finding is about the pattern, so every site was checked rather than the one
line. The fence has **exactly one** probe. Its lift check is pure ordinal and
lineage comparison with no I/O, and its two early returns are structural
conditions rather than probes, so neither can fail open. `_descent` and
`_vouched_at` both catch broadly and both land on refusal, unchanged.

### Mutation demo

Two-guard: committed `333021bc` first, tree byte-clean after the revert.
Catch-and-continue restored → **2 failed, 67 passed**, and the loop reproduced
directly rather than inferred:

```
probe raises on the anchor, restore  => advanced
journal now holds ordinal: 2
next open, CLEAN ledger              => unchanged   <- the loop, via a transient error
```

The first attempt at this demo mis-constructed the probe — failing *every*
`head_at` made `_descent` refuse first with `HeadRewrite`, which is the seam
correctly failing refusal-side and proves nothing about the fence. The probe has
to fail selectively, at the anchor ordinal only, for the fence to be the thing
under test.

### The same shape, outside the fence — reported, not fixed

Scoped out of this round, but the pattern audit found it and it should be ruled
rather than left: the **transitional binding unit** has three catches that all
fail acceptance-side.

| Site | Failure read as |
|---|---|
| `aliased_lineage`, `except OSError` | "no alias" — a bindings file that exists but cannot be read (permission wall, I/O error) means a replacement slips past `LineageReplaced` as first contact |
| `_identity_of`, `except OSError` | "no identity" — defensible for a path that genuinely does not stat, but an I/O error at a path that does exist reads the same way |
| the binding line loop, `except ValueError` | "skip" — a malformed line could be the very binding that named the alias |

All three are the S3I-L-3 shape with a different consequence: not the
self-erasing loop, but a silent first contact where a replacement should have
refused. Left alone because this round is scoped to the fence and that unit
carries its own `DELETE IN SLICE 5` marker — but it is the same finding, and the
deletion is not a reason to leave it wrong in the meantime.
`finding:s3wp3-binding-probes-fail-acceptance-side`.

## Design amendment #6 — the abandoned-history fence

Sol's integration round escalated my own N+1-descendant flag from deferred to
blocking, and it was right to. I had reported the acceptance as an
underdetermination; sol showed it was a **loop**.

**The loop.** Reset from an abandoned *N+1* back to *N*, restore the authentic
backup, and the open verifies descent **honestly** — the chain really does reach
*N+1* from *N*. So it answered ADVANCED, **journaled** *N+1* back into the
current epoch, and every later open read UNCHANGED. No refusal, no fork, ever,
and repeatable indefinitely. The acceptance erased its own evidence by recording
it, which is why nothing downstream could see it had happened.

Verified descent was never the whole question. A chain can be perfectly intact
and still be the history a ceremony put behind us — and machinery does not
silently reverse an operator's decree.

**The fence**: an ADVANCED outcome whose verified descent touches an entry
journaled in an abandoned epoch is refused with `AbandonedHistoryFenced`, whose
message teaches the ceremony as the acceptance path.

### The four pins

1. **Identity-keyed anchors** — `(ordinal, hash)` against the abandoned epochs'
   journaled entries, never ordinal spans. An operator who resets to 5 and lets
   the store re-advance mints a **new** 6, 7 and 8 inside the abandoned span; a
   span fence would refuse every one of them forever and make the ceremony a
   store's last act. Pinned from the other side by
   `test_a_legitimate_re_advance_inside_the_abandoned_span_is_accepted`, which
   asserts the same ordinal with a different hash is still ADVANCED. The
   abandoned entries remain readable in the file — epoch scoping excludes them
   from *K*, never from the read — which is what makes them available as
   anchors at all.
2. **Reach across the whole descent**, not the head alone: a branch grown
   offline presents *N+3* while the anchor sits at *N+1*. Asking `head_at` at
   each fenced anchor's own coordinate is the complete form of that check —
   an anchor can only be touched at its own ordinal — and it stays in contract
   ops, so the fence is backend-neutral like the rest of the seam.
3. **The lift rule**, or the ceremony re-bricks the store — L-3's shape exactly.
   **Verified before building, as instructed**: `trust_reset` *can* decree a
   head at or above current *K* (nothing guards it; confirmed by decreeing
   ordinal 9 over a *K* of 3), and the reset entry *does* carry the decreed
   coordinate, so the new epoch's *K* is the decreed head — the epoch is
   reset-inclusive. Both yes, so the rule is buildable and I proceeded.
4. **Placement** after ADVANCED and before anything is earned. `compare` stays
   the pure seven-outcome machine, and a fenced open journals nothing —
   `test_the_fenced_open_journals_nothing`, because the acceptance recording
   itself is what made the loop invisible.

### One narrowing of the lift rule's wording, and why

The rule as written is "fenced only when NO later reset decrees at/above it".
Read literally that reopens the loop with one extra step: reset to 10, then
reset back to 5, and the entry at 10 is lifted by the decree the second ceremony
overrode. Implemented against the **current boundary decree** only — the one
decree nothing has superseded. It fences more, never less, and the recovery path
is unaffected because a recovery decree *is* the boundary decree.

### Mutation demo

Two-guard: committed `4061f0c9` first, tree byte-clean after the revert. Fence
reverted → **5 failed, 61 passed**, and sol's cycle reproduced directly rather
than inferred:

```
restore of abandoned backup => advanced
next open                   => unchanged   <- the cycle
```

### Consequence swept

`trust_reset`'s disclosure sentence said verified descendants including
re-presentations of abandoned history "are accepted". That is now false. It
states the fence, names the one-ceremony recovery cost, and records what it used
to say and why that was the loop.

## Design amendment #5 — weakening is epoch-scoped by line position

From my own verify-item-1 answer. Weight is now **cause × position**: the cause
half already existed (a re-assertion never weighs); the position half is that a
line-positioned loss sitting **before the boundary reset's line** carries zero
weight. The ceremony decreed trust in a head, and everything positionally behind
that decree is what it decreed past. Appends are tail-only, so a line's position
in the file is its place in time — the non-ascending order this journal
documents is about **ordinals**, which two writers interleave, never about
positions, which the filesystem serializes.

The four edges, each stated in code rather than left to fall out of a
comparison:

1. **Structural absences are exempt.** A missing header carries no line, which
   is what marks it structural; it keeps full weight at any boundary.
2. **`at_least` is epoch-scoped** — verified, and it already was (below).
3. **No valid reset → no boundary → full weight everywhere**, spelled out,
   because "there is nothing to be after" is a different situation from "this is
   after it".
4. **Below means physical line**, the same coordinate system as `follows`.
   Ordinals never enter it.

**Mutation demo** (committed `d39e6cfa` first, tree byte-clean after revert):
position scoping reverted → **2 failed, 176 passed** —
`test_damage_behind_the_boundary_no_longer_weakens_the_read` and
`test_damage_on_both_sides_bounds_from_the_current_epoch_only`.

### Edge 1 — what the header actually carries, and why it changes nothing here

The header holds `v`, `type`, `protocol` and `wire`. The exemption is right on
its own terms: the absence is a claim about the file rather than about a line.

But the concrete claim it protects is **not enforced anywhere today**. Grepping
the module, `_PROTOCOL_VERSION` and `_WIRE_VERSION` appear at their definitions
and at the single write site, and **nowhere else** — nothing reads them back, so
"a v1 journal is never silently compared against a v2 head" is still the half-kept
promise WP1 named, with wire v2 as its forcing consumer. So a headerless journal
today weakens a read on the strength of a check that does not yet exist.

That does not change the implementation — an unenforced claim is exactly the kind
that should keep its weight until the enforcement lands, and exempting it would
mean re-deciding when wire v2 arrives. Reported because you asked whether it
changes the picture: it changes the *reason*, not the *ruling*.

### Edge 2 — `at_least` was already epoch-scoped

Verified rather than assumed. `best = _known_of(epoch)` takes the epoch, not the
file, so an abandoned-epoch high ordinal cannot inflate the bound. Confirmed
empirically: abandoned epoch reaching 100, reset to 90, current epoch at 91-92
with damage — `at_least` reads **92**, not 100. No fix was needed;
`test_damage_on_both_sides_bounds_from_the_current_epoch_only` pins it so it
cannot regress.

### One thing the mutation demo caught in my own prose

The healing test did **not** fail under the mutation, and the reason matters: a
voided-reset note can only come from a reset **above** the boundary, because
`_epoch_of` walks backward and returns at the first valid one. So the position
filter never exempts a voided reset — and the comment I had written, saying a
failed attempt behind a later successful one "weighs nothing", described a path
nothing can reach. Corrected at the site and in the test's docstring: that
construction heals through the walk short-circuiting, and position scoping is
exercised by the damage tests instead. It is the same stale-prose failure this
file has paid for repeatedly, caught this time by running the mutation rather
than by reading.

### The disclosure sentence

Carried in `trust_reset`'s docstring, with the open question named: a reset
decrees trust in *N*; verified descendants of *N*, including re-presentations of
abandoned history, are accepted; fencing out authentic history is not
expressible unsigned. Ledgered as
`design:arrival-reset-descendant-acceptance`, Kyle's call at the slice-6 gate.

## Design amendment #4 — a re-assertion is recorded, and carries no weight

`finding:s3-dedup-skip-weakens-read-permanently`. WP2's integration found the
cost of the dedup gate I shipped: a byte-identical crash-retry duplicate is
byte-identical **by construction**, and the journal is append-only, so weighting
its skip bounded every subsequent read **for the life of the file** —
`established_head()` raising forever, and the O(1) unchanged-open design gone,
from a crash that lost nothing.

**Per cause, not per read.** The tempting shape is "a read whose only skips are
re-assertions is established", and it does not compose: a duplicate beside an
unreadable line must still bound. Weight therefore lives on the cause. `_Skips`
offers `missed()` and `re_asserted()`, so a call site names its cause by which
method it calls and a new cause has to choose rather than inherit a default.
`test_a_dedup_skip_beside_an_unreadable_line_still_bounds` is the composition
pin, and it fails in both directions under mutation.

Grounds, in one line: the bound machinery represents **ignorance**, and a
re-assertion is the one cause that carries none — the skipped line's content is
a line this read already counted. Held narrowly as ruled: a voided reset keeps
its weight, because what is unknown there is not the bytes but what the operator
meant by them (`test_a_voided_reset_keeps_its_weight`).

`HeadLowerBound` now carries only the **weakening** subset, so the causes of a
bound are readable off the bound itself, while `JournalRead.skipped` keeps the
full record. Three prose sites said a non-empty `skipped` *is* the weakening
condition; all three are swept — the same stale-prose trap this file has already
paid for four times.

`_Skips` is a plain class rather than a dataclass. Rule 5 flagged it, and it was
right: lib dataclasses are frozen because they are value objects, and this is an
accumulator. Declaring it `frozen=True` with mutable lists inside would have
satisfied the rule's letter while holding exactly the state the rule is about —
gaming a ratchet instead of answering it.

**Mutation demo** (two-guard: committed at `fa1d4d87` first, tree byte-clean
after the revert): re-assertions weigh again → **10 failed, 162 passed**, led by
`test_a_crash_retry_duplicate_does_not_weaken_the_read_forever` failing with the
permanent bound — `established_head()` refusing on an incomplete read.

### Verify-item 1 — is skip weakening epoch-scoped? **No.**

**Reported, not fixed, per the routing.** Weakening is **file-scoped**. The code
path: `_scan` accumulates skips over *every line of the file*, with no epoch
notion available to it at all — the epoch is not computed until
`parse_journal_lines` calls `_epoch_of`, well after the scan has finished — and
`known` is then weakened by testing that whole-file set
(`parse_journal_lines`, the `if skips.weakening` branch).

Confirmed empirically as well as by reading: a journal with a damaged line at
line 3, a trust reset later, and a clean advance after it, reads
`HeadLowerBound` even though the damage sits **below** the current epoch
boundary.

The consequence is the one the routing anticipated: **mid-file damage and
TOCTOU-voided reset lines are unhealable, even by the reset ceremony.** An
operator who runs the ceremony to recover gets a new epoch whose *K* is correct,
and a read that is still bounded by a line the ceremony deliberately put behind
it. That is a question back to you rather than an edit.

### Verify-item 2 — the abandoned-backup regression: **ADVANCED, not REWRITE**

It did strengthen — the read is now ESTABLISHED, so the comparison **completes**
rather than declining on a bound — but the outcome is `ADVANCED`, not the
`REWRITE` the routing predicted, and the reason is my construction rather than
the ruling. The test resets to a truncated **prefix** of the same history, so
the restored backup genuinely *is* a verified descendant of the accepted head:
the full walk succeeds and the record at *K*'s ordinal is *K*'s. `REWRITE` is
what a genuinely divergent abandoned history would give.

Deterministic, so the assertion is tightened from "not UNCHANGED" to
`Outcome.ADVANCED`. L-5 stays closed: without the dedup gate, *K* still reaches
the abandoned head, the backup still compares EQUAL, and the unchanged arm still
gathers no evidence — the vector the test exists for is unchanged.

**One observation this surfaced, flagged rather than actioned** (out of scope,
and a question for you): after a reset to head *N*, restoring a backup at head
*N+1* that is a valid descendant of *N* is **accepted** through the advance
path, even when *N+1* is precisely the head the ceremony abandoned. The reset's
`note` records the gap; nothing compares against it. Same family as the
replayed-advance vector, and not reachable through the dedup gate.

### Known consequence, preserved rather than fixed

The dedup match predicate is now **acceptance-load-bearing**: a false match
discards a real line and the read still claims to be established.
`test_an_injected_collision_costs_a_walk_and_never_an_acceptance` carries that
weight and now pins it explicitly — established at a LOW *K*, so the store
presents an advance, and the advance branch demands a vouched `at_known` before
anything is accepted. Verification-side, never acceptance.

## Sol r2 — L-1 passed; L-2 failed twice over, both closed

### S3WP3-L-4 — identity was the right binding and the wrong amount of it

Identity is a property of the bytes, so **bytes can carry it**. Sol replayed the
historical predecessor *and* the reset as an ordered suffix: the copy names an
entry that really is sitting in front of it, the recorded identity matches, and
K went 8 → 5 with **no skip record**. Reproduced before changing anything.

`follows` is now **(physical line, identity)**. The line is what closes the
class rather than the instance: copied bytes appended later always land later,
so a stale position claim is unavoidable no matter how much surrounding context
is replayed with them. The two-line replay, a full-suffix replay and a wholesale
journal concatenation now fail the same check for the same reason. Identity
stays in the pair because position alone would accept a truncation that happens
to realign a different entry onto the recorded line.

**Physical line, never an index among parsed entries.** An index is a judgment:
a future build that classifies one line differently renumbers every entry after
it and silently voids every reset bound below. Physical line N is line N forever
in a file that is only ever appended to. `_scan` therefore carries the file's own
1-based line number for every entry, counted over lines this build skipped too,
and `test_the_position_is_the_physical_line_not_an_index_of_parsed_entries`
pins the distinction with an unreadable line sitting between a reset and its
predecessor.

**The obligation the position claim buys its protection with.** Binding to a
line means reading the tail and then appending, and **there is no lock to hold
across the two** — the journal is append-only precisely so that writers need
none, so this is not an oversight to fix by taking one. A peer appending in that
window leaves a legitimate, freshly written reset carrying an already-stale
position, which a later reader declines to honor. The direction is safe (the
higher abandoned head still stands, so opens keep refusing); what is not safe is
silence, because an operator who saw the ceremony return believes their store
will now open. So `trust_reset` reads its own entry back against the same
judgment every reader applies and raises `TrustResetNotHonored` if it did not
take. Emit-then-read-back, the store's own ethos: the append landing is not the
same claim as the append counting.

**Residual, documented at the site and here.** Truncating the journal and then
replaying realigns positions, and this cannot detect it. That is journal-rollback
territory — the known bound of unsigned local state, the same class as deleting
the journal outright and being met with trust-on-first-use. The named upgrade is
the deferred signed grammar, whose chained entries make a truncation detectable
rather than merely disbelieved.

### The number that differed — and the acceptance vector behind it

**SUPERSEDED. My analysis of this was wrong, and the ruling is FIX.**

I reported that sol's repro left *K* at 10 rather than the predicted 8, and
classified it as safe because *K* had moved **up**. That is the wrong axis. The
axis that matters is *K*'s **referent**: the head it then named was a
**genuine** head this machine really did accept, so a store restored from the
pre-reset backup presents it exactly, compares **equal**, and the unchanged arm
gathers no descent evidence by design — nothing else is ever consulted. The
ceremonially abandoned state simply opened. Verified at source before fixing: on
the pre-fix tree, `compare(K, head(10), None)` answers `unchanged`. A
wrongly-raised *K* naming a real abandoned head is a landing pad, not a wall.

My second claim was wrong in the same direction. "Nothing unsigned can tell a
re-assertion from a first assertion" is true in general and false for the case
that matters: **bytes can**, for a *literal* replay — and literal replay of
existing bytes is precisely the threat model. Anything that modifies the bytes
is forgery, which is the deferred signed grammar's territory and not this
gate's. That is a clean scope split, and I had talked myself past it.

**The fix: a line byte-identical to an earlier line is a re-assertion**, skipped
through the existing skip channel. Per-line and **type-agnostic** — a replayed
`audit` carrying an abandoned covered head poisons *K* exactly as an `advance`
or a `trust-reset` does, so a per-type rule would be a list that grows.
Order-agnostic (it compares bytes and never consults an ordinal, so the
non-ascending write order is irrelevant), read-side only, and it changes no
record shape, producer or lock. **Headers are exempt** and that is not a
per-type carve-out: a header carries no claim about any head, and two of them is
an explicitly tolerated create-race artifact, so deduping one would turn a race
this design chose to survive into a permanently weakened read.

**Collision direction, pinned rather than argued from improbability.** Two
genuinely independent events that serialize identically are indistinguishable
from a replay, so the gate drops the later line and *K* reads **lower** than the
truth. The store then presents a head above it — an ADVANCE — and the advance
branch is the one that pays for a verified walk before anything is accepted.
Cost, not credulity: the failure lands on the verification side.
`test_an_injected_collision_costs_a_walk_and_never_an_acceptance` constructs the
collision rather than assuming it cannot happen.

**Reconciled, not left contradicting.** Sol's repro flips back to **K = 8 with
two skip records** — both copied lines are literal replays — and the divergence
comment, the finding pointer and the 10-assertion are all updated to that truth.
The residual test flips into the acceptance-vector test it had been hiding.

**Two of my own fixtures were wrong, and the gate found them**: they modelled a
post-reset advance as byte-identical to a pre-reset one, which no real store
produces — after a restore the store re-advances through a *different* history.

**Position-binding needed its own case, and its first one was fake.** The replay
tests now die on the byte-duplicate gate before the position claim is consulted,
so position's coverage would have been an illusion. I wrote a dedicated case —
a line inserted ahead of a reset's predecessor, bytes unique so dedup cannot
fire — and the mutation demo **caught the test**: dropping the position half
failed nothing, because my construction broke *identity* too and would have
passed against a build with no position check at all. Corrected so identity
matches on both sides and only the line moves, and the test now asserts that
equality itself, so a construction that stops isolating position fails here
instead of passing quietly.

### S3WP3-L-3 — the previous round's fix was hollow

Sol was right, and this one is a straightforward failure of mine. `trust_reset`
still called `read_journal`; `last_entry` existed and **only test fixtures used
it**. The seam edit that was supposed to wire the caller never applied — the
script that made it died on a later assertion, before its write — and I reported
it as done on the strength of a print that never ran.

The test did not catch it because **the test pinned the helper, not the
caller**, and its fixture built an *old-epoch* equivocation, which `read_journal`
tolerates anyway. So it would have passed against a ceremony that was still
bricked. The regression now builds a **current-epoch** equivocation — the state
that actually refuses — and drives the real producer. That is also why the L-3
mutation demo below reverts the **call site** rather than the helper: a
helper-revert demo would prove nothing about the hole that existed.

## Sol r1 — two blocking findings, both closed

### S3WP3-L-1 — a spelling is not an identity

`finding:s3wp3-canonical-location-alias-first-contact`. `canonical_location`
normalizes a path; it does not establish which filesystem object a path names.
A case-variant spelling on a case-insensitive filesystem — the macOS default —
or a second mount of one volume reaches the very same store through a string
`resolve()` returns unchanged and different. Bound under one spelling and
presented under the other, the store has no binding, reads as **first contact**,
and a replacement with a fresh lineage walks past `LineageReplaced`.

**Scope the claim, then detect at the boundary** — both halves, per the ruling.
The docstring stops asserting identity and names the residual honestly: aliases
that report genuinely *different* `(st_dev, st_ino)` — two network mounts of one
export is the ordinary case — are beyond anything a client can detect from here.
Then, and only when the presenting spelling has no binding of its own, the seam
live-stats each recorded binding and compares device and inode. A match means
this is not first contact, and the open routes through that existing binding —
which refuses when the lineage differs.

Three properties the ruling asked for, each held by construction:

- **Live-stat, never record.** A stored inode goes stale when a file is
  recreated and gets recycled onto unrelated files, so recording one turns a
  fact into a claim that rots into a false match. `Identity` is only ever
  computed at comparison time; bindings whose paths no longer stat are skipped,
  because a path that cannot be stat'd makes no claim either way.
- **Fires before anything is earned.** The check sits in the binding arm, ahead
  of the journal read and well ahead of `_judge`, so it can only add a refusal
  earlier — no new write site and no change to the `_write` path. The AST
  ratchet cannot see an ordering regression here, so
  `test_the_alias_refusal_leaves_the_journal_untouched` asserts it on bytes.
- **Costs nothing on the dominant path.** Once a binding exists for the spelling
  in use, the exact lookup answers and the sweep never runs; the unchanged open
  still gathers only its single `verify(Open())`, asserted by op count.

**The CI portability trap, handled as ruled.** The alias can only be
*constructed* on a case-insensitive filesystem, so the end-to-end test probes
the filesystem at run time and skips with a reason naming the portable test that
covers the judgment. And the judgment is factored out: `match_identity` takes
identities as arguments, so its logic — newest-binding-wins, unstattable paths
skipped, absent presenting path answers nothing — is pinned on every platform by
four unit tests. A green Linux run cannot mean the vector was never exercised.
(On this macOS worktree the construction test genuinely runs and passes rather
than skipping.)

### S3WP3-L-2 — a trust reset was replayable

`finding:s3wp3-trust-reset-replay`. An entry is bytes in an append-only file, so
an old reset can simply be appended again. Under last-reset-wins it re-opens the
epoch it had closed: sol's repro — a journal advanced to ordinal 8 carrying a
legitimate reset that had accepted 5 — reads **K as 5** once the stale reset is
replayed, so a store rolled back to 5 opens UNCHANGED and the abandoned epoch is
resurrected. Silent re-acceptance through the one entry kind whose whole job is
to be the licensed way down. Measured under the reverted fix: **K = 5**, exactly
sol's number.

**Construction over detection.** Each reset now names the entry it was appended
after (`HeadAttestation.follows`), so a replayed copy is *inexpressible as
valid* rather than merely detectable — at any other position the recorded
predecessor is not the entry actually in front of it.

- **Predecessor identity, not the effective head and not a count.** Two journal
  states can share a head while differing in history, and a count is not a
  history at all. The predecessor link is also this repo's own chain idiom.
- **`follows` is deliberately NOT the deferred `previous`.** WP1's §B.2 defers
  the signed grammar's per-entry chain link, and that stays absent. This is
  unsigned, carried by exactly one kind, and makes exactly one claim.
- **Read-time validation is the load-bearing half.** `_epoch_of` honors a reset
  only if its binding matches; a mismatch is **not an epoch boundary** and the
  scan keeps walking back for an earlier valid one — so rejecting a replay does
  not reject the reset it was copied from, which would have reintroduced the
  deadlock the epoch scoping exists to prevent.
- **A mismatch is a skip record, never a refusal.** Refusing would brick every
  open on a benign crash-retry duplicate, where the same reset is appended twice
  and the second copy's predecessor is the first. The direction of the lie is
  the safe one either way: misjudging a legitimate reset leaves *K* at the
  HIGHER abandoned head, so the failure is refusal-side. Note the deliberate
  consequence — a non-empty `skipped` weakens the read to a `HeadLowerBound`, so
  a journal holding a replay still refuses anything below the bound, which is
  the attack it was closing.
- **The field is required; there is no binding-less compat arm.** The journal
  format exists only on unmerged slice-3 branches, so an "unbound resets still
  count" path would be a permanent hole built for deployed state that does not
  exist.

**One thing the fix nearly broke, caught by an existing test.** Binding at
append first read the journal through `read_journal` — which *refuses* an
equivocating journal. Equivocation is precisely one of the states an operator
runs this ceremony to resolve, so the recovery path would have been unusable
exactly when it is needed. The scan is now factored so `last_entry` reaches the
entries without the judgment built on top of them, and
`test_binding_a_reset_does_not_require_a_readable_head` pins it.

**WP1's module is no longer byte-identical to `9ed893fe`**, and that departs from
this WP's original non-goal ("no module changes; behaviors you believe wrong are
FINDINGS"). It is deliberate and routed: the ruling names
`arrival_head_attestation.py:791 _epoch_of` as the fix site, and the read-time
half cannot live anywhere else. WP1's own reset fixtures were updated to bind,
since an unbound reset is not one any writer can now produce.

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

## NB-3 — what the write-site ratchet claims, and what it does not

The gate's last non-blocking item, and the disposition is the house rule: **scope
the claim, do not widen the detection.**

`test_only_the_constructor_and_the_producers_write_to_the_journal` matches
DIRECT-NAME calls — `ast.Call` whose `func` is an `ast.Name`. Five spellings
evade it, and the sharpest is entirely innocent: switching the module to
attribute-style imports (`arrival_head_attestation.append_entry(...)`) leaves the
scan **green with zero offenders** while every write site goes invisible.

**Verified first-hand rather than taken from the gate's report.** Reconstructing
the pre-fix state — mutation (i) applied *and* the precondition assertion removed
— the ratchet passes. Silent blinding is the worst failure a ratchet can have,
because it is indistinguishable from success.

**Why the matcher was not widened.** A detector chasing every spelling would
still miss one, and it would be asserting *"no write escapes"* — a verdict claim
— where the evidence only supports *"no direct-name write escapes"*, a location
claim. Growing it is the move that turns a ratchet into something that overclaims
and then falls.

**What was done instead.** The precondition the match depends on is now asserted
before the scan that depends on it: every writing name must be a module-level
binding, imported by name or defined here, because that is exactly what makes a
call to it parse as `ast.Call(func=ast.Name)`. If one stops being bound that way,
the test fails **loudly and names the import** rather than passing by detecting
nothing. Mutation (i) demonstrates it: `['append_entry'] are no longer
module-level bindings ... would pass by detecting nothing`. The docstring states
the scope in the same terms.

**The residual, stated.** The other spellings — an alias, a `getattr`, a call
through a captured reference — remain undetected by this test and are covered
today by the byte-compare behavior tests. The gap this ratchet exists for is a
later branch that has no behavior test yet, and for that branch the direct-name
form is the one somebody actually writes. That is the whole claim.

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
| (a) | journaling-on-commit dropped from `_witness` | **4 or 5 failed** — see NB-1 — the four deterministic are `test_commit_then_open_takes_the_o1_path_not_the_advance_path` (the next open observes an ADVANCE and pays two walks), `test_an_append_through_the_wrapper_journals_its_commit`, the `NotWitnessed` test, and the race pin |
| (b) | `canonical_location` returns the location unchanged | **1 failed, 69 passed** (with the registry file) — `test_the_binding_matches_through_a_non_canonical_path`: the replacement goes undetected and the store is trusted on first contact |
| (c) | the seam swallows `IndeterminateComparison` by re-deriving *K* from `read.epoch` — the bypass WP1 explicitly named as reachable | **3 failed, 43 passed** — `test_an_incomplete_read_proceeds_labeled_at_or_above_the_bound`, `test_a_journal_with_no_readable_content_is_not_granted_a_receipt` (a receipt is written for an unreadable journal — BLOCKING-2 reborn), `test_the_carried_refusal_is_the_one_the_journal_itself_raises` |
| (d) | the across-time re-read removed | **2 or 3 failed** — see NB-1 — the two deterministic are `test_a_commit_racing_the_open_is_not_reported_as_a_rollback` and `test_a_genuine_rollback_survives_the_re_observation` (which pins the op count, so the fix cannot be faked by weakening the refusal) |
| (e) | the earned bootstrap entry written inside `_observe`, before the projection comparison can refuse | **1 failed, 45 passed** — `test_the_refused_truncation_left_no_memory_claiming_it_was_accepted` |
| (f) | the rollback-from-a-bound arm removed from `_degraded` | **1 failed, 46 passed** — `test_an_incomplete_read_still_refuses_a_head_below_the_bound` |
| (g) | the bound treated as an established head, so the seam answers from it | **4 failed, 43 passed** — `test_an_incomplete_read_proceeds_labeled_at_or_above_the_bound` (answers `unchanged`), `test_an_incomplete_read_does_not_answer_advanced_above_the_bound` (answers `advanced`), plus the receipt and carried-refusal tests |
| (h) | the pre-fix inline ADVANCE write restored in `_judge` | **3 failed, 47 passed** — `test_an_advance_is_not_journaled_when_the_projection_then_refuses`, `test_an_advance_is_not_journaled_when_the_projection_disowns_the_log`, and the AST ratchet `test_only_the_constructor_and_the_producers_write_to_the_journal` |
| (i) | `append_entry` reached through an attribute-style import instead of by name | **2 failed, 48 passed** — the ratchet's precondition assertion fails naming `['append_entry']`; also `test_a_journal_write_failure_after_a_commit_says_the_records_are_committed`, which monkeypatches the module attribute the mutation removes |
| (L-1) | the object-identity sweep reverted in the binding arm | **1 failed, 56 passed** — `test_a_case_variant_spelling_of_a_bound_store_is_not_first_contact`: the replacement raises nothing and the alias spelling silently first-contacts |
| (L-2) | read-time reset validation reverted in `_epoch_of` | **4 failed, 154 passed** — sol's repro leads, and *K* measured directly under the mutation is **5** where the journal reached 8; also the genuine-reset, crash-retry and unbound-reset tests |
| (L-3) | `trust_reset`'s CALL SITE reverted to `read_journal` (the helper left correct and unused — the shape of the r2 hole) | **3 failed, 56 passed** — `test_the_ceremony_succeeds_on_an_equivocating_journal` leads, plus the gap-recording and epoch-scoped-staleness tests |
| (L-4) | the POSITION half dropped from read-time validation, identity alone again | **1 failed, 168 passed** — `test_a_reset_whose_predecessor_moved_lines_is_not_honored`, the fresh-bytes construction. (Before the dedup gate this failed the two context-replay tests instead; those now die on dedup first, which is why position needed a case of its own.) |
| (L-5) | the byte-duplicate gate reverted | **9 failed, 160 passed** — and the sharp one is `test_a_restored_abandoned_backup_does_not_open_unchanged`, which fails with *the abandoned state opened unchanged*: the acceptance vector itself, reproduced |

**NB-1 — two demos have a nondeterministic failure SET, and the earlier counts
here were wrong twice over.** `test_two_writers_and_an_opener_leave_a_parseable_journal`
spawns three real processes, so it is an intermittent participant in mutations
**(a)** and **(d)** alike. Measured five runs each against the fixed tree:

| Demo | Deterministic | Intermittent | Observed |
|---|---|---|---|
| (a) | 4 | the concurrent run (2 of 5) | 4 or 5 |
| (d) | 2 | the concurrent run (2 of 5) | 2 or 3 |

The causes are structural and differ per demo. Under **(a)** the opener subprocess
still journals through its *own* ADVANCED branch — a different write path, which
the mutation does not touch — so whether the journal's maximum-ordinal entry ends
up equal to the store's final head depends on when that opener last ran relative
to the two writers. Under **(d)** the opener can hit the false rollback the
re-read exists to prevent, which exits its subprocess non-zero and trips the
returncode assertion — but only when the interleaving actually occurs.

Neither conclusion depends on it: the deterministic failures kill each mutation on
their own, and the concurrent test is a bonus catcher in both.

**Correcting my own record.** This entry first read "5 failed" for (a) — one
sampled run reported as a stable fact — and was then "corrected" to "7 or 8",
which was worse: those five samples were taken while the BLOCKING-1 fix was
absent from the working tree (a `git checkout` during an earlier demo had reverted
it), so three of the counted failures were the missing fix rather than the
mutation. The numbers above are re-measured against the committed, fixed tree and
agree with the gate's independent measurement. A mutation demo reporting a sampled
count as a fact is the same defect class as prose asserting an enforcement the
code does not perform — and a demo measured against a tree you have not verified
is a worse one, because it looks like evidence.

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
