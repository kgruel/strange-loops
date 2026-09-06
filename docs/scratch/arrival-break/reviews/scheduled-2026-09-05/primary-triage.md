> September 6 update: the three unfinished reviews are now complete. See
> `../fable-followup-2026-09-06/primary-triage.md` for current triage and new
> reproduced follow-ups. The queue/status described below is historical.

> Historical pre-fix assessment. The subsequent implementation and current
> validation are recorded in `../../correctness-pass-2026-09-05.md`.

# Primary triage of the completed Fable reviews

Ten of thirteen static reviews completed: restore-forward at high effort,
then nine at low. Forty-six numbered observations are not forty-six proven
bugs: several are contract choices, duplicate concerns, or gaps in the source
packet. Verification/pagination, custody observer guard and export remain
unreviewed. No additional model calls were made for this triage.

This pass read all completed findings, checked important dependencies in the
current source, and reproduced five failures on disposable file-backed stores
with isolated witness directories. No production implementation was changed.
The reproduction scripts and exact output are retained in `triage-evidence/`.

## Reproduced correctness failures

| Finding | Observed result | Primary judgment |
| --- | --- | --- |
| Restore-forward F1 | Receiver has a projection from a fork, then its ledger is truncated to the common prefix. Restore installs the exact source log successfully, but SDK facts still return `forked-fact` under the source head. Explicit sync also leaves the forked row visible when both records have equal encoded length. | Blocker, stronger than Fable's Medium/no-blocking verdict. Custody and reported read evidence disagree. |
| Declaration F1 | Inject failure after the declaration append, then call public `sdk.recover_declaration`. Cache publication succeeds and intent is removed, but SDK raises `AttributeError: DeclarationEditResult has no attribute basis`. | Confirmed public API blocker. Engine recovery success is lost during result adaptation. |
| Aggregate F1 | Store has one fact and a plain adopted declaration. Add discover only to the local locator. SDK summary changes from one fact to zero, state becomes count zero, ledger still contains the fact. | Confirmed correctness blocker. Local/effective shape disagreement silently hides observations. |
| Runtime capture F1 | Commit a pending vertex-level close tick, sync, and capture again without new facts. The same vertex boundary is pending again. | Confirmed source-mode blocker. Re-emission can also repeat the associated run clause. |
| Runtime capture F2 | Change derived own-lineage marker and genesis row ID to a foreign identity. Ordinary `open_read` refuses `NotAuthority`; runtime source capture accepts it and a boundary-only batch commits a tick (head 2 to 3). | Confirmed missing authority guard on this path. Trigger requires damaged/misbound derived declaration evidence. |

Primary source locations:

- `libs/engine/src/engine/arrival_restore.py`: `_restore_forward` judges the
  receiver projection against the proposed selected head.
- `libs/sdk/src/sdk/declare.py`: `_arrival_result` and `recover_declaration`.
- `libs/engine/src/engine/arrival_aggregate.py`: `capture_aggregate` omits a
  descriptor root when its effective declaration has no discover.
- `libs/engine/src/engine/vertex.py`: `plan_pending_boundaries` includes the
  boundary fact at the recorded tick timestamp for vertex-level boundaries.
- `libs/engine/src/engine/runtime_write.py`: `capture_runtime` goes directly
  through registry/query; `_build_effective_arrival_candidate` does not apply
  the declaration-anchor guard that `plan_ordinary_write` applies. The read
  consumer has its own guard, so its tests do not protect runtime capture.

## Findings that should not become automatic fixes

- **Source execution F2: dismissed.** `_toposort_tiers` in `executor.py`
  explicitly returns `sorted(tier)`. The review lacked that helper.
- **Search F3: dismissed as stated.** `_arrival_search_spec` calls
  `effective_declaration_from_documents`, whose default `verify_pins=True`
  invokes `verify_source_pins_from_documents` before collecting fields.
- **Runtime capture F5: existing contract already handles this.**
  `_HeadObservation._judge` raises the refusal for rollback/fork/rewrite before
  returning a successful Compared result. Duplicating this classifier into
  callers would not address a demonstrated gap.
