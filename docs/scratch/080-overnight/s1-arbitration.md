# Session 1 arbitration — the temporal cursor axis

*2026-07-17, overnight run. Arbiter: loops-claude. Status: DRAFT pending two
adversarial passes (codex skeptic tonight, Claude skeptic panel post-reset).
Evidence: dossier-spec-cursor.md, dossier-s5-impl.md, codex high-effort
advisor answer (/tmp/codex-cursor-axis-answer.txt, to be preserved into this
dir), first-hand SPEC reads (§6.2, §8.4, §9.3–9.5, §10.1–10.5),
declaration.py docstring, Rewind mock line 91.*

## The reframe (dissolves the three-way conflict)

The entry framing — "three authorities in live conflict" — is wrong, and
both the spec-cursor reader and the codex advisor independently converged on
why. The three are **roles in one stack**, not competing answers:

- **Selection** (which rows participate): witness order — §8.4's membership
  authority.
- **Replay** (how the selected set derives state): `(ts, id)` — §6.2,
  normative, unchanged, always.
- **Address** (how a user names a position): many forms — tick, seq,
  fact id, wall-clock — all resolving to one selection position. Ticks are
  chain-verified *names for* witness positions (`fact_cursor`), not a third
  axis.

Two prompt-corrections from the evidence, worth recording because the wave
thread carried them wrong:

1. §9.4's "undefined within windows" is about the rejected third-table
   residence lacking shared witness order — not a claim about ts cursors.
2. §9.3 never specifies the cursor axis at all. This is a **spec gap**, not
   a conflict. Session 1's output closes it.

## The design (proposed for ratification)

