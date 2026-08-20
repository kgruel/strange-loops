The Arrival Substrate

strange-loops · architecture proposal · ratified 2026-08-17

# The Arrival Substrate

 Loops is rebuilding its store around a single canonical artifact: an append-only,
 per-custodian arrival log. Everything else — the sqlite index, full-text
 search, fold state, and the shared file people actually read — becomes a declared,
 rebuildable projection of it. This document lays out the model, the five laws
 that freeze it, the empirical evidence that the current design fails in ways the new one
 cannot express, and the shipping plan: a 1.0.0 contract break, a one-time migration
 sidecar, and a CLI rebuilt from scratch over the SDK.

 Converged over five cross-family review passes, 2026-08-16 → 17 ·
 Kyle Gruel with Claude Opus 5, Claude Fable 5, and GPT 5.6 “Sol” ·
 grounded by a 22-agent code audit, an 81-row consumer census, and the first live merge experiment

Contents

Loops, for the cold reader

Where this came from

The collapse

The five laws

Ordering, generalized

The custody boundary

The empirical evidence

Sharing over git

Shipping: 1.0, sidecar, new CLI

What this costs

What remains open

## 1Loops, for the cold reader

 Loops is a design-memory substrate. People and agents emit facts —
 decisions, open threads, observations, frictions — into a vertex, which is
 a named store plus a fold schema. Facts are immutable and append-only; a fold
 maintains a compressed current view (latest decision per topic, current status per thread), so a
 session reads the fold to orient and emits as it works. Correction is re-emission, never editing;
 the history is the point.

 Around that core sit the evidentiary mechanics: every fact is attributed to a signing
 observer; a tick is a sealed checkpoint — a signed,
 hash-chained record that commits to the exact window of facts it closed over. Stores can be
 shared between people and machines, and reads can be addressed at a
 witness position: “answer as of what this store had received at
 point P,” not just “answer now.”

 That last idea — that when a store received something is first-class,
 inspectable history — is what this whole proposal is about getting structurally right.

## 2Where this came from

A performance fix pulled a thread, and the thread was load-bearing.

 PR #8 made fold replay follow receipt order — the order this store
 received facts — instead of event-timestamp order, collapsing an O(n²) ingest into a
 linear one (a fold over a prefix-stable order can resume from a checkpoint; a fold over
 timestamp order must replay whenever a backdated fact lands in the middle). That fix worked, but
 it raised the real question: what is receipt order, authoritatively?

 Today the answer is embarrassing when said out loud. The canonical artifact is a JSONL file
 — intended to be tracked and shared through Git, though that tracking was never actually
 realized — the sqlite database beside it is a derived index; and custody order is
 implicit in line order, materialized as sqlite’s rowid. The
 audit that closed this arc found the latent defect that implies: the tick chain’s
 cryptographic commitments — window hashes, cursors — are computed over
 rowid ranges, and a routine index rebuild regenerates that axis. Custody
 commitments rest on an axis a maintenance operation reassigns. Worse, the canonical file is the
 one git is invited to merge — and a textual merge of a custody log rewrites the custody.

 Two intermediate designs were tried and dissolved on review (a two-mode
 “receipt store vs. event store” scheme, then an arrival-record sidecar
 bolted to it). Each round of cross-family review — two Claude models and a GPT model
 deliberately kept independent, with a 22-agent repo audit between passes — removed a mode
 or a special case, until one artifact remained.

## 3The collapse

The store is what this custodian received. Everything else is a question asked of it.

 The canonical store becomes an append-only, lineage-local arrival log. It holds
 complete canonical records plus a minted lineage genesis — the
 custodian’s own identity marker. Its position is the witness position:
 (arrival_lineage, ordinal). It is never merged, never rebuilt, never rewound.

 Everything else is a projection of an arrival prefix: the sqlite index,
 full-text search, fold state, graph views, checkpoints — and, crucially, the
 JSONL file itself — today’s authoritative artifact, intended to be tracked
 and shared through Git though that tracking was never actually realized — which becomes a deterministic, canonically-ordered
 synchronization projection. Authority inverts: the file people diff, review, and share stops
 being the store and becomes a derived representation of it.

 [figure omitted]

 The authority inversion. Today git merges write into the canonical artifact, and
 custody order is whatever line order results. Under arrival, exactly one artifact is
 canonical and git only ever touches a derived projection; the single write path into custody
 is the custodian’s own admission step.