- **Inspection F5: dismissed as stated.** `_arrival_declaration` explicitly
  refuses an effective aggregate unless `allow_aggregate=True`; inspection
  does not pass that override. The review did not see this dependency.
- **Aggregate F3: semantics mostly already chosen.** Legacy `vertex_read`
  overwrites own-declared kinds with own-store folds, including empty state.
  Current capture distinguishes all observed facts from those selected for a
  fold. The orchestration checkpoint records this decision. The handoff is
  stale and should be reconciled; this is not an invitation to change overlays
  into unions or collapse member occurrences by lineage.
- **Inspection F1 and SDK-source F1:** these posit nonconforming adapters or
  an append raising a commit-less NotWitnessed. Ordinary attested append
  supplies its actual Commit on witness failure. These deserve conformance
  and defensive classification review, not a claim of an observed normal-path
  failure.

## Secondary findings, not all reproduced yet

| Review | Remaining assessment |
| --- | --- |
| Restore-forward | Source opening advances the shared lineage witness even if receiver preflight later refuses. That follows current observation semantics and needs explicit documentation. The optional through head cannot select history below the source capture; clarify whether it is an expected source head. The mismatched-lineage refusal type differs from ordinary open. |
| Initializer | Pre-mint failures can retain a reserved intent; reservation races can expose raw FileExistsError. Recovery's witness level and reporting of a head advanced by another writer need careful evidence semantics. Do not equate a reserved signature alone with proof of a durable mint. |
| Declaration | Recovery after a competing append retains the intent despite evidence the planned CAS did not land; clearing it must also prove cache/publication-artifact conditions. Pre-append intent diagnostics omit recovery identity. CRLF cache reads normalize bytes before an exact-byte comparison. ProjectionBehind wrapping loses refusal specificity. |
| Aggregate | Storeless leaf treatment needs distinction from explicit storeless composition. A detachment failure can leak an opened resource; rereading the locator around reused root capture can mismatch definition evidence. |
| Runtime capture | Some planning exceptions lose item identity, and pending tick ID collision checking differs from ordinary tick planning. Synthetic planning coordinates are not actual ledger receipt coordinates. |
| Source engine | Post-collector metadata/clock failures may escape structured collection evidence. Retained fully duplicate tiers can meet a commit assertion. Dispatch after unwitnessed/projection-failed commits and stale-head handling need explicit operational semantics. No automatic recollection should be inferred from a safe refusal. |
| SDK source | Refused/failed classification, preparation evidence, tier-level dispatch receipts and SDK coverage gaps need follow-up. Several items are diagnostics or coverage concerns rather than independently established data loss. |
| SDK batch | Signature-inclusive duplicate identity, duplicate-item signed status, empty Replica batches and first-row envelope timestamps are small API/contract questions. No ordinary/batch CAS or signer-domain regression was established by this review. |
| Search | Pre-build refusals can be labeled projection-unknown. Rebuilding identical coverage changes schema generation and invalidates continuations; current changed=true reports that actual rebuild, but idempotence may be preferable. Maintenance coverage does not enforce the read-side schema-validity check. |
| Inspection | Source-pin fingerprints are recomputed from live files on both ASTs; unlike search, this path uses documents_to_vertex directly. Pin drift reporting needs a dedicated repro. Malformed declaration rows/error normalization and the always-empty cadence_ticks field need checking. |

## What the evidence says about the architecture

The reviews support substantial parts of the intended design: exact-head CAS,
separate signing domains, deterministic tier execution, immutable capture,
per-occurrence aggregate bases, and explicit unknown/committed outcomes.
That support is bounded static review evidence, not blanket acceptance.

The reproduced failures concentrate where boundaries differ: SDK versus engine
result models, local versus adopted declaration topology, vertex versus loop
boundary replay, and custody versus derived projection identity. Fixing those
requires making the shared guarantees apply consistently at supported entry
points. None of these reproductions by itself demonstrates that the observer/
event model or backend-neutral SDK direction is unworkable.

The next-step decision remains with this discussion. This triage adds no new
implementation stage, accepts no review wholesale, and leaves all five
reproduced failures open.
