The Arrival Log

strange-loops · design specification · ratified 2026-08-17

# The Arrival Log

 The Arrival Substrate established the model: one append-only custody log per
 custodian, everything else a projection of it. This document is its sibling and lays out the
 artifact itself — the file on disk, its line grammar, the genesis ceremony that opens it,
 the observers and keys that live inside it, and the seams where custody ends and drivers,
 projections, and secrets begin. Nearly all of it dissolves into machinery loops already has;
 the few genuinely new rulings are recorded here with their grounds.

 Design session 2026-08-17 · Kyle Gruel with Claude Fable 5 ·
 sibling to The Arrival Substrate · every ruling backed by a decision fact in the
 project store (colophon)

Contents

The dissolution result

The file: JSONL, ratified

Line grammar and position

What the log contains

Genesis: three movements

Observers, keys, verification

Rotation, revocation, taint

Aggregation membership

Ceremonies and the CAS

Integrity posture

Migration touchpoints

Deferred, on record

## 1The dissolution result

The arrival log is not a new format. It is the existing codec under new law.

 The session opened on one gating question: does the arrival log dissolve into the JSONL codec
 loops already ships — the same three line shapes, with new custody semantics around them
 — or does it need a new envelope? The walk-through answered it shape by shape: admitted
 assertions are fact lines, ceremonies are batch lines, seals are
 tick lines, genesis follows the rebirth template as a fact plus a sealing tick,
 and witness position is line position, computed and never stored. Nothing arrival needs to say
 lacks a home in the grammar that exists.

 One retroactive win falls out for free. Today facts and ticks live in two sqlite tables with
 independent rowids, so their interleave is recorded nowhere — the whole
 _receipt_order reconstruction problem exists because of that split. A single
 interleaved file records the interleave as a plain property of line order. The defect the
 migration census spent five readers characterizing simply cannot occur in the artifact being
 migrated to.

Ruled

 No new file type, no per-record envelope. The one place dissolution strained — nothing
 commits to order between seals — was accepted deliberately: order between seals
 is asserted by custody and committed by the next seal. Seal density is the ruled
 integrity lever (§10), not per-record chaining, which would protect against an adversary
 who could re-chain anyway and would make every record’s bytes position-dependent,
 breaking verbatim migration.

## 2The file: JSONL, ratified

The custom-format ideation was run, and it failed the dissolution test.

 The question was asked squarely: is JSONL as the store format worth reconsidering
 before the contract freezes? The answer turned on what the physical format must actually
 provide — and on what it need not. Law 1 removes read performance from the
 requirements entirely: reads execute through derived indexes; the log is parsed only at index
 build and at verify. That kills the traditional case for binary before it starts.

 | 
 | Candidate | What it buys | Why it fails

 | Length-prefixed binary frames
 | Faster parse, per-record CRC, cleaner torn-write detection
 | Loses cat/grep/git-diffability; re-derives test-pinned
 machinery (torn-tail, batch atomicity, golden fixtures) with fresh bugs; the CRC
 protects unsealed spans against disk rot — a threat already accepted under the
 seal-density posture. Buying it back via encoding re-litigates that ruling.

 | CBOR / msgpack lines
 | Smaller records
 | Canonical binary encoding is a spec minefield, and the storage encoding would diverge
 from the JCS commitment surface — every verify would round-trip a translation.
 Today stored bytes are committed bytes; that identity is load-bearing.

 | sqlite as canon
 | —
 | Already ruled out: the index is derived and droppable. Making it canonical
 resurrects the two-mode store.

 The argument that decides it beyond reuse: the record-completeness gate makes JSONL-canonical
 records the bindable exchange representation. Custody format equal to exchange format
 means one representation of canon — no translation layer between what a custodian holds
 and what it publishes, no divergence surface between two spellings of the same record. And
 there is a product stance in it: a loops user’s entire evidentiary history is readable
 with cat, greppable, diffable — the same “see it directly”
 property the .vertex fold-out gives declarations, held at the store level.

Ruled, with two riders

 The arrival log’s physical format is JSONL — the existing codec.
 Rider one: the genesis fact carries a format-version field, the one-break
 budget’s exit hatch — if a different encoding ever becomes necessary it is a
 future loud break, detectable at line 1 rather than archaeologically. Rider two:
 blobs stay out of the grammar — large binary content is sourced and
 referenced from facts (content-addressed, by hash) when needed, never inline, so attachments
 can never become a format argument later.