### Three clocks, three authorities

 The model keeps a strict ontology of time, and it survived every pass unchanged. Each temporal
 datum has exactly one authority, and no datum ever substitutes for another:

 | Clock | Field | Authority | What it means

 | Claim | fact.ts | Claimant | “This is when I say the thing happened.” Observer-asserted event time. Data, never substrate.

 | Emission | fact.id | Emitter | Identity and dedup (a ULID). Totalizes orderings deterministically; carries no time authority.

 | Witness | (lineage, ordinal) | Custodian | “This is when I received it, relative to everything else I received.” Order, not wall-clock.

 Wall-clock at the custody layer exists in exactly one place: a seal. A tick
 binds its own signed timestamp to a witness position, so “this store had received X by
 time T” is an attested claim with a chain behind it — not a bare field
 anyone could have written. (Section 7 covers why the model deliberately adds no per-record
 receipt timestamp.)

## 4The five laws

 The smallest attackable surface. Everything else in the record is derivable from these;
 break one and you break the architecture.

Law 1

The store is the arrival log. Projections compute answers; arrival determines what those answers are about.

FORBIDS — any local semantic or integrity claim resting on an artifact other than arrival. Reads may execute through sqlite, FTS, or a checkpoint — that is what they are for. If a projection disagrees with arrival, the projection is stale or invalid, never the other way around.

Law 2

Ordering over an arrival basis is witness order or a declared (thing, id) order. id totalizes and carries no domain-time authority.

FORBIDS — the substrate learning what ts, fiction_time, or priority mean; and id being read as a clock. The second prohibition matters more after the generalization, because most declared keys are not time at all.

Law 3

Drivers propose candidates; only the custodian admits records and mints witness positions.

FORBIDS — two things minting positions. A driver that can append to arrival is a second custodian, and the single-custodian invariant is the one property arrival exists to hold. The inbound interface is deliberately weak: it returns candidates, it does not write.

Law 4

Witness positions compare only within one arrival lineage.

FORBIDS — cross-lineage comparison answering at all. It is not false, it is undefined, and it must fail structurally rather than return a confident wrong answer. Copying arrival bytes for backup or replication is legal and recommended; the typed error is opening a copied arrival log as another custodian while silently claiming continuation of the lineage. Restore is an explicit lineage act, never a silent one.

Law 5

Projection maintenance is derived from ordering semantics and reduction algebra. It is never an independent store mode.

FORBIDS — a freely-declared maintenance class. A reduction wrongly marked order-independent produces silently wrong fold state — the only silent failure shape this architecture permits, so the claim is checked, not trusted (§5).

 The laws were frozen with a standing reopening bar, so future review needs
 evidence rather than aesthetics:

Falsification criterion

 Show a required Loops operation that cannot be expressed as custody in one lineage
 plus declared interpretation/projection over an arrival basis, without introducing
 false historical claims. Five review passes produced none.

## 5Ordering, generalized

“Event order” was only ever (ts, id) — and ts is just the first key anyone thought of.

 The old design treated timestamp order as a special mode of the store. The generalization that
 finished the collapse: fiction_time, effective_date,
 priority, (chapter, scene) are all peers of ts. So
 “event” leaves the vocabulary entirely and the substrate exposes one read
 primitive:

