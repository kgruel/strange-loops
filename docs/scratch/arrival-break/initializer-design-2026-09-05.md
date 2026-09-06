# Arrival initializer and declaration ceremony proposal

This is the next bounded design slice. It keeps the public operation name
`sdk.declare.init_vertex` and changes its ordinary single-store path to an
explicit Arrival initializer. It does not add `init_arrival`; aggregates keep
their separate scaffolding behavior until an aggregate ceremony is specified.

## Contract shape

Extend `init_vertex` with an explicit `StoreDescriptor` (or equivalent
backend, location, lineage, and role fields), require `role=authority`, and
require an observer plus operation-fresh signing credentials. The descriptor
is the only store selection input: no suffix probing, `probe_target`,
`_open_store`, SQLite, or legacy `absorb_genesis` call may appear on this
branch. SDK custody may keep the existing `CustodyCredentialProvider` shape
(`for_write(vertex) -> WriteCredentials`) and obtain the private signer from
the configured key file; the durable intent stores only the public founding
key, never private material.

The generated declaration text remains the presentation cache. Parse and
validate the proposed declaration with `lang` before any ledger mutation, and
ensure its store locator, backend, lineage pin, and authority role agree with
the explicit descriptor. A malformed declaration, wrong role, missing signer,
existing target, or incompatible existing store is a typed precommit refusal.

The lineage identity is allocated once before the first durable action and
persisted in intent. Pass it explicitly to the registry ledger's
`mint(options)`: `arrival_contract.ArrivalLedger` defines this operation, and
`_DescriptorLedger.mint` already enforces a descriptor lineage pin before
delegating. `ArrivalLog.mint` (arrival.py:873) assembles and signs the final
`{protocol, lineage, key}` genesis body and publishes it with its exclusive
staging gate. The registry's `AttestedLedger` must remain the only returned
custody surface so minting is witnessed.

## Recoverable phases

1. **Validate and reserve.** Resolve the descriptor from caller input, parse
   the declaration, derive its document set with `vertex_to_documents`, and
   prepare the exact declaration source text. Create the sibling
   `<target>.vertex.intent` with `O_CREAT|O_EXCL`, write, flush, fsync, and
   retain the descriptor, lineage, observer, public key, timestamps, document
   payload, declaration fact ID, and all planned signed draft content. The
   existing `engine.ceremony.intent_path_for` and exclusive intent discipline
   are the right shape, but the intent version and fields must be distinct from
   legacy declaration-update intents.

2. **Mint the physical lineage.** Open the registered adapter through the
   registry and call `attested.mint` with the reserved lineage, observer,
   signer, and public key. A wrong role is refused before the opener. A mint
   failure is recoverable by an attested re-open: if the exact reserved
   genesis is present, continue; if the store is demonstrably absent, retry
   the same reserved mint; if an incompatible artifact is present or the
   result is unknown, return a recovery-required outcome and never replace it.

3. **Append declaration genesis.** Build one `RecordDraft(kind="fact")` for
   `_decl.genesis`. Its fact-row body uses the reserved fact ID **equal to the
   physical ledger lineage**, the one timestamp and observer, the JSON payload
   `{protocol, documents}`, and the inner fact signature over the exact payload
   text. The Arrival envelope signature is separately computed over the final
   fact body using the existing `content_commitment("fact", ...)` rule. Append
   this draft with `expected=head0` through the attested ledger. The existing
   `ArrivalStore._genesis_payload` seam (arrival_store.py:694) confirms that
   Arrival declaration genesis carries only protocol and documents; legacy
   cursor and chain-era pins do not belong in this payload. One declaration
   fact is preferable to a batch here, so its identity and signature are
   unambiguous.

4. **Sync derived state.** After the declaration append is durably witnessed,
   request the backend's projection maintenance through its registered
   maintenance surface. This is rebuildable state and may be absent before
   sync. A maintenance failure must retain the intent and report the durable
   ledger head plus the projection's before/observed-after evidence; it must
   not claim that no derived write occurred.

5. **Publish and finish.** Atomically replace the `.vertex` cache using the
   existing tempfile/fsync/rename helper from ceremony.py, then remove the
   intent. A cache failure after the declaration append is a committed,
   recoverable result. No phase overwrites a pre-existing artifact merely
   because initialization was retried.

Recovery reads the intent first, opens the descriptor through the attested
   registry, and compares exact reserved genesis/declaration IDs, bodies,
   signatures, lineage, and projection basis. It classifies `not-applied`
   only when absence is established, `safe-to-finish` when the reserved
   ledger content exists and only a later phase is missing, `already-applied`
   when ledger and file agree, and `conflict` for any other content or
   lineage. A malformed or superseded intent remains in place for human
   diagnosis. This follows ceremony.py's existing “recovery never guesses”
   rule and avoids minting a replacement after an unknown append.

## Declaration edits after initialization

The descriptor-aware edit path should be added beside the existing ceremony
orchestration, not implemented by calling it. Capture the effective
declaration documents and control head from one `CURRENT` query snapshot, and
retain the full ledger head for append CAS. Convert the existing frozen
definition/tombstone changes into signed `_decl.*` fact drafts, using one edit
timestamp and the original annotation payloads. Append the whole change set
with one expected full-head CAS; the backend's atomic append limit decides
whether the request is supported. A stale head refuses before any append.

Replace the file cache only after the append commit. If replacement fails,
leave intent plus the actual commit for recovery; replay resolves the new
declarations from the ledger rather than trusting the stale file. The existing
`declaration.resolve_declaration_documents_from_snapshot` check remains the
source of the control identity: the licensed own declaration genesis has a
fact ID equal to the physical lineage. `reanchor` is removed and is not a
recovery synonym or authority-transfer implementation.

## Acceptance slice

The first implementation should cover a real temporary file backend: fresh
init yields ordinal-zero signed genesis and ordinal-one `_decl.genesis` whose
fact ID equals lineage; a `CURRENT` SDK read returns the same declaration
identity and basis. Tests inject failures after mint, declaration append,
projection sync, and cache publication, then recover without duplicate
controls or replacement minting. They also cover wrong role, malformed input,
missing signer, conflicting artifacts, stale edit CAS, and byte-preserving
cache failure. SDK results must serialize refusal, committed, and unknown
states through the typed error models. No legacy authority opener is allowed
on this path.
