# sdk-inspect — Fable review

Effort: low. Finished: 2026-09-06T02:59:04.028047+00:00.
Packet SHA-256: `8bd5aab16217b931b43086e073f356a0d8654d8c95975005e3fd72324ec612a7`.

Static reviewer output; findings still require primary triage.

No blocking findings. Five non-blocking findings follow, all scoped to the current Arrival inspection stage.

**1. Medium. `open_read` does not enforce `ProjectionRequirement` itself.**
Location: `libs/engine/src/engine/arrival_consumer.py`, `open_read`, the `watermark is None` and `else` branches.
Trigger: a registry adapter whose `open_snapshot` honours `requirement=CURRENT` loosely, returning `represented=None` or a watermark with `ordinal < captured.ordinal` without raising.
Consequence: the seam builds a `ReadBasis` with `projected_through=None` or a behind watermark and returns normally. `inspect_declaration` then folds declaration documents from an incomplete snapshot and reports `read_path="arrival"` with status `store`, and the CLI exits 0. The two supplied tests only prove the file adapter refuses (`ProjectionAbsent` / `ProjectionBehind`); nothing in the shared opener guarantees it for other backends. A one-line check (`requirement is CURRENT and (watermark is None or watermark.ordinal < captured.ordinal)` → refuse) would make the contract adapter-independent. Third-party adapters are not in this snapshot, so this is a contract gap, not observed misbehaviour.

**2. Low–Medium. `local_status` cannot register pinned-source drift.**
Location: `libs/sdk/src/sdk/declare.py`, `_document_fingerprint`; `libs/lang/src/lang/document.py`, `_content_sha256` inside `vertex_to_documents`.
Trigger: a `.loop` or template file referenced by a source-defined document changes on disk after genesis.
Consequence: both fingerprints are computed by re-decomposing an AST, so `content_sha256` and `params_sha256` are recomputed from current disk bytes on both the locator side and the effective side. The stored pin in the ledger is never compared. Inspection reports `matches-effective` while the effective declaration's pinned content no longer matches the file. Whether `_arrival_declaration` calls `effective_declaration_from_documents(verify_pins=True)` and raises `SourceDrift` is not visible in this snapshot. If it does, drift surfaces as an exception rather than in `local_status`, which is acceptable but should be stated in the result docstring. If it does not, inspection silently understates drift.

**3. Low. Malformed self-lineage overlay rows escape as internal errors, and inspection does not normalize.**
Location: `libs/engine/src/engine/declaration.py`, `resolve_declaration_documents_from_snapshot` overlay loop; `libs/sdk/src/sdk/declare.py`, `inspect_declaration` Arrival branch.
Trigger: a signed, self-lineage `_decl.kind-defined` row whose payload lacks `subject`, whose `payload` is not a dict, or whose fold op carries an unknown `op` tag.
Consequence: the fold inserts `docs[(kind, None)]`, and `documents_to_vertex` then produces `loops[None]`, or raises `AttributeError` / `ValueError` from `_loop_def_from_payload`. The edit and recover paths wrap engine exceptions in `normalize_exception`; the inspection path does not, so the SDK surfaces a raw `AttributeError`, and loops-min reports exit 70 (internal) instead of a typed refusal. The sqlite resolver (`resolve_declaration_documents`) has the same shape tolerance, so this is consistent legacy behaviour, but the Arrival snapshot fold is new code and could validate `subject: str` and `payload: dict` and raise `DeclarationResolutionError`.

**4. Low. `cadence_ticks` is dead on both paths.**
Location: `libs/sdk/src/sdk/declare.py`, `_inspection_fields`, `getattr(ast, "cadence", None)`.
Trigger: any inspection.
Consequence: `VertexFile` has no `cadence` field (see the explicit constructor list in `_reattach_ingress`), so the v2 schema always emits `cadence_ticks: []`. Consumers may read that as "no ticks declared". Either populate it from the real AST field or drop it from the v2 schema before the schema string is relied on.

**5. Low. Aggregate refusal is locator-only; effective state can still say aggregate.**
Location: `libs/sdk/src/sdk/target.py`, `_arrival_descriptor` (combine/discover check on the parsed file); `declare.py`, `_inspection_fields(effective_ast)` deriving `is_aggregate`.
Trigger: the effective document set carries `_decl.member-defined` rows or a `discover` value in the vertex-defined singleton, while the local locator file has been edited to drop them.
Consequence: the descriptor gate passes on the file, but the result reports `is_aggregate=True` with `read_path="arrival"`, contradicting the stated single-store scope. Inspection is read-only so nothing breaks, but the stage's "aggregates not implemented" guarantee is enforced against the wrong AST. Checking the effective AST as well, or reporting `local_status="drifted"` with an explicit aggregate caveat, would close it.

**Explicitly not findings.** `init` / `emit` / `declaration` returning `Unavailable` from loops-min is the deferred legacy cutover, not a defect. `restore_forward` as a separate procedure with ordinary opens keeping the `HeadRollback` refusal matches the approved design and the CLI test. `edit_declaration` / `recover_declaration` were not reviewed in depth; note only that `recover_declaration` passes `result` as both `plan` and `result` to `_arrival_result`, which requires the recovery result to expose `basis` and `changes`, neither of which is visible in this snapshot.
