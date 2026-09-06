# Declaration edits after initialization

The corrected disposition in `slice4-design-proposal.md` section F governs:
declaration edits survive, genesis absorption dissolves into initialization,
and reanchor is removed. Descriptor adoption is a separate designation operation.

## Existing behavior to preserve

`engine.ceremony` supplies plan/apply/recover and SDK `kind.py` supplies kind
mutations and observer grants/revocations. Today both use the legacy probe,
canonical store opener and SQLite declaration generation. They must move as
one supported operation; adapting only the final append leaves a bypass.

`SqliteStore.absorb_edit` is the current semantic source: subject-granular
whole-document definitions and tombstones from `lang.document.diff_documents`,
the complete frozen edit vocabulary (including vertex and lens singletons),
one effective timestamp for the entire edit, mandatory inner signatures, and
all-or-nothing persistence. Empty changes append nothing. Do not send reserved
declaration facts through the ordinary runtime's public admission bypass.

## Required Arrival path

1. Parse and validate proposed text before mutation. Resolve the existing
   explicit descriptor before legacy probe/open; backend/location/lineage/role
   changes are not a declaration-edit shortcut to adoption or authority transfer.
2. Capture one attested CURRENT snapshot. Its full custody Head is the append
   CAS, and its anchor/effective documents are the diff basis. The physical
   lineage equals the own declaration genesis fact ID. Ordinary appends after
   planning make this plan stale too; a declaration-only timestamp is inadequate.
3. Assemble and sign the exact final rows, with one timestamp and stable IDs.
   Mandatory inner fact signatures use the fact signer. Outer Arrival fact or
   batch signatures use a separate Arrival signer. Do not reuse one domain's
   callable for another. Pack the same-observer declaration transition into a
   batch so a historical receipt prefix cannot split that transition.
4. Introduce any newly declared public keys before records using those keys.
   `_decl.observer-defined` is semantic evidence; it does not itself introduce
   a key into Arrival's cryptographic registry. A `key` record must be signed
   by an observer whose key is already valid at that position. Include needed
   introductions and the declaration batch in the same exact-Head append.
   Keyless observers remain legal, and revoking an admission grant does not
   retroactively invalidate cryptographic evidence. Reanchor never rewrites
   earlier signatures.
5. Preflight all final record/atomic limits before append. Reserve a durable
   intent containing the captured Head, exact signed drafts, proposal text and
   expected old file bytes/fingerprint before entering the append. The intent
   must support proving exact record membership after an unknown outcome;
   comparing only the resulting document fold is not sufficient identity.
6. Append once, explicitly synchronize the projection, then publish the local
   declaration cache. Refuse a concurrent unrelated file edit; the cache write
   must not silently overwrite it. Known commits, unwitnessed commits and
   unknown append outcomes retain their distinct receipts and intent identity.
   No automatic retry that re-signs or manufactures a second edit history.
7. Recovery opens through the same registry and compares exact planned records
   at their expected positions. Finish the cache step only when those records
   are proved; unrelated later ordinary facts do not erase that proof. A later
   declaration transition requires care before publishing an older cache.

The existing SDK names should consume this path. Uniform versioned results
must expose descriptor, basis, planned IDs and actual Commit when available;
do not flatten committed-incomplete outcomes into `CeremonyFailed` with only a
message. Declaration inspection must likewise use the attested snapshot and
report syntax/cache drift separately from effective store documents.

## Acceptance examples

Real default custody initialization followed by add/edit/remove kind, grant
another observer and signed emission by that observer; verify both signature
domains and Arrival key history. Verify no-op, singleton edits, tombstones,
same-timestamp batch semantics, stale full Head, invalid proposal, missing
signer and oversized batch before append. Inject durable-then-raise, witness
failure, projection failure, intent-save failure and concurrent cache edits;
recovery must preserve exact drafts and never duplicate the transition.

This is an implementation handoff grounded in the existing contracts, not a
claim that the declaration stage is implemented or accepted.
