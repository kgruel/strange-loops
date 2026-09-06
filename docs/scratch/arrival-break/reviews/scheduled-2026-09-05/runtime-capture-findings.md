# runtime-capture — Fable review

Effort: low. Finished: 2026-09-06T02:49:24.523581+00:00.
Packet SHA-256: `d5dde56d39ed858ca47e680e6be0fa5ecf5ff89f9a7d530e308db174d3be1bc2`.

Static reviewer output; findings still require primary triage.

**Verdict:** one high-severity bug in implemented pending-boundary behavior; no blocking finding for the ordinary/batch write path. Findings 2–5 are gaps or verification items, not cutover/import deferrals.

**1. HIGH — Recorded vertex-level tick is re-emitted by every source-mode capture** (`libs/engine/src/engine/vertex.py`, `Vertex.plan_pending_boundaries`)

Trigger: a vertex-level boundary (e.g. `boundary when="close"`) has already fired and its tick is recorded at ts T, minted from the `close` fact at ts T (`_fire_vertex_boundary` uses `fact_ts`, so tick.ts == fact.ts). Then `capture_runtime(..., source_mode=True)`.

Mechanism: `hydrate_snapshot` restores `_vertex_period_start = T`; `since_ts = max(T, T)`; the fact filter is `since_ts <= fact.ts`, so the `close` fact at T is included. The exclusion `fact.ts > since_ts` is guarded by `not self._has_vertex_boundary`, so it does not run for vertex boundaries, and the planner has no equivalent of the 1 µs tolerance in legacy `_evaluate_vertex_only_boundaries`. `_match_vertex_boundary` then fires again.

Consequence: a duplicate vertex tick (and duplicate `run` clause) is planned on every source invocation until a newer fact moves the edge, contradicting "recorded ticks suppress re-emission." The tests cover only loop-level recorded ticks (`test_pending_boundary_precedes_items_and_recorded_tick_is_not_reemitted`) and a vertex boundary with no recorded tick. Mixed vertex+loop declarations inherit the same defect from legacy `evaluate_boundaries`, but the vertex-only case is a regression versus legacy. Blocking for source-mode acceptance; not for ordinary/batch writes.

**2. MEDIUM — Anchor-lineage authority check is skipped on boundary-only and retry paths** (`runtime_write.py`, `_build_effective_arrival_candidate` vs `plan_ordinary_write`)

The `NotAuthority` check that `anchor.own_lineage` and `anchor.genesis.id` equal `captured_head.lineage` lives only in `plan_ordinary_write`. `_build_effective_arrival_candidate` resolves declaration documents from the anchor without it. Two paths never reach `plan_ordinary_write`: `plan_batch_from_capture(items=(), include_pending_boundaries=True)` and the `_existing_fact_plan` duplicate short-circuit in `prepare_ordinary_write`/batch. `_ensure_current_basis` compares `snapshot.represented.lineage`, not the anchor.

Trigger: a projection index whose `own_lineage` marker/genesis belongs to another lineage (foreign or stale index behind an Authority ledger). Consequence: a pending tick is minted from a foreign declaration and committed under this ledger's head. Correction: move the anchor check into `_build_effective_arrival_candidate` (or `capture_runtime`).

**3. LOW — Non-typed planning exceptions escape the batch refusal contract** (`runtime_write.py`, `plan_batch_from_capture` item loop)

Only `AdmissionError`, `_AdmissionPlanRefused`, and `RuntimeWriteRefused` are wrapped in `BatchWritePreparationRefused`. `ReservedKindError` (a `_decl.*` fact, raised by `receive_receipt` when `_plan_only`) and any `RuntimeError` from `plan_receive_receipt` propagate raw, without `item_index`, basis, or the "no append attempted" evidence the docstring promises. Consequence: an SDK cannot attribute the refusal to an item or distinguish it from a capture failure. No custody effect.

**4. LOW — Pending tick draft omits the generated-id collision check** (`runtime_write.py`, `_pending_tick_draft`)

`plan_ordinary_write` refuses when a fresh ULID equals an existing tick id; `_pending_tick_draft` does not. Also, all pending ticks are given synthetic coordinate `(head+1, seq)` while item drafts get `head+1+len(logical)`; this is consistent for predecessor selection but is not the ordinal the ledger will assign, so nothing downstream may treat these synthetic coordinates as ledger truth. Cosmetic today; worth a shared helper so the two tick paths cannot drift.

**5. VERIFY (not a bug in this packet) — `Compared` outcome is not inspected**

`capture_runtime` and both `execute_*` accept any `Compared` and use `comparison.presented` as H without checking `comparison.outcome`. Rollback protection for ordinary opens therefore depends entirely on `arrival_head_seam` converting non-advancing/regressed outcomes into `Indeterminate`/`PreGenesis` refusals rather than returning `Compared`. That module is not in this snapshot, so I cannot confirm it. If the seam ever returns `Compared` for a detected regression, the CAS here would happily append onto a rolled-back head. Recommend an explicit assertion on the outcome enum at the capture boundary so the property is local rather than inherited.

**Noted, not counted against the limit**

- Signer domains are correctly separated: `fact_signer` → inner commitment, `arrival_signer` → outer fact/batch envelope, `tick_signer` → tick commitment; no fallback between them (`_pack_batch_drafts`, `plan_ordinary_write`, `_pending_tick_draft`). Tests confirm the fact signer does not sign the envelope.
- Held-head CAS is sound for the paths shown: `comparison.presented != plan.captured_head` pre-check plus `ledger.append(plan.captured_head, ...)`; `NotWitnessed`/`ContractRefusal` pass through, other exceptions become typed unknowns without retry.
- Capture immutability holds: public accessors deep-copy, templates are re-copied per plan, `_capture_locator_ingress` detaches locator env. The `object.__new__` construction leaves unlisted `VertexFile`/`InlineSource` slots unset; safe only while `_reattach_ingress` and `documents_to_vertex` touch just `sources_blocks`, `path`, `store*`. Any future consumer reading another slot of `capture._locator` will hit an `AttributeError`.
- Pending-tick payload folds facts that arrived after the boundary fact but before capture (legacy `evaluate_boundaries` parity), so it differs from a live fire. Pre-existing semantics, not a regression.