## 3Line grammar and position

 Three line shapes, discriminated by "t", exactly as the codec defines them today:

{"t":"fact", id, kind, ts, observer, origin, payload[, signature]}
{"t":"tick", id, name, ts, since, origin, payload,
 prev_hash, window_start, fact_cursor, window_hash[, signature]}
{"t":"batch", rows:[<fact records>]} // ≥2 rows, no nesting, no ticks inside

 The codec’s disciplines carry over unchanged, because they are precisely arrival’s
 requirements: payload rides as the verbatim stored string and is never
 re-serialized, so round-trips re-derive byte-identical commitment hashes; signature
 is absent, never null, when unsigned — one canonical spelling per record; a
 line is the atomicity unit, so a ceremony is indexed whole or truncated whole; a torn tail is
 truncated, never skipped.

### Witness position

 A record’s witness position is (lineage, ordinal) — the lineage
 minted at genesis, the ordinal its position in the record sequence: line order, with
 batch lines expanding in row order. Ordinal is per-record, not per-line
 — forced by the existing machinery, which indexes each batch row to its own rowid, and by
 class (b) migration verification, which recomputes window hashes over the carried order
 and would break if a migrated store’s fact counts disagreed with its own signed history.
 A batch therefore occupies a contiguous ordinal range; atomicity is an
 admission property (the line commits whole or truncates whole), never an addressing
 property — a read basis may land mid-batch, exactly as a fact-id address can name a
 mid-ceremony fact today. The record is what position addresses; the line is the atomicity unit.

 Position is computed by append(record) → stamp, never
 stored in the record. A stored ordinal would be a second authority that could disagree with
 actual position — the exact defect class merge created — and the migration ruling
 forbids fabricating per-record receipt data for history that never carried it. Under arrival,
 seq:N inverts from the most dangerous address form (a rebuild renames its
 referent) to the canonical coordinate: ordinals in an append-only, never-rebuilt file are
 stable by construction.

## 4What the log contains

Everything that is evidence. Exactly four exclusions.

 The conception ratified in-session: a 1.0 arrival log contains the entirety of the
 vertex — genesis, the vertex definition, the observers, the memberships, every assertion,
 every seal. The census walked every artifact class in a complete loops deployment and the
 boundary came out crisp:

 | 
 | | Artifact | Disposition

 | in | Assertions, seals | fact and tick lines, as ever

 | in | Vertex definition (kinds, folds, name) | Already in: _decl.* facts via the absorb ceremonies, as batch lines

 | in | Observer introductions, grants, rotations, revocations | Declaration-vocabulary facts (§6–7); the observers{} block joins the declaration document set

 | in | Aggregation membership | Declaration facts in the aggregator’s lineage (§8)

 | in | Genesis + migration receipts, classification facts | Rebirth template: receipted fact + sealing tick

 | out | Secrets | Private keys never enter the log

 | out | Code | Lenses are interpretation machinery, not custody

 | out | Transport | Driver config, credentials, cursors, locator maps — watermarks, resettable

 | out | Its own address | A log naming its path lies the moment the file moves

The .vertex file becomes a projection

 The editable KDL file is folded out of the arrival log for convenience
 — iterating, experimenting, seeing it directly — and edits-on-file are
 re-absorbed through the declaration ceremony. It is a derived artifact and
 the interface must say so, the same way every file-to-store authority transition is
 disclosed. Derived artifacts never masquerade as canonical ones — including the ones
 people look at most.

## 5Genesis: three movements

loops init stops creating files and starts opening a lineage.

 A fresh 1.0 log opens with a genesis ceremony of three movements — self-certifying
 genesis, declaration absorption, seal — committed before the first ordinary admission.
 The ordering carries a bootstrap proof (caught in Sol’s review of this document’s
 first draft, which had the key introduction after the declarations it was supposed to
 sign): the genesis fact is the founding introduction. Line 1 carries the
 lineage id, the format-version, and the founding public key, self-signed by that key —
 so every subsequent line, the declaration batch included, is signed by a key the log has
 already introduced. No line is unsigned in a signed lineage; no verification is retroactive.

 [figure omitted]

 Anatomy of an arrival log. Movements: self-certifying genesis (id + format-version +
 founding key; for migrations, source hashes/counts and classification facts), declaration
 absorption signed by the just-introduced key, then the genesis seal. Ordinary admissions
 follow; the numbers shown are record ordinals, which is why the batch at line six spans two.

 For a migration, movement one is the legacy-adoption receipt: source hashes and counts on the
 rebirth template, plus the classification facts — order
 verified / asserted / minted
 per segment, signature era orthogonal (§11). One store, one log, one genesis:
 classification annotates segments; it never fragments the lineage.

