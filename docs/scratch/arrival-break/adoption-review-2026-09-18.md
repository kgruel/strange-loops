# C9 adoption contract review — 2026-09-18

Scope: read-only review of the C9 adoption design, existing initializer and
declaration recovery contracts, mapped credentials, and migration boundary.
The engine adoption implementation was not present at the first review pass;
the checks below are acceptance gates for the incoming engine/SDK work.

## Design requirements (must hold)

- The operation accepts an explicit authority descriptor, selected migration
  head `S`, reviewed declaration snapshot, adopting observer, mapped signing
  credentials, and optional report receipt. It must open through the registry,
  capture the actual head `H`, require `H == S`, and run `Full(S)` before any
  signature or append side effect.
- The declaration snapshot is caller-selected evidence. Do not read the
  current `.vertex` cache as authority, silently use a later cache, or infer a
  declaration from the migration source. Reparse the supplied bytes with the
  current Vertex grammar, validate runtime identity, reject duplicate subjects
  and loop/vertex collisions, and bind the exact bytes/documents to a durable
  hash in the intent.
- Before drafting, scan the verified prefix for: an existing current-lineage
  `_decl.genesis`; any fact whose ID is the physical lineage; and any
  historical `_decl.*` row that claims the physical lineage. Foreign or
  legacy declaration rows remain evidence and must not be selected as this
  store's authority.
- Verify migration genesis and key-introduction signatures with an injected
  ARRIVAL-domain verifier. Structural `Full` verification and
  `verify_target` do not establish key trust. Ordinary migrated envelopes may
  remain unsigned; adoption must not claim their authorship.
- Resolve the adopting observer's already-created mapped binding only after
  capture. The bound public key must be valid for that observer at `S`; no
  resolver mint, legacy import, fallback, or key replacement is allowed.
  FACT and ARRIVAL signatures for the single `_decl.genesis` must be distinct
  domain requests, independently verified against the captured key, and the
  public binding evidence must survive in the intent without private material.
- Append exactly one initializer-compatible `_decl.genesis` draft with fact ID
  equal to the physical lineage, `before=S`, and no mutation of prefix bytes.
  The synthetic anchor is outside migration source-equivalence comparisons.
- Recovery must reserve the exact draft and evidence, never re-sign or append a
  duplicate, and revalidate that `S` is still the pre-append head. A known
  append followed by sync/cache failure is a committed-incomplete outcome that
  retains the real commit. An unknown append must remain recovery-required
  until exact content proves whether it landed.
- After the append, sync explicitly through `A`; inspection/read/write must
  agree on basis `A`. A projection/cache failure cannot erase or roll back the
  custody commit.

## Incoming API concerns

- The SDK now wires the engine's explicit `reviewed_text`/
  `reviewed_sha256` fields. Keep a real engine-backed test: the existing seam
  test monkeypatches preparation and would not catch a future argument drift.
- `CredentialPurpose` currently has initialization, authorship,
  key-introduction, and receipt purposes but no adoption purpose. The mapped
  API should either add an explicit adoption purpose or document and test a
  deliberate, non-conflicting purpose choice; silently reusing initialization
  credentials weakens the domain/purpose boundary stated by C9.
- The SDK wrapper currently requires `selected_head`, declaration bytes, and a
  declaration hash, which is the right shape. It must also ensure the supplied
  head lineage matches the parsed descriptor and expose typed refusal,
  unknown, and committed-incomplete outcomes rather than collapsing them into
  a generic SDK error. Recovery must not require the original provider/key.
- The wrapper must not import the migration sidecar into ordinary SDK paths or
  call a legacy writer. Its descriptor lookup must preserve opaque backend
  locations and pass the exact registry supplied by the caller.
- Intent evidence should include descriptor, `S`, selected document hash and
  canonical documents, observer, fact/Arrival binding public evidence, exact
  draft/signatures, and optional report verification at `S`; it must exclude
  private keys and report verification after the anchor changes the live head.

## Concrete acceptance cases

1. Sidecar output has backend/file, physical lineage, authority role, and
   `Full(S)`; report verification succeeds at `S`; pre-adoption sync still
   refuses declaration-dependent inspection/read/write.
2. Refuse before append for stale `S`, wrong lineage/role, malformed or
   changed snapshot bytes, invalid runtime identity, duplicate subjects,
   wrong mapped public key, missing binding, bad genesis/key-introduction
   signature, current-lineage anchor, physical-lineage fact-ID collision,
   historical declaration overlay claiming the physical lineage, and a new
   or replaced observer key.
3. Success appends one anchor at `S+1`, preserves every prefix record exactly,
   and makes sync/inspection/read basis the new head. A migrated ordinary
   envelope remains unsigned and is not reported as adopted authorship.
4. Inject failures after append, projection sync, and cache publication;
   recovery finishes from the durable intent without duplicate anchors or
   replacement minting. Inject an unknown append and require a refusal until
   exact ledger evidence resolves it.
5. Verify a supplied migration report against `S` before append. After
   adoption, do not rerun the report's live-head equality check or imply that
   the report is an on-ledger identity record.

## Landed implementation findings

- **Resolved:** the first implementation had two recovery integrity gaps. Both
  were reproduced: tampering intent binding evidence, or tampering the anchor
  signature while updating `exact_drafts`, still completed recovery. The fix
  now requires public FACT/ARRIVAL verifiers, repeats `Full(S)` and the
  registry check, validates coherent FACT/ARRIVAL evidence against the key
  valid at `S`, reconstructs the canonical anchor body, and verifies both
  signatures before append or acceptance of an existing row.

  Rerunning both original probes now refuses with `AdoptionApplyError` and
  leaves the ledger at `S`; restoring authentic intent bytes then recovers with
  the offline-key verifiers. The later-tip probe also preserves the exact
  adoption head in `commit.after` and reports the concurrent tip separately.

## Scope boundary

The first slice does not need key-changing adoption, automatic source
snapshotting, live-store orchestration, archive/recovery of projections, or a
new durable source-to-anchor provenance event. Those are separate design work
unless the implementation makes them part of its public contract.