ordered(prefix = W, key = K)
 = stable total ordering of arrival[0:W] by (K(record), record.id)

 A projection declares order arrival or order by KEY. The substrate
 never learns what any key means — domain vocabulary stays in declarations —
 and id serves only as the deterministic tiebreak.

 [figure omitted]

 One prefix, two declared orders. Record 6 arrived late but belongs early in fiction
 time. The arrival-order fold never re-opens folded state; the fiction-time projection pays a
 bounded replay from the insertion point. Which cost a projection pays is derived,
 never chosen.

### Maintenance is derived, never declared

 A projection has two declared inputs and one derived property:

 | Ordering (declared) | Reduction (semantics) | Maintenance (derived)

 | arrival | any, within the fold contract | prefix-stable — resume from head

 | (K, id) | order-independent | insertion-independent — incorporate directly

 | (K, id) | order-sensitive | insertion-sensitive — checkpoint + replay

 Worked instances, and note the shape they make: FTS and the shared JSONL land in
 different maintenance classes though both are non-fold projections; the fiction fold
 and the shared JSONL land in the same class though one is a fold and one is a file.
 Maintenance is a property of the (ordering, reduction) pair, never of the artifact.

 | Projection | Order | Maintenance

 | receipt-order fold | arrival | prefix-stable

 | latest-by-event-time | (ts, id) | insertion-independent (max needs no replay)

 | fiction chronology fold | (fiction_time, id) | insertion-sensitive

 | full-text search | none meaningful | insertion-independent

 | canonically ordered shared JSONL | (id) | insertion-sensitive

 Why derivation is a law and not a style preference: a reduction wrongly asserted
 order-independent yields silently wrong fold state — no error, no refusal.
 Every other wrong answer in this architecture is engineered to fail structurally, so this one
 claim gets a ratchet: where a user asserts order-independence, the test suite
 runs the reduction over shuffled visitation orders of one record set and requires identical
 results. A claim that can be falsified automatically must be.

## 6The custody boundary

Admission records observation, not semantic eligibility.

 If arrival is permanent, irrecoverable evidence, the question “what may enter it?”
 is the architecture’s most consequential boundary. The ruling separates two questions
 that older designs fused:

custody: did this custodian receive a legitimate assertion?
interpretation: should this assertion participate in this answer?

The admission table answers only the first, and it is complete:

 | Verdict | Case | Why terminal

 | reject | malformed bytes | re-obtaining changes nothing

 | reject | invalid signature | re-obtaining changes nothing

 | reject | id collision, different bytes | identity corruption; detectable via signatures

 | reject | source not authorized for intake | source still holds the records if policy changes

 | admit | everything else | — it arrived; that is a fact about this custodian

 Admit does not mean believe. It means only: this custodian received this
 legitimate assertion, at this position. Everything about semantic usefulness — trust,
 curation, horizons, relevance — happens above admission, in declarations and
 projections. A rejection is safely terminal if and only if the candidate remains
 obtainable from its source — which the default transport guarantees (§8).

 [figure omitted]

 Drivers propose; the custodian admits. The inbound interface is deliberately weak: a
 driver returns candidates and can never mint a position. Signature verification, intake
 authorization, and position minting all sit on the arrival side of the seam.

 Why some projections may participate in exchange and others may not: exchange bindings are
 gated on being record-complete — a projection can carry canonical bytes
 outward only if it preserves complete canonical records, which is why JSONL, Parquet, or a
 full-record sqlite projection can serve as a transport surface while FTS or fold state cannot.
 A lossy projection has already interpreted; letting it speak for the store would smuggle
 interpretation back into custody.

### The threat model this places correctly

 An authorized peer can still assert pathological values — ts = 2099,
 priority = −∞, effective_date = 1900. Under the
 generalization this is not a timestamp problem: every declared key inherits it. A
 pathological K captures latest-style (K, id) projections and forces
 worst-case replay on insertion-sensitive ones. The ownership is deliberate:

Arrival records who asserted it — nothing more.

The projection’s declaration owns eligibility, horizon, and range policy for its own key.