## 6Observers, keys, verification

The registry moves into the log, and verification becomes position-dependent.

 Today the observer registry — name to public key, grants included — lives in the
 .vertex file, and verify_chain checks all of history against the
 registry’s present state. That timelessness is a defect twice over: rotate a key
 and old signatures break; add a key and it retroactively validates records signed before anyone
 trusted it. And it is the exact failure measured in the homelab: a peer’s ticks
 unverifiable in one vertex because its key lived only in another vertex’s file.

Position-dependent verification

 Observer introductions, grants, rotations, and revocations are ordinary signed facts in the
 log. The verifier walks from line 1 maintaining the key registry as a projection:
 a key is valid at position N iff introduced before N and not revoked
 before N — or N is the genesis position and the record is
 self-certifying, the one explicit clause of the bootstrap (§5); legal at
 ordinal 0 and nowhere else, never retroactive. Every lineage carries the keys needed to
 verify itself — the log is cryptographically self-verifying with
 nothing beside it. (Self-verifying is not externally authenticated: a TOFU genesis proves key
 possession, never who holds the key — see the bootstrap below.) This is the arrival
 restatement of the historized-keys
 ruling (internal-table-meta-schema, 2026-07-01): time-correct
 verification, rotation as a new row.

### The bootstrap: self-certifying genesis

 Line 1 must be signed by a key the log has not introduced yet. The circularity resolves
 by self-certification: the genesis fact is the founding introduction
 — it carries the public key and is signed by that key, trust-on-first-use at
 line 1, the same shape as an SSH CA root. It is honest about what it proves, because of a
 protected invariant loops already holds — signatures attest claims, not external
 truth. The self-signed introduction attests possession: “the holder of this key
 opened this lineage.” It does not attest that the key belongs to any person; names are
 lineage-local labels, and binding a name to a person across lineages is the vouch arc,
 deliberately deferred. Anyone can mint a lineage claiming any name — that is the
 honest scope of local custody, not a defect.

 Later observers are introduced by facts signed by an already-introduced observer, so every
 introduction is attributable, and the admission check “source not authorized for
 intake” reads its authorization from the log itself. Keyless genesis stays coherent:
 --allow-unsigned opens the lineage with no self-certifying anchor, the
 classification fact records signature era UNSIGNED, and an introduction
 can open the signed era later — the unsigned→signed transition era-monotonicity
 already permits.

## 7Rotation, revocation, taint

Rotation was already ruled. The compromise case was the one true gap, closed this session.

 The cooperative cases were settled by the 2026-08-14 custody arc and the meta-schema ruling
 before it: rotation within an observer’s key set is invisible to everyone else’s
 grants; removal is a forward-only epoch rekey (“stops seeing new, never unsees
 old”); delegate revocation is certificate expiry, never a registry event; and registry
 mutations must be signed facts, verified before honoring. What no prior pass unpacked:
 what a revocation means for records signed between a key’s compromise and the
 revocation’s position.

Ruled — arm one, the default

 Taint stays in place. The records were legitimately admitted — at
 admission time the key was valid, so the receipt was and remains true. Compromise degrades
 the attribution (signature no longer implies author for the span), never the
 receipt; excising records would delete true history to fix a false inference. Excision is
 also the operation arrival exists to forbid — a rebuild-with-holes renumbers every
 later witness position, breaks every seal over the span, and establishes that custody history
 is editable, capping the log’s evidentiary value permanently. The revocation fact gives
 every projection a position-bounded predicate — “signed by K in
 (introduction, revocation)” — to discount, exclude, or flag per purpose,
 reversibly if the compromise window is later re-assessed. Tainted-span disposition
 is interpretation policy: admission records observation, not semantic eligibility, applied to
 keys. The taint is also the forensic record of the incident itself.

Ruled — arm two, content destruction

 When tainted content must genuinely cease to exist — a live secret or
 poisonous payload written into the log — the operation is the single re-custody
 ceremony, never an in-place rebuild: a new lineage, genesis receipted with source
 hashes, classification facts recording exactly what was excised and why. Old positions die
 honestly because their lineage is retired, not silently renumbered. Second instance of the
 ceremony beside the 0.x→1.0 sidecar; nothing is built for revocation at all.

## 8Aggregation membership