**A cursor denotes the inclusive witness prefix of rows this store had
received at a position. Cursor identity is a fact id (or the empty/genesis
sentinel). The selected prefix — domain facts and self-lineage `_decl.*`
rows alike — is then replayed in `(ts, id)` order; ontology resolves from
the `_decl` rows in the same prefix (equal cursors = same position P for
both, making §9.3's default concrete and coherent).**

Key consequences:

- **fold-as-of** selects by witness prefix, NOT by `ts <= T`. Late arrivals
  (merge/import/backdate) do not rewrite what a position shows: "what a
  reader at P could have seen" is receipt-honest per §9.3. The ts-cutoff
  read survives as an *explicitly requested* analytical projection
  ("event-time/retrospective"), never the cursor default.
- **Address forms**, all resolving to a witness position:
  - `head` — newest fact id, captured atomically, frozen once returned
    (write-receipt discipline: no moving token).
  - `fact:01J…` — the durable canonical handle.
  - `seq:N` — Nth receipt ordinal (display-level, per-store, derived;
    includes `_decl` rows in the count).
  - `tick:01J…` — resolve via the tick's `fact_cursor`; report chain-verify
    status with the resolution.
  - wall-clock — **snap to tick floor** (last tick at-or-before the mark),
    reported explicitly. No tick ⇒ "no witness-time anchor", never a silent
    ts approximation. Rationale: facts carry no receipt timestamp; only
    ticks bind wall-clock to witness position, and their timestamps are
    signed claims. (This is exactly what the Rewind mock's "(last tick
    before the mark)" was already saying — the mock read the protocol right.)
- **--diff(P1, P2)**: full independent reconstruction at both endpoints,
  structural diff. Never incremental application of the interval — a
  backdated arrival inserts early in `(ts,id)` replay and can change
  order-sensitive downstream state. Output notes late arrivals and
  declaration changes in the interval.
- **Rewind** scrubs fact positions; tick markers decorate (and are the only
  wall-clock-addressable anchors). **Watch** tails receipts in witness order
  (`seq N`); `_decl` arrivals advance the cursor and can change
  interpretation; a tick arrival renders an anchor without advancing fold
  position. Same axis, both surfaces.
- **Merge**: cursor handles bind to store lineage. Head fold state is
  merge-stable (same fact set + ontology ⇒ same state, §6.2); historical
  trajectories are legitimately per-store (§0.5.4: attestation is a
  function of receipt order by design). merge(A,B) and merge(B,A) converge
  at head, diverge in history — honestly.
- **Rebuild**: fact-id cursors survive `rebuild(dump(S))` because §10.1
  carries witness order explicitly per line; raw rowids do not survive and
  are never exposed as handles.

## CLI surface (proposal — session 3 refines rendering)

New flag on the **fold route**: `--at <address>` taking the full address
grammar. `--as-of` remains an event-time filter on the facts/ticks routes
and stays refused on the fold route — but the refusal message now teaches
`--at`. Rationale: one flag name carrying two semantics across routes
(event-time filter vs witness cursor) is the exact incoherence the
read-router refusal (184dfce) exists to prevent. Explicit over implicit:
two semantics, two names.

`--diff <addr1>..<addr2>` (or `--at A --diff-against B`; bikeshed at
implementation) on the fold route.

## Residue & amendments (honest edges, not failures)

1. **Name collision**: `fact_cursor` is a §8.2 tick-envelope field. The new
   concept is a *witness position*. Code should say `WitnessPosition` /
   `at`; never reuse `fact_cursor` for the read-path cursor. (spec-cursor
   reader's catch.)
2. **Legacy/pre-chain ticks**: wall-clock snap resolves through a tick's
   recorded cursor. Whether all 211-legacy-era ticks carry usable window
   bounds is an implementation-time empirical check; where absent, degrade
   honestly per the verify-era pattern ("no witness anchor for this era").
3. **§10 interleaving under-specification** (codex finding, new): facts and
   ticks occupy separate rowid domains; §10.1 promises one globally
   witness-ordered stream. Not a 0.8.0 blocker (cursor identity is a fact
   id; ticks are anchors), but it feeds thread:loops-go-conformance-oracle —
   before §10 vectors are generated, either add a global receipt ordinal or
   narrow the §10.1 promise.
4. **S5 migration**: `load_declaration` gains witness-position selection;
   the shipped ts cutoff remains as the explicit event-time projection. Its
   same-ts "edit wins its own instant" tie-break governs only that explicit
   ts mode; under witness selection the question dissolves (inclusion is by
   prefix membership, interpretation is one ontology per read — projection,
   not delta composition, per design/internal-table-meta-schema).
5. **vertex_tick_fold anchoring**: currently interprets snapshots under
   `as_of = tick.ts` (event-time). Coherence improvement available: anchor
   at the tick's own witness position instead. Differs only when a
   backdated `_decl` row arrived post-seal. Migration note, not urgent.
6. **Conformance**: no existing Go vector assumes any as-of axis (verified
   with cites: vectors_test.go:26,62; sqlite.go:23; merge_test.go:31).
   Green conformance is silent on this decision — the §8.7 two-authorities
   fixture and cursor-selection vectors are still owed. The thread's
   "S5 incumbent-provisional" marking resolves: provisional-status
   CONFIRMED and now superseded at the cursor layer by this design.
7. **Per-fact receipt time does not exist.** This is why wall-clock
   addressing snaps to ticks. If finer wall-clock resolution is ever
   wanted, that is a new column/era decision (protocol-level, era-opening
   rules §8.5) — out of 0.8.0 scope.
8. **Mid-ceremony positions are illegal (amendment, store-context reader's
   catch).** Edit ceremonies write multiple `_decl` rows with one shared
   effective ts precisely so equal-cursor rewind cannot observe a partial
   ontology (hardening outcome, review 01KXE4BQK6). ts-selection got
   ceremony atomicity for free (shared ts ⇒ all-or-nothing at any cutoff);
   witness-prefix selection does NOT — a cursor can land between two rows
   of one ceremony. Resolution rule: cursor resolution snaps OUT of a
   ceremony's row-span (to the position just before its first row, or just
   after its last — direction per address form: floor-forms snap before,
   head snaps after a completed ceremony only). Implementation: ceremony
   rows are contiguous in witness order and share effective ts; the
   resolver detects span membership and adjusts. `--at fact:ID` naming a
   mid-ceremony row is an error with a teaching message, not a silent snap.

## Arbitration v2 — post-cross-exam amendment package (2026-07-17 ~00:45)

The codex high-effort cross-exam (s1-codex-crossexam.md) confirms the axis
("selection/replay distinction is sound") and breaks five product claims.
Arbiter's judgment per finding — each FATAL resolves to an amendment, none
overturns the axis; the amended contract below supersedes the naive claims
above where they conflict.

- **A1 (from F1) — the cursor is a FACTS-ONLY witness position in 0.8.0.**
  Facts and ticks occupy separate rowid domains with no durable cross-table
  interleaving. The fold boundary needs only the facts axis (skeptic
  concedes this). Watch renders a facts-ordinal feed with tick markers;
  cross-table arrival order between refreshes is per-table, disclosed as
  such. **GlobalReceiptPosition** (durable store-wide receipt ordinal
  covering facts+ticks) is queued as a PROTOCOL amendment, oracle-
  coordinated, prerequisite to §10 dump implementation — grow-the-substrate,
  sequenced, not smuggled into 0.8.0.
- **A2 (from F2, pre-caught) — receipt-group atomicity.** Ceremony rows are
  an atomic receipt group (shared effective ts, contiguous append); cursor
  resolution snaps out of a group's span; `--at fact:ID` naming a mid-group
  row errors with teaching. Adopt the skeptic's "receipt group" framing.
- **A3 — id-era rules.** Handles resolve by primary-key lookup only; no
  code path ever orders or parses ids for cursor purposes (mixed uuid4/ULID
  eras). `seq:N` is rowid-ordinal, per-store, display-tier.
- **A4 (from F4) — rebuild durability is a §10-GATED GOAL, not a shipped
  claim.** Within-store durability (id→rowid) holds now; cross-rebuild
  durability ships with §10 dump/rebuild + vectors, which do not exist.
  slice/merge/rebirth today do not preserve source witness order — noted in
  the fact, no longer implied otherwise.
- **A5 (from F5, decisive UX evidence) — wall-clock addressing gets an
  honest two-step: tick-floor where anchors exist, else the LABELED
  event-time projection (`ts <= T`) with explicit disclosure** ("no witness
  anchor for this era — event-time projection"). Never a silent error
  across the pre-June corpus, never a silent semantic swap. The projection
  already exists in this design as the explicit analytical mode; A5 merely
  routes unanchored wall-clock addresses to it WITH the label. Optional
  follow-up (not 0.8.0): non-attesting anchor backfill for legacy ticks —
  must not retro-claim attestation (§8.5).
- **A6 — discrete scrubber contract.** Primary scale = receipt ordinal,
  explicitly discrete; ticks are the only dated markers; no date
  interpolation for fact positions, ever.
- **A7 — Watch control events + replay budget.** Hidden `_decl` receipts
  render as visible control events ("seq N · ontology changed"); display
  carries both receipt seq and visible count; refresh recomputes per
  coalesced receipt group (full reconstruction is the CONTRACT; insertion-
  aware replay is an optimization, never a semantic). No O(1) apply promise.
- **A8 (from F8) — dual selector API.** `load_declaration(as_of=float)`
  unchanged (event-time projection, shipped tests keep their meaning);
  new `at=WitnessPosition` selector, mutually exclusive. vertex_tick_fold
  migration carries the tick envelope (fact_cursor) through the drill API;
  legacy ticks fall back to ts-mode with an "unanchored interpretation"
  notice. Real work, scoped in implementation plan.
- **A9 (from F9) — aggregate cursors are per-member VECTORS.** Wall-clock
  and tick addresses resolve per-member (tick-floor vector; partial
  anchors disclosed per member, A5 fallback per member). `seq:`/`fact:`
  forms are REFUSED on aggregates (member-scoped handles; error teaches
  addressing the member). Membership-as-of uses CURRENT membership with
  the existing 'aggregate-head' honesty marker (aggregates lack internal
  tables today; SPEC §9.5 aggregate-constitution history is future work,
  disclosed not faked).
- **A10 — lineage-qualified handles.** Serialized cursor handles carry the
  store lineage id; resolution against a store with different lineage
  errors with teaching. Same handle must never silently mean a different
  prefix.
- **A11 (from F11, skeptic's steelman ACCEPTED over my route-split) —
  flags carry SEMANTICS, not routes.** `--at` = witness cursor; `--as-of`
  = event-time projection; both valid on the fold route (the 184dfce
  refusal lifts into two explicit labeled modes — which A5 needs anyway);
  each route refuses only forms that are meaningless for it, and output
  always names the mode that answered.
- **A12 — unsealed-tail disclosure.** Positions beyond the last sealed
  window render as tail/unverified vs chain-anchored — the era-honesty
  pattern at the cursor tier.
- **A13 — pre-genesis positions reuse the shipped honesty ladder.**
  Witness positions before the genesis row resolve ontology to the genesis
  floor with the existing Unhistorized marker.

Findings 14/15 SURVIVE unchanged. Verdict: axis ratifiable WITH this
package; implementation plan must carry A1–A13 as first-class scope.

## What would change my mind (for the skeptic passes)

- A concrete UX walk where tick-floor snapping makes `--at <time>` useless
  in practice (sparse-tick stores) AND users genuinely need wall-clock
  positions between ticks — would force either a ts-approximation mode
  (labeled) or per-fact receipt time (protocol change).
- Evidence that witness-prefix ontology resolution breaks a shipped S5
  test/behavior consumers depend on.
- A Watch/TUI requirement that needs cross-store (aggregate) cursors —
  witness positions are per-store; aggregates would need per-member cursor
  vectors (defer: aggregation reads at head remain fine).