Maintenance machinery pays the replay cost its declared ordering implies — a priced cost, not a surprise.

Signatures make abuse attributable: a hostile assertion is a visible, signed, permanent act by a chosen peer.

 Rejecting such records at the custody boundary would make one projection’s taste into
 everyone’s history filter — which is exactly the fusion of custody and
 interpretation this architecture exists to remove.

## 7The empirical evidence

 The convergence was not taken on argument. The final pass attacked the frozen laws against
 code, censused every temporal consumer in the tree, and ran the experiment three passes of
 design had only reasoned about.

### 7.1 — The merge experiment

 Nobody had ever actually git-merged a JSONL store log. The final pass did, in a sandboxed lab:
 seeded stores through the engine’s own APIs, cloned, diverged, and merged in every shape
 git offers. Findings, with the working tree receipts preserved:

 [figure omitted]

 Receipt order stops being a property of the store and becomes a property of the
 merger. This is the measured, stronger form of the argument for a monotonic transport
 — it replaced the assumed “lines interleave unpredictably” story.

The individual findings, each with verbatim receipts in the lab transcript:

 Rebuild alone is safe — measured. A store that tailed forward, a store
 that rebuilt, and a fresh clone with no index at all produce byte-identical row order and
 identical window hashes from the same log. The invalidator is a rebuild over a log whose
 line order changed; rebuild over an unchanged log is order-isomorphic.

 The silent cursor failure is real. After pulling a union merge, a held
 durable handle resolved without any error to a different witness prefix — two
 foreign facts now inside a position that previously excluded them; seq:5 named a
 different record entirely. Nothing raised. A plausible answer under silently changed
 semantics.

 Chain verification is loud only inside sealed windows. The same merge
 produces three loud breaks when foreign lines land inside a sealed window — and a clean
 ok: true when they land past the last seal, indistinguishable from honest
 unsealed appends. The unsealed tail is exactly where an active store lives.

 The split-brain verify. A byte-length-preserving interior edit merges cleanly
 under git’s default driver. The same commit then yields two different folds and
 two different verify_chain verdicts in two working trees — the tree that
 kept its index certifies a log it no longer matches.

 The duplicate-id brick. Union-merging the same fact id sitting at two
 different tail positions commits a store that no clone can ever open again —
 discovered only after the merge has been committed and distributed. (Simulated through the
 transport seam; today’s wired paths refuse before reaching it.)

Why this evidence closed the argument

 The two worst outcomes — the brick and the split-brain — are states the
 arrival architecture cannot represent. An id-sorted shared projection gives one fact
 one position by construction, and Law 1 makes a projection never a verify basis. The new
 model doesn’t handle these failures better; it makes them inexpressible.

### 7.2 — The last open question, and how it closed

 One custody-schema question survived four passes: should arrival hold a typed
 “deferred” entry for legitimate-but-not-yet-usable candidates, or a per-record
 receipt timestamp? The question sharpened into a falsifier — does
 any real operation require historical wall-clock context at a witness position? —
 and an exhaustive census of the tree answered it:

Exactly one operation in the entire codebase maps wall-clock to a position
 (the CLI’s --at <date> form), and snapping to the last sealed
 checkpoint is its documented contract, not a degraded answer.

Every other consumer of the seal-anchor machinery does identity and ordinal arithmetic
 (“is this position sealed?”, “how many records past the seal?”) —
 duties a timestamp cannot retire.

Evidence-grade dating is already served better by seals — signed and
 chain-committed, with seal density as the precision lever — than any unsigned field
 could serve it.

And the migration argument: arrival times for the legacy corpus are
 unreconstructible, so the field would be born null for all history or fabricated — and
 fabricating historical precision is expressly forbidden (§9).

Resolution — ratified 2026-08-17

 Add neither. Historical reconstruction is intentionally limited to
 witness position + declaration generation + fact contents. The admission table has no
 legitimate-but-inadmissible row for a deferral to hold, and retention obligations for
 windowed transports belong to those drivers, never to arrival. Reopening requires a real
 consumer, by the falsification criterion in §4.

