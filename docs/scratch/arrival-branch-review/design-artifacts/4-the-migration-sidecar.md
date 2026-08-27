The Migration Sidecar

Contract Specification · strange-loops 1.0

# The Migration Sidecar

The one-time, frozen ceremony that carries a 0.x store into an arrival log — sibling to The Arrival Substrate and The Arrival Log.

Authority: this spec implements the migration obligations of decision:design/declared-fold-order amendment #4, fact 01M070N08HX69QAEQ3TRPY72CQ, and is invalid read apart from it.

## 1What the sidecar is

The sidecar is a frozen artifact, not a maintained surface (ruled: arrival-release-scope). It bridges exactly two pinned ends: the last 0.x reader and the first arrival writer, as frozen dependencies, uvx-runnable years after 1.0 ships. It runs once per store. When it is done, the store carries its own migration evidence — provenance lives in the store, not the tool — which is what makes deleting the tool safe. residence.py and store/rebirth.py die with it.

One permanent residue remains in 1.0 proper: a legacy-shape detector that refuses with teaching and names the sidecar. It makes a location claim ("this is a 0.x artifact"), never an open-and-read path.

Sidecar-ness relaxes the maintenance commitment, never the epistemics. Everything below was a release blocker before the sidecar ruling; it is a release blocker for the sidecar.

## 2The genesis is containment-only

Ruled · sidecar-containment-genesis

The migration genesis asserts exactly: "this lineage contains a faithful re-encode of source X" — source hashes, counts, classification facts attached. It never asserts continuation.

Continuation is a custody claim, and custody claims belong to owners, not tools. If an owner later wants "this lineage continues my old store's identity," that is a signed declaration layered on top, made in the owner's voice, verifiable against the containment receipt already in the log. The custodian-continuation question is thereby relocated outside the sidecar entirely; the sidecar does not block on it and cannot prejudge it.

## 3Lineage identity: the content-addressed genesis

Ruled · sidecar-deterministic-genesis + amendment

The migration lineage id is the content-address of the canonical genesis record itself — the hash of the genesis record's canonical bytes, which carry the source hashes and the founding key when present. Tool version lives beside the id in the receipt, never in it: the id answers what was contained; the receipt answers who, what, and when did the containing.

This strengthens the existing invariant ("the genesis row's own id is the lineage id", sqlite_store.py:834) rather than amending it: for this one record — the only record nothing prior can witness — the id becomes content-derived instead of minted.

### Custodian cases

Same custodian, rerun. Same genesis record → same id. Idempotence is a derivation check, not a guard protocol.

Two keyed custodians, same source. Different founding keys → different genesis bytes → different lineages. Each containment is a distinct custody act, which is exactly what containment says it is.

Two keyless custodians, same source. Byte-identical genesis records → the same lineage, honestly: the containments are indistinguishable in every way the log can express. Post-genesis divergence is a same-lineage fork, refused at exchange time by ordinal-content mismatch — the same structural-refusal law as cross-lineage comparison (undefined, not false). No new machinery.

Rejected arm: per-run entropy salt — it restores keyless uniqueness at the cost of the structural idempotence the ruling exists to provide.

The derivation basis is the canonical genesis record bytes, not raw source file bytes: a merged or WAL-carrying sqlite source has no single canonical byte stream. The genesis record's source-hash fields carry the content commitment, and those fields commit to canonical record bytes in carried order for the same reason — a VACUUM or WAL checkpoint changes a sqlite file's raw bytes without changing content, and hashing raw file bytes would break the §7 idempotence claim for exactly those sources.

### Circularity and signature placement

The genesis record's own id is the lineage id, and the id is the hash of the record's canonical bytes — so the hashed stream excludes the id field (hash-then-embed, git-object style). The hashed stream also excludes the signature: rerun-idempotence must not depend on a signature scheme happening to be deterministic, and a future scheme change must not silently re-key lineages. The signature covers the record including its embedded id, as with every other record.

## 4The exactness contract

Verified premise (in-session, sqlite_store.py:157–164, 1510–1538): no rowid appears inside any signed or hashed bytes. Tick envelopes commit to fact-id cursors; window hashes use rowid only as a selector. Therefore signed history migrates exactly — no re-signing — iff the sidecar preserves, verbatim:

record bytes,

relative fact order,

relative tick order,

cursor ids.

Ordinals are per-record (ruled: arrival-batch-ordinals): batch lines expand in row order, occupying a contiguous range, and the arrival witness order must be order-isomorphic to legacy rowid order — the property the verifier's window-hash recomputation checks. Casualties are exactly the non-cryptographic residue: seq:N handles and FTS watermarks, which re-key under arrival.

Disclaimer · ruled in arrival-genesis-bootstrap

Legacy physical position ≠ 1.0 witness ordinal, even for order-VERIFIED stores. What is preserved is relative order, record bytes, and tick relationships — never receipt-number identity.

## 5Classification is the verifier's exit code

There is no classifier component (ruled: migration-order-classification + amendment). The migration verifier lives inside the frozen sidecar — a verifier maintained apart from a frozen migrator drifts — and must run regardless, because exactness (§4) is what keeps signed history valid. Per segment, it has exactly three exits, each written into the log as a classification fact:

