# restore-forward — Fable review

Effort: high. Completed review preserved; no rerun.

Packet SHA-256: `aacc39766ed99fc9e5b27412b7e1927a748f18844615e674ef6875646e03b332`.

Static reviewer output; findings require primary triage. The CLI reported a small auxiliary Haiku call alongside substantive Fable output.

**Verdict: no blocking findings.** Implemented behavior refuses in the safe direction throughout; the four items below are one Medium evidence gap and three Low API/ordering concerns. Empty-receiver import and the legacy cutover are deferred by design and are not counted against this stage.

## 1. Receiver projection-ahead evidence is laundered when the watermark sits in (before, selected] — Medium

**Location:** `libs/engine/src/engine/arrival_restore.py:123-129` feeding `_HeadObservation._projection` in `arrival_head_seam.py` (the `watermark.ordinal > presented.ordinal` branch).

**Trigger:** The proof passes `selected` as the presented head, so the receiver's projection is judged against the *proposed* head rather than its *actual* head `before`. A receiver whose ledger was truncated to ordinal 2 while its projection still accounts for ordinal 5 (the seam's own definition of tail-truncation evidence) classifies BEHIND, not ProjectionAheadOfLedger. Ordinary open of the same receiver refuses.

**Consequence:** If the receiver's former records at 3..5 were a fork that was later truncated back to the shared prefix (which step `arrival_restore.py:107` cannot see, since it only checks the current head), replication installs the source's 3..5 beneath projected rows derived from different records. The post-commit ordinary open reads BEHIND and journals acceptance, so the state carries no refusal signal and the truncation evidence is erased by the ledger mutation. Later catch-up refuses only if the resume-mark byte offset happens not to land on a record boundary, and then as "not a verified log boundary" rather than as truncation. No engine or SDK test constructs a receiver projection in this range; `test_projection_evidence_beyond_selected_prefix_refuses` covers only `> selected`. Either refuse `watermark.ordinal > before.ordinal` in preflight (operator re-derives the projection first, consistent with "no projection repair") or record this as an accepted residual in the stage document.

## 2. `through` below the captured head can never succeed — Low

**Location:** `arrival_restore.py:93` and `:99`; `BackendRegistry.restore_forward` and `sdk.restore_forward` signatures.

**Trigger:** The source opens through ordinary attestation first. Source and receiver share one lineage-keyed journal, so that open establishes K ≥ captured before the proof runs. Any `through` with ordinal below captured then classifies ROLLBACK against K (`test_selected_head_below_witness_refuses_without_receiver_write` demonstrates exactly this, with `through=before`). `through` above captured refuses in `_verify_prefix`.

**Consequence:** The only accepted value is `selected == captured`, so "bounded" selection advertised by the parameter and the stage document is unreachable. Safe direction, but a documented capability that cannot be exercised will mislead the CLI cut when it grows a `--through` flag. Remove the parameter or document that it exists for a future reset-scoped epoch only.

## 3. A refused restore is not side-effect-free for the receiver's later opens — Low

**Location:** `arrival_restore.py:93` runs before every receiver check at `:101-115`.

**Trigger:** Receiver is the everyday local store journaled at K=3 and opening UNCHANGED. Operator runs restore-forward from a genuine descendant at 10. The source's attested open journals an ADVANCE to 10, then preflight refuses on the receiver (AtomicLimitExceeded, fork at `:107`, missing receiver).

**Consequence:** The receiver's next ordinary open refuses HeadRollback although nothing on it changed, and a receiver blocked by its atomic limit has no automated way forward except the ceremony. This is the lineage journal's documented semantics, so it is not a defect in ordinary open, but the stage document's "preflight writes no receiver acceptance" understates it. `test_forked_receiver_refuses` and `test_atomic_limit_refuses_without_chunking` assert receiver bytes only, not journal bytes, so the effect is untested. Document it, or defer the source open's write by opening the source through `_open_components` plus a pure observation and journaling the source only on success.

## 4. Lineage-mismatched receiver projection surfaces as HeadMismatch, not NotAuthority — Low

**Location:** `arrival_restore.py:77-80` (`_BoundedProof.head_at`) as called from `_projection`'s `watermark.lineage != presented.lineage` branch.

**Trigger:** Receiver's projection reports a different lineage than the receiver's ledger. The seam's comment expects the contract's NotAuthority from the adapter; the bounded proof raises HeadMismatch("restoration proof does not cover this watermark") first.

**Consequence:** Refusal direction is preserved and nothing is written, but the SDK `source_type` differs between ordinary open and restore-forward for the same store state, which weakens the "same comparison" claim in the stage document. Cosmetic unless a caller branches on the type.

## Confirmed sound

Rollback floor, same-height fork at `:107`, reset fences via `_BoundedProof.head_at` over the source, indeterminate journal raising strictly, torn or absent receiver refusing pre-mutation, CAS race to HeadMismatch, unknown versus committed-incomplete separation with exact heads, no-op retry after a lost receipt, and resource closure all hold against the supplied source. `except ContractRefusal: raise` correctly keeps `_DescriptorLedger` lineage refusals out of the unknown bucket.
