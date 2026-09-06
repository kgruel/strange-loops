# Transfer boundary findings

Status: reproduced during primary's exact-transfer integration. Export and
explicit restore-forward are implemented and locally validated. Empty receiver
import remains design work;
this note supersedes the assumed creation path in the earlier transfer handoff.

## Older exact copies and witness comparison

`BackendRegistry.open` constructs `AttestedLedger`, whose `_observe` reads
the journal by physical lineage. Opening the source first records its newest
head. Opening an exact older receiver then raises `HeadRollback`, even when
its entire prefix agrees with the source. The implementation must not hide
this by changing witness namespaces, lowering the witness, bypassing the
registry, or treating a rollback as first contact.

The witness protocol comparison table says to refuse authority and restore
forward; its failure table permits restoring from a verified copy. The
current opener provides no constrained restoration capability. Its returned
ordinary handle would also allow Authority append, so making its refusal
conditional on a loose flag would weaken the existing boundary.

Recommended next design: an explicit restore-forward operation, separate from
ordinary opening. It receives an independently attested source prefix,
verifies exact receiver membership, and can append only the exact suffix
through the selected source head. The selected head must satisfy the current
witness and trust-reset fences. It must preserve the current witness and
refuse changed lineage, fork, unanswerable comparison and stale receiver CAS.
Its resource cannot be reused as an ordinary append-capable handle. A known
commit is witnessed before success; unknown outcomes retain both heads and
exact reconciliation identity. The user approved the explicit
restoration surface. It is now implemented as the registry-owned procedure
documented in `restore-forward-stage-2026-09-05.md`; ordinary opening retains
its rollback refusal.

## Empty receiver bootstrap is not blind replication

`FileLedger.replicate` delegates to `ArrivalLog.append_records`, which obtains
an existing verified head. `expected=None` is a blind-head append request,
not an exclusive create request. A new receiver raises `GenesisRefused`.
The prototype coordinator's contrary assumption failed a real temporary-file
test and has been removed from supported source.

The adapter's existing `import_prefix` first calls `ArrivalLog.adopt_genesis`
and then replicates the suffix. That method is intentionally not reachable
through `AttestedLedger`; its genesis adoption is not witnessed there and
can leave a genesis-only copy if later replication fails. Calling it directly
from the SDK would bypass precisely the boundary this work is establishing.
Calling `mint` with source material would also misdescribe creation and can
lose carried extension fields; fabricating a pre-genesis `Head` in `Commit`
would contradict the receipt model.

The next import design therefore needs to name the exact-genesis installation
and its receipt/recovery boundary explicitly. It should reuse the file
adapter's exclusive staging machinery, preserve all original record bytes,
and establish witness evidence for the exact installed head. Keep the backend
contract's distinction between import procedure and ledger operation visible;
do not silently change `replicate(None, ...)` or grant Authority to a copied
Replica. General resumable import remains separate contract debt.

## File projection path collision corrected

The registry's file opener used `residence.index_path_for`, which returned
the original path for unrecognized suffixes. Consequently a valid Arrival
ledger named `ledger.db` or `ledger.odd` could be opened as its own SQLite
projection. New `file_projection_path` retains conventional `.arrival` and
`.jsonl` sibling naming and gives other file ledger spellings distinct
`.projection.db` sidecars. The file query, maintenance and search openers use
the same helper. Real initialization, summary and exact export now pass for
all three spellings and preserve the original ledger bytes.
