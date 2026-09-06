# Runtime proposal: Fable 5.1 review

Static review of the write-stage proposal plus arrival_body.py, admission.py
and arrival_file_backend.py. Requested `claude-fable-5-1[1m]`; modelUsage
confirms `claude-fable-5-1` with auxiliary CLI Haiku usage. No tools.

## Reviewer response

**Verdict: revise.** The custody boundary, pre-append refusal, and single-append tick bundling are sound. Four issues need a rule decision before 3A code starts; the rest are wording or gating fixes.

**1. Fresh-write outer signature rule is asserted, not sourced — High**
Step 4 says ordinary facts are "unsigned at that layer under the current rules," generalizing from admission. But admission's `_draft_for` leaves `RecordDraft.signature` None specifically because "the target's operator holds no key for a foreign observer"; it says nothing about local authorship. `arrival_body._refuse_mixed_observers` states the opposite premise: the envelope observer "selects the key that signs an outer commitment covering every row." `FileLedger.append` forwards `draft.signature` verbatim, so whatever rule exists lives in `ArrivalLog.append_marked_many` (not supplied). Correction: cite the per-kind outer-signature wire rule from `arrival.py`, split the table into "new local authorship" and "admitted foreign row," and make test 1 assert outer-signature presence or absence explicitly. Preserving source signatures on transfer must not be the reason fresh facts drop a required signature.

**2. Mixed-observer drafts depend on finding 1 — Medium**
The doc correctly avoids a blanket ban: `FileLedger.append` commits any draft sequence atomically. But if outer signatures are observer-keyed, a mixed-observer SDK call requires the writer to hold a signing key per observer, or to leave some drafts unsigned while others are signed. Either way, "emit a sequence of separate drafts" is under-specified. Correction: state which key signs each draft's outer envelope and what happens when the writer lacks one (refuse before append, not sign as someone else).

**3. Fresh tick drafts inherit admission's chain-nulling — Medium-High**
Step 5 requires ticks to "omit/null source-local chain fields." In admission that is justified because a foreign tick's `prev_hash`/`window_hash` reference the source chain, and the codec then reads it as "the pre-chain era shape, honestly claimed." A locally generated tick has no foreign chain; nulling its fields makes every new tick claim pre-chain era and drops the tick signature the chain fields anchor. The live tick mint site (`ArrivalStore._custodian`, `_store_tick`) is not supplied, so this may be a misreading of "current wire rules." Correction: distinguish "admitted tick: chain nulled" from "locally minted tick: chain fields per the live mint rule," and have test 3 assert the actual expected chain state rather than absence.

**4. Fold state and CAS head can come from different points — High**
Step 2 reads a projection snapshot and the ledger head as two operations. `_FileQuerySnapshot` accepts a watermark behind `captured_head` when the requirement is not CURRENT and silently clamps. A writer that folds against a behind projection while pinning CAS to the newer head will commit a fact and tick decision computed from stale state, and the CAS will pass. Correction: writes open the snapshot with `ProjectionRequirement.CURRENT`, or replay the ledger records between watermark and head into candidate state before folding. Test 2 should include "projection behind head" as a refusal case.

**5. Declaration anchor for writes read from the projection — Medium-High**
`_read_declaration_anchor` returns `own_lineage` set with `genesis=None` when the row is missing, and never compares `own_lineage` to `captured_head.lineage`. `_AbsentFileQuerySnapshot` returns an empty anchor. In fresh init, config facts follow the declaration genesis before any projection exists, so step 2's "resolve the anchor" cannot come from the projection at all. Correction: the writer resolves the anchor from the committed ledger prefix (or a CURRENT snapshot), and refuses when `genesis is None` or `own_lineage != head.lineage`. This is the concrete check behind the root invariant; the table's "refuse without mutation" currently has no defined trigger.

**6. Batch bodies cannot interleave a mid-batch tick — Medium**
3B proposes grouping same-observer items into one `body_of_batch`. A boundary fired by item i needs a tick record between row i and row i+1, but `rows_of_body` expands a batch as one contiguous record; the tick can only precede or follow the whole batch. Reconstruction would then see the tick's `since`/state at a different position than the fold computed. Also `body_of_batch` needs two or more rows, so a split can leave a single-row remainder that must become a fact draft (admission already handles this in `_drafts_for`). Correction: either split batch bodies at every boundary, or rule that all ticks trail the append and replay tolerates that; state the choice and pin it in test 5.

**7. Refusal typing and journal claims over-promise — Low**
`FileLedger.append` maps only `StaleHead` to `HeadMismatch`; the parent `AppendRejected` (placement faults) propagates as a backend exception. The invariants table lists only typed refusals. Separately, test 2 requires "no new append journal entry" while acknowledging open-time attestation may write one; that distinction is asserted in prose but the seam's journal shape is not supplied. Correction: add `AppendRejected` to the pre-durability refusal set, and have test 2 diff the journal against a post-open baseline rather than asserting emptiness.

**8. "No SqliteStore import" is not achievable via admission reuse; binding test is misgated — Low**
`_verify_admitted_rows` imports `sqlite_store.FACT_COLUMN_INDEX`, so a planner that reuses `admission.py` transitively imports the legacy store; the import-spy in test 1 will fail or be watered down. Correction: move that constant to `jsonl_codec` or spy on `SqliteStore` mutation methods, not the import. Also, acceptance test 8 (binding identity) is listed in the 3A set while the doc assigns that work separately. Its only dependency implication for 3A is that reconciliation keys on `Commit.after` plus record IDs, not on the binding key, so 3A is unaffected; drop test 8 from the 3A gate.

**Limitations.** `arrival.py`, `arrival_head_seam.py`, `arrival_contract.py`, `declaration.py`, `vertex.py`, and the SDK emit path were not supplied. Findings 1, 3, and 7 therefore flag source insufficiency rather than a confirmed defect; findings 4, 5, 6, and 8 are grounded in the supplied backend, body, and admission code. Nothing here reviews the read-snapshot implementation beyond how the writer would consume it.

## Primary judgment

Revise before runtime implementation. Transfer/admission rules must not be
generalized to fresh local authorship. Source checks after review confirm
ArrivalStore._write supplies an outer fact signer, body_of_tick_row retains
chain/signature fields, and Vertex._store_tick enforces the live tick-signing
floor. The write planner must preserve those fresh-write semantics while
keeping foreign admission rules distinct. Exact signing primitives require
an implementation-owner source pass before extraction.

Writes require CURRENT state at their CAS basis. Batches preserve event/tick
interleaving by splitting fact groups at boundaries within one append.
Declaration anchor licensing follows physical Arrival lineage. Refusal tests
use a post-open attestation baseline; opening can independently earn a
journal entry. Binding identity has its own stage and test gate.

Sol will source-check the signing/chain extraction after the SDK handoff.
