# final — Fable review

Effort: low. Finished: 2026-09-07T03:58:58.542231+00:00.
Packet SHA-256: `50cb3e69f5e351bc72414cf03edd76db6b66983045fd87fba015a36083742eac`.

Static reviewer output; findings still require primary triage.

**Verdict: ACCEPT** (no implementation blockers, no design blockers; observations below).

## Implementation blockers
None found. The five review targets hold:
- Lineage and authority role are published and re-parsed exactly (`sidecar.py:295-329`).
- Exact bytes are checked on entry (`:247`) and again after temp fsync, before replace (`:357`). Correctly described as non-atomic, quiescent-input checks.
- KDL quoting via `json.dumps(ensure_ascii=False)` plus control-char refusal (`:287-293`) covers `"` and `\`; test at `test_sidecar.py:613` exercises it.
- Preexisting explicit descriptors refuse before any target creation (`:759-779`); exact already-published resume skips the editor (`:1130-1142`) and is regression-tested with a patched editor (`test_sidecar.py:312-325`).
- Regression taxonomy after lineage pinning: `NotAuthority` maps to `TargetMismatchOnResumeRefused` on resume (`:863`) and `ReportHeadMismatchRefused` in the verifier (`:682`). The friendly-name test now hits the registry path first; the message still carries filename and lineage, so the assertion is honest. Tampered/torn-tail types are unchanged.

## Implementation observations (non-blocking)
1. **Already-published resume rewrites the report** (`sidecar.py:1105-1113`). README says it re-verifies "without replacing the descriptor" but the report is re-signed and atomically replaced, and a different `tool_version` argument changes the signed body. Trigger: re-run with a different `tool_version`. Consequence: audit artifact silently changes. Minimum correction: in the `already_published` branch, skip the rewrite when the existing report verifies at the same head, or state the rewrite in the README.
2. **Store-clause structure is validated only after staging.** Duplicate/commented-out/missing store nodes are detected in the editor (`:271-283`), after genesis, appends, and report exist. Minimum correction: dry-run `effective_store_clause` on the captured bytes before Stage 1. Cheap, and shrinks the documented post-staging-evidence case.
3. **Raw exceptions at parse edges.** `parse_vertex` at `:260` and `:757`, and `.decode("utf-8")` at `:757`, raise untyped errors instead of `PublishPreconditionRefused`. Pre-existing behavior, low impact.
4. **No upgrade path for descriptors written by the previous sidecar** (`backend="file"` without lineage/role). They now hit `vertex_already_descriptor_backed`. Correct per contract, but any real prior output needs a manual edit. Worth a README sentence.
5. **Report write lacks directory fsync** while the vertex write has one (`:363-367`). Inconsistent, not incorrect under the stated no-power-loss claim.
6. **API compatibility is honestly stated.** `edit_vertex_store_clause` gains two required keyword-only arguments; that breaks any direct external caller. The 9-test legacy CLI pass is consistent with the CLI only calling `run_migration`.

## Design (adoption) review
The identity decisions are sound: reviewed snapshot over locator fallback, fact-ID equals physical lineage, collision scan including historical `_decl.*` overlays, separate FACT/ARRIVAL signatures, immutable planned draft, legacy rows as prefix evidence, no automatic old-identity claim. No unsafe recommended operation.

Design observations:
1. **Key-introduction verification assumes ARRIVAL domain** (design §5). The sidecar `Signer` has no domain argument; only the test fixtures sign with `ARRIVAL_DOMAIN`. If a production wrapper signed under another domain, adoption would refuse every legitimate migration. Resolve the signer-contract decision before step 2, not as an open item after it.
2. **Report verifier will fail after adoption** (acknowledged). Consider a `through=S` prefix-verification mode so the report remains checkable post-adoption rather than only pre-adoption.
3. The "Current gap" line references (`sidecar.py#L647`, `#L209`) are baseline offsets and are already stale against this patch. Label them baseline or drop them.

## Evidence caveats
Test outputs and source hashes are packet evidence, not my executions. The "crash simulation" is an in-process patched `os.replace`, not a subprocess kill, as the report states. No real store touched.