Vertex registration dissolves into declaration state in the aggregator’s own lineage.

 Membership is not an admission — nothing arrives from a source. “This vertex’s
 answers draw on these lineages” is the custodian’s interpretive commitment, which
 makes it declaration state, changed through the declaration ceremony in the
 aggregator’s own log. The vocabulary already exists: the meta-schema’s CONSTITUTION
 events name member-defined / member-removed as historized
 combine constituents. Today’s config globs and combine blocks appear in no
 receipt anywhere — “what was the root vertex aggregating in June” is
 unanswerable. Under this ruling it is a fold over CONSTITUTION events.

 | 
 | Where | What | Why there

 | In the aggregator’s log
 | Membership declarations naming members by lineage id
 | Stable, minted at member genesis, machine-independent; aggregated-read provenance is
 incomplete without it — that is what earns log residence

 | Outside, driver config
 | The locator map: lineage id → current path / remote / schedule
 | Paths are transport; a log naming filesystem paths lies the moment anything moves

 | The discover glob
 | Degrades from authority to a discovery driver
 | Scans, reports “lineage X found at path P,” drafts a membership
 declaration edit for the custodian to absorb — Law 3 shape, through the
 declaration ceremony

 One boundary deliberately unmoved: ad-hoc combine stays registration-free.
 Pointing a read at arbitrary stores remains a pure read-path operation. Membership declarations
 are for standing aggregation, where the composition is part of what answers mean; exploratory
 reads carry no membership provenance, honestly.

## 9Ceremonies and the CAS

cas(head) is specified: conditional append on a kind-scoped witness position.

 The surviving verb set is append(record)→stamp, records_from(pos),
 cas(head) — and the last needed sharpening. A declaration edit guards
 against “a declaration change slipped in since I folded out the file,” which is a
 CAS against the declaration head. CAS against the arrival head would be spuriously
 strict: any ordinary admission between fold-out and re-absorb would fail an edit with no actual
 conflict.

