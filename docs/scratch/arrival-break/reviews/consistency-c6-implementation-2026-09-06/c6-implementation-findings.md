# c6-implementation — Fable review

Effort: low. Finished: 2026-09-06T21:35:39.245540+00:00.
Packet SHA-256: `790d16340d92c25d5d394db28c1539178fd234d66fe96e48ef225fd31d1ceacc`.

Static reviewer output; findings still require primary triage.

**Verdict: ACCEPT.** I read the frozen module, all three call sites, the compiler parser change, and the engine/SDK tests. I found no mismatch with the selected contract and no defect that changes runtime behavior in a way the design forbids. Blockers: none. Notes below, ordered by how much I would want them checked before merge.

## Contract points verified in code

- **Full history, intermediate revisions.** `declaration_document_revisions` folds every own-lineage overlay in `(ordinal, seq)` order and snapshots the namespace after each ordinal group (`arrival_boundary_continuity.py:217-240`). Same-ordinal retire+redefine is one revision (`test_atomic_declaration_group_does_not_expose_transient_retirement`); retirement at a distinct ordinal followed by re-add is caught as `prior-incarnation` even when the final document equals the genesis document.
- **Every relevant tick, not the newest edge.** `analyze_boundary_continuity:525` iterates all owned ticks; the earlier-interval test proves an unknown revision between two ticks refuses the earlier one and passes once only later ticks remain.
- **Vertex identity scope.** Loop ticks require `namespaces[i].vertex_name == target` over `[start, end]` (`:595-607`); vertex-period ticks check the same plus loop-absent at receipt (`:527-572`).
- **Pre-genesis / negative time.** Ticks below genesis ordinal get `start=None` and refuse only if consumed (`:587-594`, `:528-535`); pre-genesis own overlays are skipped at `:206-209`. Both call sites request `since=-inf` for continuity while hydration keeps `TickRequest()` (`runtime_write.py:810-811`, `:854`).
- **Implicit cite.** `_namespace` seeds `{"cite"}` (`:319`); runtime compiled set adds `"cite"` (`:831`), matching `materialize_vertex:1024`.
- **Consumer gating.** Vertex-name tick without target boundary is skipped (`:578-582`); with boundary, rechecked. SDK test exercises repair-then-readd on a real store.
- **Three-valued names.** Direct/literal presence is added independently of `unknown` (`:335-355`); `membership` returns unknown only when not present and a generator is unresolved.
- **Same-read hashing.** `collect_verified_parameter_rows` hashes `data` then parses the same `data` (`:295-298`). `parse_source_params_bytes` uses `TextIOWrapper` with default encoding/newline, the in-memory equivalent of `read_text()`; `_load_params_file` delegates to it so the compiler and collector share one grammar. `$$`/whole-value `$NAME` handling in `_literal_kind` matches `_resolve_param_indirection`.
- **Both directions.** `missing` always refuses; `extra` refuses unless an unknown generator exists (`:454-469`).
- **Refusal before effects.** Runtime: analyzer runs after `compile_sources` (parse only, no execution) and before `materialize_vertex`/`hydrate_snapshot`/pending planning; the capture test asserts no hydration call and identical log bytes. Preparation: analyzer runs before `ledger.scan`/key registry/signers; test asserts `activity` has no `scan`. Preview: before returning `applicable=True`.
- **Evidence.** `BoundaryContinuityRefused` carries `basis`, `captured_head`, effective declaration, scalar `tick_id`/`ordinal`/`fact_id`/`vertex`, phase `prepare`, custody `not-entered`. Preparation and preview raise `DeclarationPreparationRefused ... from conflict`; `_cause_details` serializes the conflict's scalars. No new error schema.
- **Declaration fact identity in a mixed revision.** `_revision_fact_id` matches on `(kind, subject)` for loops and on kind for vertex, returns `None` when no single row is causal. The observer/loop same-subject test proves the fix.
- **Existing scope.** Reads, export, CAS/recovery, legacy replay untouched. `capture_runtime` now reuses the builder's `facts`/`runtime_ticks` instead of re-querying, both from the same snapshot.

## Notes (non-blocking)

1. **MEDIUM, verification gap, not a found defect.** `_namespace` reads inline template params as `payload["params"][i]["values"]` (`:341-343`). The engine tests construct that shape by hand; the SDK integration test covers only `from file`. If `vertex_to_documents` serializes inline rows differently, literal inline generated names would be silently dropped, and runtime would refuse every inline-param template loop with `runtime-namespace-mismatch` (`unproved`). One real-store SDK case with an inline `params` row and a tick would close this. The design explicitly requires "literal inline parameter rows ... can establish generated names".

2. **LOW.** Vertex documents are keyed by `(kind, subject)` and `_namespace` takes the last vertex document in insertion order. `DECL_VERTEX_DEFINED` has no tombstone (`_DEFINED_KINDS` adds it outside `DEFINED_TO_TOMBSTONE`), so if a rename ever changed the document subject, a later rename-back would update the earlier map slot and the stale second document would win. The tests use a fixed subject with a changing `name`, which suggests subject is stable; if so this is moot.

3. **LOW.** `_namespace` raises `DeclarationResolutionError` for a vertex document lacking `name`. At runtime this escapes `_build_effective_arrival_candidate` outside the `RuntimeWriteRefused` family, and in preparation it is wrapped as "cannot establish declaration preparation basis". Any pre-existing store whose genesis vertex document has no `name` would now refuse capture entirely. That matches the "malformed evidence refuses" rule but is a compatibility effect worth stating in the summary.

4. **LOW.** The continuity reconstruction deliberately skips own-lineage overlays with ordinal below genesis, while `resolve_declaration_documents_from_snapshot` does not (`declaration.py:261-275`). When such a row exists, the runtime target differs from `revisions[-1]` and is appended as a `proposed` revision with ordinal `None`. Behavior stays conservative (names from that overlay are never provably present historically), but the two definitions of "own history" diverge, contrary to the design's preference for one shared definition.

5. **LOW, cost.** `declaration_document_revisions` runs twice per call site (collector and analyzer) and deep-copies every document per revision. Accepted by the summary's no-performance-claim statement.

6. **INFO.** A negative-timestamp owned tick passes continuity but is excluded from hydration and pending planning by the preserved `since=0` selection, so an `after` loop with only such a tick is re-derived from fact counts. This is the documented preserved policy, not a defect.