VERIFIED — chain / line-order evidence confirms the carried order. Typical: project.jsonl (line order ≡ rowid over all facts); modern config stores with full fact_cursor chains.

ASSERTED — dense rowid order carried verbatim; nothing in the store can falsify it. Typical: chainless-era stores, pre-chain archives.

MINTED — interleave was reconstructed — the adoption boundary. Typical: ticks with null / unresolvable cursors; merged stores' tick populations.

Signature era is the orthogonal axis, classified per segment ("unsigned before position N"). Per-segment classification never fragments the lineage: one store → one arrival log → one genesis; classification annotates, it does not split.

Each classification is a scoped location claim ("order evidence here is rowid-only"), never a verdict claim ("this order is true") — never-manufacture-precision, which cuts both ways: the sidecar neither upgrades evidence nor discards it. Blanket "everything migrated is pre" was considered and rejected for exactly that reason.

## 6Attestation: the keyless arm

Keyless migration of a signed source requires explicit --allow-unsigned (ruled: migration-genesis-attestation). Hard refusal punishes exactly the user the frozen sidecar exists for — arriving years later, possibly without custody. Silent proceed is ruled out by classification-as-fact. The downgrade is deliberate at ceremony time (the flag) and loud permanently (a classification fact: signature era UNSIGNED opening a lineage whose source was signed). A migration genesis is a new lineage, so the era downgrade is legal there — it must merely be loud.

## 7Idempotence and resume are structural

Both were release blockers by ruling; under the content-addressed genesis (§3) they stop being protocols and become properties:

Idempotence. "Already migrated?" is answered by deriving the lineage id from the source and checking for it. A rerun over unchanged source converges on the same lineage; there is nothing to guard.

Resume. The target lineage is known before the first byte is written, so resume is: derive the id, find the log, verify its last committed record (torn-line truncation applies — arrival inherits _read_lines / _truncate_torn_line, which are correct here because arrival is the genuinely append-only artifact), and append from the ordinal where it ends. The rebirth crash-window failure — receipt committed, seal not, never-overwrite guard makes retry impossible — is unconstructible: there is no non-deterministic id to orphan.

Ceremony order: genesis record → carried records (with interleaved classification facts at segment boundaries) → sealing genesis tick. A crash at any point leaves a prefix; resume verifies the prefix and continues. Only the final seal marks the migration complete; an unsealed log is a named incomplete state, not a lie.

## 8Population inventory

project.jsonl (jsonl-canonical, ~3.7k facts / 92+ ticks) — Lossless re-encode of existing line order; expected VERIFIED throughout, both eras.

Six sqlite-canonical config vertices — Fact/tick interleave passes through _receipt_order; chained segments VERIFIED, chainless segments ASSERTED, unresolvable-cursor ticks MINTED.

Archive / chainless-era stores — ASSERTED order carried verbatim; no adoption genesis needed — the order is not manufactured, merely unfalsifiable.

Merged stores — Fact order ASSERTED (current rowid order genuinely is receipt order; no truer order exists); tick population MINTED (merge stripped chain columns).

Blast radius of the weaker grades: this corpus. Every store a 1.0 user is likely to hold migrates order-VERIFIED.

## 9Resolved residuals

own_lineage vs _decl.genesis: no collision. own_lineage is a store_meta marker pointing at the genesis row whose id is the lineage id; under arrival the marker's content moves into the genesis fact and the marker dissolves as index-side residue.

Rebirth as template: the tool dies (ruled: rebirth dissolves), the discipline is inherited — receipt fact with source hashes and counts, sealing genesis tick. Its crash-window defect is specifically designed out (§7).

## 10Open items

Ruled · rebirth-tick-facts-order-grade

The 216 rebirth tick.* facts (re-entered as facts in the 2026-06-12 rebirth) are just facts: they migrate under their segment's order grade, no special-casing. Their tick-hood is historical content, not custody structure — records about ticks that once existed, admitted by a past ceremony. The arrival log carries what was admitted; it does not reinterpret it. Going forward, the interleaved single file gives real ticks real positions, so the pressure that produced tick-as-fact re-entry cannot recur.

Queued · implementation

Interleave-uniqueness conformance vectors (accepted obligation, loops-go queue) exercise the same order-isomorphism property the sidecar verifier checks; the verifier and the vector family should share fixtures.

## Colophon

Backing facts, in ruling order: anchor 01M070N08HX69QAEQ3TRPY72CQ (declared-fold-order amendment #4) · design/arrival-release-scope · design/migration-order-classification + amendment 01M08Q7129MKN6RPKVFT7J5QQ1 · design/migration-genesis-attestation · design/arrival-batch-ordinals 01M08N9H33H3X06A9ZR9X00V1Q · design/arrival-genesis-bootstrap 01M08N9H8GT4WQXMPGJN3ADWW4 · design/sidecar-containment-genesis 01M08Q6P3P81575S5R6PGHJNGB · design/sidecar-deterministic-genesis 01M08Q7C4GZZBCCN5HHR1E48VF + amendment 01M08R3PWYPEK30F21N2XJ7KYS · design/rebirth-tick-facts-order-grade 01M08RBHV28PQPE3K5HEW6KWFJ. Drafted 2026-08-17, Kyle Gruel with Fable, sidecar-spec unpacking session.