Two scopes, frozen shrink-only

 The condition is “append this batch iff no record of kind-class K admitted since
 position N,” with exactly two sanctioned scopes:
 K = everything (the arrival head — transport, backup
 boundaries) and K = declarations (the ceremony guard, what
 _declaration_head_in_txn already computes). No predicate generalization —
 “append-if no record matching P” is a query language growing inside the
 custody boundary, and admission stays too dumb to evaluate semantics. A third scope requires
 demonstrating a ceremony that is structurally neither ordinary admission nor a declaration
 edit — and every ceremony named in this arc (introductions, grants, rotations,
 revocations, membership, epoch mutations) is declaration-shaped, because the observers block
 and membership were both ruled into the declaration document set.

 Rider: _decl.* promotes from convention to contract-level
 namespace — it binds forever under the one-break budget, said out loud. It is
 structural, not semantic: the custodian distinguishes declaration records the way it
 distinguishes fact lines from tick lines, knowing nothing of what any declaration means. The
 namespace already exists de facto (_decl.genesis, the frozen
 *-defined/*-retired edit vocabulary, _meta.own_lineage,
 _topology); under arrival, _meta.own_lineage moves from
 store_meta into the genesis fact and dies with the derived index.

 Surface rider: the SDK types the two coordinates as distinct types —
 ArrivalHead and DeclarationHead — never a generic position plus
 a flag, so the frozen scope set lives in the type system rather than in review vigilance. The
 verb renames to guarded_append: cas(head) under-describes semantics
 that are “append iff no record of class K arrived since N,” and an API
 shaped like a generic CAS quietly makes arbitrary predicates look like an obvious extension.

## 10Integrity posture

What commits to what — and the honest sentence about what doesn’t.

 | 
 | Mechanism | Commits to

 | window_hash | Fact content and fact order between two id-resolved cursor bounds, in line order — facts only

 | prev_hash | Total order over ticks, chained tick to tick

 | fact_cursor | Which fact each tick follows — ties among cursor-sharing ticks break by chain order

 | signature | Authorship of the record’s claim, per observer, position-verified (§6)

 Windows stay facts-only by force, not preference: signed history migrates exactly iff its
 committed bytes are unchanged, and historical windows commit to fact rows between cursor
 bounds. Including tick lines would change every window’s input and demand re-signing,
 which the exactness ruling forbids. Nothing is lost, and the reconstruction rule is stated
 rather than gestured at: a tick’s cursor assigns it to the gap immediately after
 fact F; ticks sharing a gap order by chain; chain continuity makes cursor assignment
 monotone — given ordered facts, ordered ticks, and per-tick gap assignment,
 exactly one total interleave exists. That is a claim that can be falsified automatically, so it
 must be: interleave uniqueness is a conformance-vector obligation, a candidate
 family for the loops-go oracle queue. (Correcting an overstatement in the substrate memo: no
 rowid was ever inside signed or hashed bytes — ticks commit to fact-id cursors, and
 rowid was only ever the ordering authority. That is why signed history migrates
 without re-signing at all.)

 The honest residue, accepted deliberately: between seals and on the live edge, the log’s
 only integrity is possession — it is the custodian’s file on the custodian’s
 disk. Seal density is the policy lever: a custodian wanting finer-grained
 commitment seals more often. Per-record chaining was considered and rejected — it defends
 against an adversary with write access to the custody log, who could re-chain regardless, and
 its cost lands on the honest path by making every record’s bytes position-dependent.

## 11Migration touchpoints

What this document’s rulings hand the sidecar spec.

Class (a) is a re-read. The JSONL-canonical flagship store is already in
 the arrival format’s line grammar; migration re-encodes nothing — it prepends
 the genesis ceremony and carries lines verbatim.

Legacy physical position ≠ 1.0 witness ordinal — even for
 order-verified stores. The genesis ceremony shifts every carried
 record by its own length, and no old integer is claimed: what is preserved is relative
 order, record bytes, and tick relationships — never receipt-number identity. Stated
 so nobody tries to preserve integers and invents a phantom pre-genesis region.

Classification facts land in movement one of genesis: order
 verified / asserted /
 minted per segment, signature era orthogonal. Scoped location
 claims, never verdict claims; one store → one log → one genesis.

Signed history carries byte-exact — record bytes, relative fact
 order, relative tick order, cursor ids verbatim. Facts-only windows (§10) are what
 make this possible.

Keyless migration of a signed source requires explicit
 --allow-unsigned; the downgrade is deliberate at ceremony time and loud
 permanently as a classification fact.

Casualties re-key, by design: seq:N handles and FTS
 watermarks die with the rowid axis; witness addressing re-keys onto (lineage, ordinal),
 where it is stable by construction.

## 12Deferred, on record

 | 
 | Item | Status

 | Lineage-copy detection / custodian binding (who may append; a byte-copied log
 carries its lineage id)
 | Deferred to the custody discussion — binding is custody-side state, not log
 content

 | Key loss / escrow (recovery-wrap story)
 | Open from the encryption arc; orthogonal to the log format

 | “Merge racing an epoch rotation” (encryption arc’s deferred item)
 | Closed by dissolution: arrival is never merged; the race is a
 driver-level admission-ordering question inside one lineage

 | Sidecar contract spec
 | Next. Must reference the full migration ruling
 (01M070N08HX69QAEQ3TRPY72CQ) directly — it is
 invisible from folded reads

 Decision facts backing this document (project store)
 design/arrival-log-format · 01M08KK74KMY6JYFRY014P9G4B
 design/key-revocation-taint-disposition · 01M08HZSS8EXYWSS2PXJZAD8KH
 design/aggregation-membership-as-declaration · 01M08M4WX608FVQTSY75PC1CC7
 design/arrival-cas-two-scopes · 01M08MD6Y51BS2RJ8136J5DGFV
 design/arrival-batch-ordinals · 01M08N9H33H3X06A9ZR9X00V1Q
 design/arrival-genesis-bootstrap · 01M08N9H8GT4WQXMPGJN3ADWW4
 self-certifying genesis ratification · thread:arrival-migration-arc · 01M08J0C… / 01M08KE1…

 Standing on: arrival-substrate-laws 01M0871C ·
 declared-fold-order #4 01M070N0 / #5 01M086HT ·
 log-and-index-roles 01M070P4 ·
 arrival-release-scope 01M08AB1 ·
 migration-order-classification · migration-genesis-attestation ·
 internal-table-meta-schema · custody-identity-artifact 01M016G9

 Review: cross-family pass by GPT 5.6 “Sol” (artifact-only, no code
 access), 2026-08-17 — three contracts settled (batch ordinals, genesis bootstrap, custodian
 continuation deferred as ruled), four riders folded in (§6 scope qualifier, §9 typed
 heads, §10 interleave rule, §11 ordinal disclaimer).

 Sibling document: The Arrival Substrate (model, laws, evidence, shipping plan).
 This document: the artifact itself. · 2026-08-17
