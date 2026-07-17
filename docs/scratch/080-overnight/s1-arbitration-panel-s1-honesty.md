# Panel review — PARADIGM-HONESTY lens on s1-arbitration.md (incl. v2)

*2026-07-17, Claude skeptic panel. Lens: every amendment tested against SPEC
normative clauses (§6.2, §8.4, §8.5, §9.3, §9.4, §9.5, §10) and the honesty
charter (rewound reads never silently lie; era rules; never retro-claim).
All load-bearing claims re-derived empirically; nothing deferred to the codex
pass or the arbiter's own citations. Verdict: **AMEND** — the axis survives
every break attempt; five named fixes, none structural.*

## What was verified empirically (not taken from the documents)

- **F5's decisive evidence is exact.** `sqlite3` against
  `.loops/data/project.db`: 2,176 facts with `ts <= 2026-06-01`; first tick
  2026-06-12 15:03:48; zero NULL-`fact_cursor` ticks. Against
  `.loops/data/archive/project.pre-rebirth-2026-06-12.db`: 216 ticks, 211
  with NULL `fact_cursor`, last tick at-or-before June 1 is 2026-05-20 with
  no usable cursor. Wall-clock addressing over the pre-June corpus genuinely
  has no witness anchor — A5's motivating problem is real, not rhetorical.
