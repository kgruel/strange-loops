# Transfer integration handoff

Status: primary's source inventory for the later transfer slice. No new wire
format, authority-transfer protocol or implementation is introduced here.

The ledger already exposes `export`, `scan` and `replicate`. Engine transfer
tests pin export/import/export byte identity and prefix consistency under a
concurrent append. The missing work is the supported registry/SDK operation
boundary and removal of the old store-mode entry points.

`store.merge.merge_store` still selects SQLite, Arrival or refused legacy JSONL
from `probe_target`. Its Arrival arm constructs `ArrivalLog` directly and
materializes a legacy index before dedup. `engine.admission.admit_records`
already owns valuable comparison/draft/verification rules but still accepts an
`ArrivalLog`, calls `append_marked_many`, retries `AppendRejected`, and invokes
an unstructured rederive callback. Do not present this function unchanged as
the new witnessed transfer coordinator.

The operations must remain distinct:

- **Exact replication** preserves source lineage, coordinates, commitments
  and envelopes through a captured full prefix. Receiver designation and
  backend capabilities govern replication; no destination re-signing occurs.
- **Admission** takes foreign rows into a destination Authority, preserving
  exact authored fact payload text and inner signatures. Existing pure
  `_comparable`, `_drafts_for` and verification helpers define divergence and
  foreign tick handling. It is a new custody sequence, not a replica. Fresh
  local tick-chain/signing rules from runtime emission are not the admission
  rules. Dedup and admission decisions come from one attested target snapshot;
  execute with one full-head CAS and retain the actual commit/unknown outcome.
- **Slicing** selects observations and admits them elsewhere. A filtered set
  must never be labelled an exact ledger prefix. Legacy SQLite transport files
  are not the new transfer artifact.

Capture both source and target evidence explicitly. A source export may be
lazy: keep handles alive until the stream is consumed, and publish an output
artifact only after complete successful export. A source moving later must not
silently extend the promised prefix. Verification claims should identify the
captured prefix and level; source key-history self-consistency does not imply
that the destination operator trusts those keys.

Same-ID/equal-content is idempotent; same-ID/different-content refuses before
append. Incoming duplicate IDs must also be checked within the offered set.
An explicit retry policy may reconsider a proven CAS refusal against a new
snapshot, but must never retry an unknown append or unwitnessed durable commit
as though it were uncommitted. Projection sync is explicit postcommit work and
must retain the transfer receipt if it fails.

Initial acceptance uses temporary source/receiver ledgers: exact prefix byte
identity, append during export, foreign admission signatures, divergent IDs,
mixed source groups, stale target CAS, postcommit projection failure and
unknown durability. Capability refusal must precede mutations. Keep the
legacy migration reader/codecs within the sidecar boundary when deleting the
old SQLite merge/transport and suffix-dispatch arms.