## 8Sharing over git

The projection obeys the same law as what it projects.

 Sharing stores through git is an intended, forcing workflow — per-repo curated vertices
 plus combinatorial vertices over them. The ruling: the shared projection lives on a
 monotonic ref (its own append-only line of history, published on push), not as
 a branch-traveling tracked file. Four arguments, one decisive:

A fact’s survival must not depend on a code-review outcome. An
 observation made on an abandoned branch is more valuable, not less — it is the
 record of a path not taken.

Same law as the source. Arrival is append-only and never rewound; under a
 monotonic ref, so is its published projection. Fast-forward is the superset check; a
 rejected push is the conflict, resolved by re-project-and-push.

Branch-travel loses its own motivating benefit. Facts do not belong to
 branches: a checkout that drops admitted facts is a divergent projection, repaired by
 re-projecting — so every branch’s copy converges to the local union anyway.
 Branch-travel delivers a perpetually churning tracked file, not PR-scoped facts.

Aggregates break under it. A combinatorial vertex over N repos would answer
 differently depending on which branch each clone has checked out. Under a monotonic ref,
 membership only grows.

 The merge experiment’s block-ordering result (§7.1) is the empirical version of the
 same point, and the ff-only shape it validates is precisely this transport. The semantic merge
 driver designed in an earlier pass is deferred, not built — it is what a
 branch-travel driver would need if someone ever configures one, and nothing is prepaid for it.

## 9Shipping: 1.0, sidecar, new CLI

One break, spent on the model actually believed.

 The project’s standing rule is a one-break budget: the persisted store
 contract may break once, loudly. That is semver-major reasoning, so the arrival substrate ships
 as 1.0.0 — no intermediate store contract before it, and the interim
 hazard documented on main (the merge behaviors of §7.1, currently unreachable) ends when it
 lands.

### Migration is a sidecar, not native

 1.0 does not read 0.x stores. A separate, one-time migration sidecar converts
 them. Supporting legacy formats natively-forever would keep two open code paths alive
 indefinitely — the two-mode store re-entering through a compatibility door — so the
 sidecar is the option that completes the dissolution. Three requirements keep it honest:

Sidecar-ness relaxes the maintenance commitment, never the epistemics.
 The migration is fully receipted; it reproduces exact historical receipt order where the
 source contains it, and where it does not, it mints an explicit legacy-adoption genesis
 marker — “historical receipt unavailable before this boundary” —
 rather than inventing precision. Idempotent and resumable are release blockers.

A bridge pinned at both ends. The last 0.x reader and the first 1.0 writer
 ship as frozen, pinned dependencies — runnable years later (uvx) for a user
 arriving from any 0.x. A frozen artifact, never a maintained surface.

Provenance lives in the store, not the tool. The adoption receipt in the
 new arrival log is what makes deleting the tool safe: the store carries its own migration
 evidence after the sidecar is gone.

 [figure omitted]

 One-time, not support-forever. The only permanent residue in 1.0 is a legacy-shape
 detector that refuses and names the sidecar — a location claim, never an
 open-and-read path.

### The CLI is rebuilt from scratch over the SDK

 The current CLI grew up alongside the old authority model. Rather than retrofitting it, 1.0
 ships a new CLI as a thin wrapper over the SDK, with explicit license to drop any current
 concept that doesn’t fit the model. This is safe because the verification pyramid —
 conformance vectors, architecture rules, property suites — lives at engine/SDK level and
 survives; only CLI-level goldens rebuild, against a surface that is honest about the new model.

### Dissolves

store-file suffix as a mode switch (residence)

the byte-prefix custody model in store verify (re-specified over arrival)

merge/receive as sqlite operations — they become admission through drivers

adopt reshapes into the lineage-genesis ceremony

### Carried, or stronger