- **The aggregate-head marker exists and fires.**
  `libs/engine/src/engine/declaration.py:359-386` (status ladder, "honesty
  caveat, SPEC §9.5" in the docstring);
  `apps/loops/src/loops/commands/fetch.py:449-459` and `:601-609` attach an
  `ontology_notice` to the output dict whenever a cursor is set and status
  != `"store"`. A9's claimed cover is shipped machinery, not vapor.
- **Ticks carry `fact_cursor`/`window_start`** (live schema of
  `project.db`) — so A1's "tick markers on a facts-ordinal feed" has a
  durable facts-axis placement for chained-era ticks; it is not arrival-order
  fiction.
- **Ceremony shared effective-ts is real and rewound-reader-motivated**:
  `libs/engine/src/engine/sqlite_store.py:704-723` ("a historical `as_of`
  cursor could land *between* the rows of one edit … transaction atomicity
  protects live readers, not rewound ones").
- **Merge inserts source facts `ORDER BY ts, id`**
  (`libs/store/src/store/merge.py:98-102`) — source witness order is not
  preserved; A4's "slice/merge/rebirth today do not preserve source witness
  order" is confirmed, and this matters for A2 (below).
- **Rebirth mints a FRESH lineage** (`libs/store/src/store/rebirth.py:446`:
  "rebirth reconstructs a FRESH lineage") — I probed A4/A10 for the hole
  "stale pre-rebirth handles resolve in the current incarnation because
  lineage survived rebirth"; it is closed: A10's lineage-qualified handle
  check will reject them. Confirmed the hole does NOT exist.
- **S5 suite: 9 tests collected** (`pytest --collect-only` on
  `libs/engine/tests/test_ontology_as_of.py`), including
  `test_same_ts_edit_is_in_force_at_its_own_ts` and the head-equivalence
  set — A8's dual-selector claim ("shipped tests keep their meaning") is
  coherent: those tests live entirely on the `as_of` path the design keeps.

## Question 1 — A5's labeled fallback vs §9.3's "explicitly requested"

**Re-derivation, not deference.** §9.3 (SPEC.md:1110-1120) governs the two
cursors *facts-as-of* and *ontology-as-of*: equal is the mandated default;
unequal "MUST be explicitly requested, never a silent default." A5's
fallback projection applies `ts <= T` to facts AND ontology — **equal
cursors on the event-time axis**. So A5 does not literally trip §9.3's
unequal-cursor MUST. The lens question as posed conflates two layers: A5's
sin is not cursor inequality, it is **mode routing** — a cursor-form address
(`--at`, defined by A11 as *the* witness-cursor semantic) silently selecting
the other semantic when the data lacks an anchor.

Where that routing actually collides is with the design's **own ratified
core**, s1-arbitration.md:47-49: the ts-cutoff read "survives as an
*explicitly requested* analytical projection … **never the cursor
default**." A5 then makes the projection the automatic answer on the cursor
route under a data-dependent condition. Disclosure-after-the-fact is
charter-compliant on *silence* (the read never silently lies — it is
labeled) but it is **not** the same act as explicit request: a request
precedes the read and lives in the command; a label follows the read and
lives in output that scripts, pipes, and downstream agents routinely drop.
Two concrete failure modes:

1. **Mode instability.** A5's own optional follow-up (non-attesting anchor
   backfill for legacy ticks) means the same `--at 2026-05-01` that answers
   in projection-mode today answers in witness-mode after backfill — same
   command, same store lineage, different semantics and different state.
   That is the same-handle-different-meaning hazard A10 exists to prevent,
   reintroduced at the address tier.
2. **A5 contradicts A11 inside the same amendment package.** A11's whole
   argument is "flags carry SEMANTICS, not routes" — one flag, one meaning.
   A5 gives `--at` two meanings selected by store content.

**The fix is nearly free, because A11 already built it.** A11 puts `--as-of`
(labeled event-time projection) on the fold route. So the codex F5 dilemma
("bare ISO time must not simply error across the principal historical
corpus") dissolves without auto-routing: an unanchored wall-clock `--at`
**refuses with teaching** — "no witness anchor for this era (first tick
2026-06-12) — rerun with `--as-of 2026-05-01` for the labeled event-time
projection." One retype; the user's next command IS the explicit request;
`--at` keeps one semantic; future backfill changes what `--at` *accepts*
but never silently changes what an answering command *meant*. Note the
codex F5 amendment itself offered option (b) as an **explicit**
`event-time:` address form — A5 as written *weakened* its own source
amendment from explicit-form to auto-route-with-label. Either the teaching
refusal or an explicit `--at event-time:T` spelling restores it.

**Finding (AMEND, highest priority): A5-EXPLICIT-PROJECTION.**

## Question 2 — A9's current-membership aggregate read vs SPEC §9.5

SPEC.md:1181-1186: aggregation vertices' constitution history "requires them
to own at least an internal table, else a historical read of an aggregate is
dishonest about *which stores constituted the view at T* — the same lie as
§9.1 at the membership tier."

Structural analysis: membership cursor = head, member fact cursors = T is
**unequal cursors at the membership tier** — exactly the shape §9.3 forbids
as a default, and §9.5 explicitly extends the tier ("the same lie … at the
membership tier"). The marker makes it *disclosed*, not *requested*: a
labeled default is a non-silent default, but it is still a default.

However — and this is where I part from a naive BLOCKED — the derogation is
**already shipped and disclosed**: 0.7.0's `--as-of` aggregate reads do
precisely this, with the `aggregate-head` `ontology_notice`
(declaration.py:359-386, fetch.py:449/601, both verified). The SPEC's own
honesty pattern for capabilities the substrate lacks is *degrade honestly,
report, never fake* (§8.6: "legacy eras are reported as unverifiable, never
counted as verified"). A9 extends an existing disclosed derogation to new
address forms rather than minting a new lie, and the alternative (refuse all
historical aggregate reads) would regress shipped, working, disclosed
behavior. The marker covers it — **conditionally**. Three conditions are
currently missing from the fact of the design:

1. **Name it as a derogation with a sunset.** The ratified text should say
   explicitly: this is a §9.3-shaped unequal-cursor default at the
   membership tier, tolerated because equal membership-cursors are
   *impossible* without aggregate internal tables, sunset when §9.5
   aggregate constitution history ships. "Future work, disclosed not faked"
   gestures at this; the derogation framing makes it a tracked debt instead
   of an accepted norm. (AMEND: **A9-DEROGATION-SUNSET**.)
2. **The marker must be unlosable.** `ontology_notice` is a dict field; the
   session-3 TUI and any JSON consumer must be REQUIRED to carry it —
   dropping it in rendering converts a disclosed derogation into the exact
   silent lie §9.5 names. This must be first-class scope, ideally a ratchet
   test. (Folded into A9-DEROGATION-SUNSET.)
3. **Mixed-mode member resolution is a new, worse problem A9 creates.**
   Per-member A5 fallback means one aggregate answer can combine
   witness-anchored members with ts-projected members. The combined fold is
   then computed over incommensurable snapshots — it answers *no* well-posed
   question: not "what a reader at P could see" anywhere, not "retrospective
   at T" uniformly. Per-member disclosure labels the ingredients but the
   *combined state* is still a chimera presented as one answer. Default
   should refuse mixed modes with teaching ("members X,Y have no witness
   anchor at T — use `--as-of T` for a uniform event-time projection across
   all members," which IS well-posed and matches shipped behavior). (AMEND:
   **A9-MIXED-MODE-REFUSAL**. Note: adopting A5-EXPLICIT-PROJECTION makes
   this nearly automatic, since the per-member fallback disappears.)

## Question 3 — Is A1's GlobalReceiptPosition deferral honest about Watch?

Yes, with one small disclosure gap. Re-derived:

- §10 is headed **PROVISIONAL** (SPEC.md:1189) and its vectors are "to
  build" (§10.5) — deferring GlobalReceiptPosition violates no shipped
  normative clause, and A1 correctly sequences it as *prerequisite to §10
  dump* rather than pretending §10.1's total interleaved stream is
  producible from two rowid domains (it is not — schema verified).
- Watch's tick markers have an honest placement that needs no global
  ordinal: chained ticks carry `fact_cursor` (schema verified), a durable
  facts-axis anchor. Placement-by-cursor is deterministic and never claims
  cross-table *arrival* order; A1's "cross-table arrival order between
  refreshes is per-table, disclosed as such" is the correct honest shape.
- A4's companion downgrade (rebuild durability = §10-gated goal) is honest
  and verified: merge does not preserve source witness order
  (merge.py:98-102), rebirth re-lineages (rebirth.py:446), so within-store
  id→rowid durability is the only claim the substrate supports today, and
  that is all A4 claims.

**Gap (minor):** legacy ticks have NULL `fact_cursor` (211 of 216 in the
archived store; zero in the current project store). On any legacy-era
surface, Watch/Rewind marker placement can only be ts-based — event-time
placement inside a witness-order feed. Residue item 2 covers wall-clock
*snapping* through legacy ticks but not marker *placement*; the era-honesty
pattern (§8.5: rendered honestly as legacy, never retro-anchored) should be
extended explicitly to the marker tier: legacy markers render as
"ts-placed, no witness anchor," visually distinct from cursor-anchored
markers. (AMEND, small: **LEGACY-MARKER-ERA-DISCLOSURE**.)

## Sweep of the remaining amendments against the charter

- **Core design (witness-prefix selection, `(ts,id)` replay of the selected
  set, ontology from the same prefix):** compliant with §6.2 (replay order
  untouched), §8.4 (membership = witness authority; "a late-arriving fact
  … must not retroactively enter a sealed window" — the design generalizes
  exactly this to read positions), and it makes §9.3's equal-cursor default
  *concrete* (one position P for both cursors). This is a strengthening of
  the charter, not a strain on it. Tried to break it with merge: a cursor
  handle on target A survives merge(A←B) because A's rowids are stable and
  B's rows append — the old prefix stays a prefix; B-native handles are
  rejected by A10's lineage qualification. Failed to break it.
- **A2 (receipt groups):** the *invariant* is right — mid-ceremony
  positions are the §9.1 lie and must be unreachable. But the
  implementation note (residue 8) detects groups by "contiguous in witness
  order and share effective ts," which is a **heuristic, not a durable
  identifier** — codex F2 explicitly proposed storing a group id/end
  ordinal, and A2 adopted the *framing* while quietly keeping the
  heuristic. Concrete break path: same-lineage replica merge re-inserts
  self-lineage ceremony rows via `ORDER BY ts, id` (merge.py:98-102); any
  fact carrying the identical ts (float collision — improbable, not
  impossible, and backdated/imported facts use payload-supplied ts) can
  interleave inside the span, defeating span detection and making a
  mid-ceremony position reachable again. An honesty invariant enforced by
  an improbability is a ratchet-test failure waiting to happen. Store a
  durable group boundary (group id in the `_decl` payload, or
  first/last-member ids in a ceremony receipt row). (AMEND:
  **A2-DURABLE-GROUP-ID**.)
- **A11 (flags carry semantics):** lifting the 184dfce refusal into two
  labeled modes is *better* than the refusal — the refusal existed because
  fold silently dropped temporal flags; two explicit modes with the answer
  naming its mode preserves the never-silently-lie charter on every route.
  One hardening: "output always names the mode that answered" must bind to
  **structured output** (a mode field in JSON), not only rendered text —
  otherwise piped consumers get modeless answers and the label was
  decorative. (AMEND, small: **A11-MACHINE-MODE-MARKER**.)
- **A13 (pre-genesis → genesis floor + Unhistorized):** verified the
  marker ships (declaration.py:357, fetch.py "unhistorized" notice). The
  look-ahead technically violates the "ontology from the same prefix"
  slogan, but it is the *shipped* honest resolution: an explicitly labeled
  earliest-known floor is not a retro-claim (the retro-claim would be
  rendering under the current file silently). Compliant; the design should
  keep codex F13's demand that the genesis fact id's inclusive/exclusive
  boundary lands in vectors.
- **A3 (id-era rules):** primary-key-lookup-only resolution honors §8.4's
  witness/id split and 3b2ceb5's lesson (id order ≠ append order in mixed
  eras). Compliant.
- **A6 (discrete scrubber):** renouncing date interpolation for fact
  positions is the never-fabricate rule applied to rendering — it honestly
  contradicts the Rewind mock's continuous ruler, and the design says so.
  Compliant.
- **A7 (Watch control events):** visible `_decl` control events are the
  observability-of-observation principle at the feed tier; full
  reconstruction as CONTRACT with incremental as optimization keeps §6.2
  replay honest under backdated arrivals. Compliant.
- **A12 (unsealed tail):** era-honesty pattern at the cursor tier,
  consistent with §8.5's three-era reporting. Compliant.
- **A1 name-collision residue** (never reuse `fact_cursor` for the read
  cursor): correct; §8.2's field keeps its meaning. Compliant.

## Verdict

**AMEND.** I actively tried to break the axis — merge prefix stability,
rebirth handle staleness, pre-genesis retro-claim, §9.3 equal-cursor
compliance of the core — and failed every time; the selection/replay/address
stack is paradigm-honest and genuinely strengthens §9.3 by making its
default concrete. What does not survive unmodified is the v2 package's two
convenience-over-explicitness moves (A5 auto-routing, A9 mixed-mode
combination) and one honesty invariant left resting on a heuristic (A2).
Named amendments, in priority order:

1. **A5-EXPLICIT-PROJECTION** — unanchored wall-clock `--at` refuses with
   teaching that routes to `--as-of` (or an explicit `event-time:` address
   form, per codex F5's original option b). Auto-route-with-label breaches
   the design's own ratified "never the cursor default," contradicts A11's
   one-flag-one-semantic, and is unstable under A5's own future anchor
   backfill.
2. **A9-MIXED-MODE-REFUSAL** — never combine witness-anchored and
   ts-projected members into one aggregate answer by default; refuse with
   teaching toward a uniform `--as-of` projection. (Falls out of amendment
   1 almost automatically.)
3. **A9-DEROGATION-SUNSET** — name current-membership-over-past-facts as a
   §9.3-shaped derogation at the membership tier (SPEC.md:1181-1186) with
   an explicit sunset (aggregate internal tables), and make carrying
   `ontology_notice` a hard rendering requirement (ratchet-testable) so the
   disclosure cannot be dropped by a renderer.
4. **A2-DURABLE-GROUP-ID** — store a durable ceremony-group boundary; span
   detection by contiguity+shared-ts is a heuristic that same-lineage
   replica merge (+ ts collision) can defeat, making the mid-ceremony lie
   reachable again.
5. **A11-MACHINE-MODE-MARKER** — the answering mode must appear in
   structured output, not only rendered text.
6. **LEGACY-MARKER-ERA-DISCLOSURE** (minor) — Watch/Rewind markers for
   NULL-`fact_cursor` legacy ticks render as ts-placed/unanchored,
   extending residue 2 from address snapping to marker placement.
