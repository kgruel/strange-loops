# sdk-search — Fable review

Effort: low. Finished: 2026-09-06T02:57:30.080502+00:00.
Packet SHA-256: `3e5bb6a30abbd44e97d3d559f406a9387fac49e53e030b4d7f03f15aa7ec0e5e`.

Static reviewer output; findings still require primary triage.

**No blocking findings.** Implemented behavior matches the stated design on the core invariants: the FTS corpus is built through an attested H under `BEGIN IMMEDIATE`, reads run coverage check and MATCH in one read transaction, P>H is clamped and refused unless coverage is exactly H, reads never reach maintenance, and `ranking_through` is forced equal to `basis.captured_head`. Four non-blocking findings follow.

**1. Medium: pre-mutation refusals are reported as "projection-unknown".**
Location: `libs/engine/src/engine/arrival_search.py`, the `except Exception` in `sync_search_index`; `libs/sdk/src/sdk/errors.py` maps `SearchIndexSyncError` to `ProjectionOutcomeUnknown`.
Trigger: once `target` is set, every exception is wrapped, including `query.open_snapshot(...)` raising `ProjectionBehind`/`ProjectionAbsent`, `registry._search_maintenance_for` raising `NotSupported`, and `build` refusing with `ProjectionBehind`/`HeadMismatch` before any DDL.
Consequence: a clean, nothing-written refusal surfaces to SDK and CLI as outcome `projection-unknown` with "reconcile derived state" semantics. Operators get told to reconcile an index that was never touched. The cause type is preserved in `details.source_type`, so it is recoverable, but the outcome classification is wrong. Wrapping should start only after `maintenance.build` has been entered, or the wrapper should classify `ContractRefusal` causes raised before build as refusals.

**2. Medium: `changed` is always true and every successful sync invalidates all fact continuations.**
Location: `FileSearchMaintenance.build` in `arrival_file_backend.py`, `changed=before != after`; `SearchCoverage` includes `schema_version`.
Trigger: rebuild at the same head and same spec. `DROP`/`CREATE` always bump `PRAGMA schema_version`, so `after.schema_version != before.schema_version` and `changed` is true. The coordinator never short-circuits when existing coverage already equals `(target, fields_hash)`.
Consequence: `SearchIndexResult.changed` carries no information, and an idempotent `search-sync` bumps `view_generation`, refusing every outstanding fact `Continuation` for a corpus that did not change. Compare `changed` on `(through, fields_hash)` only, or skip the rebuild when coverage already matches and is schema-valid.

**3. Medium (design divergence, unverifiable from snapshot): the pin check the design requires is not on the search path.**
Location: `derive_search_spec` in `arrival_search.py` docstring says "pin-checked"; `_arrival_search_spec` in `sdk/read.py` passes `target_path.parent` as `ingress_dir` to `collect_search_fields`. No call to `verify_source_pins_from_documents` appears anywhere in the supplied files, and `compiler.collect_search_fields` is not supplied.
Trigger: a declaration whose searchable fields derive from template/parameter files in the locator directory, after those files drift from their pinned digests.
Consequence: if `collect_search_fields` reads live files, the `fields_hash` on both build and read sides is derived from unpinned locator-directory content, contradicting the design's "never silently replaced by the live locator content." If fields are purely AST-declared today, this is a dead parameter and a misleading docstring. Either way the claim should be made true or removed.

**4. Low: maintenance-side coverage ignores the schema token the read side enforces.**
Location: `FileSearchMaintenance._coverage` vs `_FileQuerySnapshot._search_coverage`.
Trigger: a base-schema migration or any DDL after a build.
Consequence: `coverage_before`/`observed_after` in `SearchIndexResult` and `SearchIndexSyncError` can report coverage that `search` will refuse as "schema-invalid". Diagnostic evidence and read behavior disagree. Apply the same `schema_version` comparison in `_coverage`, or report validity explicitly.

**Noted, not findings:** `search` uses exact `observer` match while `facts` accepts suffix match (documented as exact, acceptable); `_AbsentFileQuerySnapshot.search` raises `NotSupported` rather than `SearchStale` but is unreachable from `search_facts` since it opens CURRENT; descriptors with `role=None` are readable but refused by `sync_search_index` with `NotAuthority`, consistent with the registry's stated transitional stance. Final legacy cutover and empty-receiver import are out of scope here and nothing in this stage depends on them.