witness addressing, re-keyed on (lineage, ordinal) — seq:N inverts from today’s most fragile address form to the canonical coordinate

the read grammar, lenses, and zoom discipline

the emit grammar and fold-key model

seals, chain verification, signing — re-based on arrival positions

 Implementation proceeds as four cuts: A authority (arrival becomes
 canonical), B projections (sqlite and the shared JSONL re-derive from it),
 C ordering (declared projection orders, (K, id) keys),
 D surfaces (verification and seals re-specified over arrival).

## 10What this costs

The record keeps its bill visible; so does this document.

 Arrival is simultaneously the most locally vulnerable artifact and the only
 irrecoverable one. Lose the sqlite index — rebuild it. Lose the shared
 projection — rematerialize it. Lose arrival, and “this custodian received these
 records in this order” cannot be recreated from any surviving artifact; the facts are
 re-adoptable only into a new lineage. The durability asymmetry inverts from
 today. Mitigation falls out of append-only: incremental backup through a known durable head,
 no snapshot coordination required.

 The artifact humans read moves to the derived side. The git-visible file
 — the thing reviewed and shared — is a projection, and readers will treat what
 they can see as authoritative. The interface must disclose the inversion; the conceptual
 model’s protected invariants are amended to require it (“derived artifacts never
 masquerade as canonical ones — including the ones people look at most”).

 Facts become residence-wide rather than branch-wide, permanently. The
 branch-travel workflow some might expect (facts scoped to a PR) is structurally unavailable
 — by argument §8.3, it always was.

 Sync acquires an explicit admission boundary that did not exist before,
 including signature verification on intake — new code, new operational surface.

 Insertion-sensitive projections keep their replay bill. Declared
 (K, id) orders pay checkpoint-and-replay when records sort into prior
 material — a derived, visible cost rather than a mode choice, but a cost.

## 11What remains open

The burden of proof has moved to implementation. These are the named targets.

Migration exactness is the first adversarial target. The architecture is
 unusually strict about historical claims, and migration is where a correct design can betray
 its philosophy by inventing data. The contract must establish, store by store, which permit
 exact reconstruction and which take the explicit adoption boundary.

Experiment residuals, not architectural blockers — the ruled transport is
 monotonic fast-forward and the semantic merge driver is explicitly deferred, so these are
 unanswered empirical questions from the old-log merge lab restated as implementation
 obligations: signed-tick migration/rebasing onto arrival positions (all lab
 ticks were unsigned), and aggregate reads across independently updated
 arrival-backed members.

The four cuts have not been attacked as a decomposition — nobody has
 pressure-tested whether cut A is atomically shippable.

The loops-go conformance oracle is out of tree and unaudited — the
 most consistently flagged blind spot across every review pass.

 Provenance. This document is a projection of the ratified design record in the
 strange-loops project store. Canonical facts:
 decision:design/arrival-substrate-laws (01M0871CH6HQBNH0DW0CNZM0XQ) ·
 decision:design/declared-fold-order amendments #4/#5 (01M070N08HX69QAEQ3TRPY72CQ, 01M086HT5JMSZXZ3KKZCCRJDY1) ·
 decision:design/projection-driver-model ·
 decision:design/shared-projection-transport ·
 decision:design/arrival-release-scope (01M08AB1PH9NJNAAKW85D8ZXFK) ·
 thread:admission-disposition, resolved (01M08A9REXYYMJJJZE58609JNS) ·
 observation:architecture/witness-position-rebuild-invalidation, updated with the merge experiment (01M08AAEFF4AS4Y6RCYJMR0YTM) ·
 decision:design/conceptual-model-protected-invariants, third protected-sentence edit (01M08ABB4SQC0PJQ0RN7VXF8ZD).

 Evidence. Consumer census and merge-lab transcript with reusable scripts:
 docs/dev/scratch/arrival-fable-pass/ in the repository.
 If a claim here disagrees with the store, the store is right and this page is stale —
 which is, of course, the whole idea.
