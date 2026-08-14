# R4 remediation report — libs-handoff wave

Branch `fix/libs-handoff-r4`, reset onto `libs-handoff-wave` HEAD (5a5dd262).
One commit per finding; every regression test verified red pre-fix, green post-fix.

## Disposition table

| Finding | Severity | Disposition | Commit | Fix |
|---|---|---|---|---|
| SOL-R4-01 | blocker | **fixed** (arbiter ruling: conservative refusal) | e8839257 | The scanner's PROVABLE DOMAIN is now explicit in the `vertex_mutation` module docstring: plain `"…"` KDL strings only. `add`/`edit`/`remove_vertex_kind` refuse with a typed, actionable ValueError ("…cannot prove safe to splice over…; edit the file by hand") when the vertex text contains `#"`, `"#`, or `"""`. Whole-text scan, not just the loops-block span — the span finder itself is raw-string-blind. No KDL lexer built. Corpus verification: **0 raw strings across all 15 `.vertex` files**; the repo's 10 raw-string hits are all `.loop` source lines (a different file type, outside the mutation domain). Parser oracle retained as in-domain backstop. |
| SOL-R4-02 | major | **fixed** | e6aa268b | `_committed_row_state` returns (exists, signature) separately; the write read-back raises typed `CommittedRowMissing` when the inserted id is ABSENT at pre-commit read-back, and `_write_fact_row`/`_write_tick_row` roll back before re-raising. Facts AND ticks, sqlite AND jsonl (jsonl's read-back precedes any log byte). `fact_signature`'s public None-for-unknown-id read contract unchanged. |
| SOL-R4-03 | major | **fixed** | 0663c705 | Jsonl `_write` reads back the COMPLETE inserted row (persisted column order) post-INSERT/pre-commit and serializes EXACTLY that row into the log — the index is what was committed; the log derive-matches it. Missing row → `CommittedRowMissing` refusal with zero log bytes (composes with R4-02). Codec pre-flight on the assembled row retained ahead of the INSERT so sqlite column affinity can't coerce a codec-invalid row (string ts) into something committable. |
| SOL-R4-04 | major | **fixed** | 3e5e6067 | Preflight's `_sqlite_busy` extracted to `sql_util.sqlite_busy` (one spelling: errorcode low byte 5/6, message fallback); preflight's local copy deleted, both JsonlStore destructive-recovery guards (initial open + under-lock recheck) rewired from the text-only `"database is locked"` match to the shared predicate. Authentic SQLITE_LOCKED now re-raises — no quarantine, same inode — and RECOVER_THEN_OPEN classifies it `refused`. |

## Regression tests (red pre-fix, green post-fix)

- `libs/lang/tests/test_vertex_mutation.py::TestScannerProvableDomain` — sol's two repros (raw string hiding a same-line duplicate `task`; `run #"echo " quoted"#` + `// KEEP`) now REFUSE for edit/remove, add's multiplicity precondition refuses too; no-raw-string happy path pinned unchanged.
- `libs/engine/tests/test_receipt_attestation.py::TestCommittedRowExistence` — delete-trigger repro, facts + ticks × sqlite + jsonl; log untouched on jsonl refusal; store usable after refusal.
- `libs/engine/tests/test_receipt_attestation.py::TestJsonlLogDerivesFromCommittedIndex` — signature-nulling trigger: log line carries no signature, `audit_agreement` passes; untriggered append still logs the signature.
- `libs/engine/tests/test_jsonl_store.py::TestRecoveryGuardsAreCodeAware` — injected authentic SQLITE_LOCKED (code 6, "database table is locked") at both guard sites: no quarantine, inode unchanged, error propagates; preflight RECOVER_THEN_OPEN → `refused`.

## Suites

| Suite | Result |
|---|---|
| engine | 1484 passed, 1 skipped, **4 failed — pre-existing** (`test_topology.py::TestTopologyCacheResolution`, reproduce on clean `libs-handoff-wave` HEAD via stash-check in this environment; unrelated to R4 files) |
| lang | 586 passed, 3 skipped |
| store | 113 passed |
| loops (CLI) | 2522 passed, 1 xfailed |
| root | 59 passed |

## Beyond-fence → needs-arbiter

- **Ceremony full-row derivation** (`_ceremony_persist`, jsonl_store): declaration-ceremony rows are read back for SIGNATURE equality only (R3-02 check in `absorb_genesis`/`absorb_edit`); a trigger that rewrites a non-signature field with the signature intact would still serialize the ASSEMBLED rows into the log — the same index/log divergence class as R4-03, on the ceremony path. Deleted ceremony rows ARE now caught (R4-02's raise fires inside the ceremony transaction). Not fixed here: sol's finding is scoped to `_write` (:527), and silently serializing a mutated declaration would also be wrong — the honest ceremony fix is refusal on ANY divergence, which is a contract call. **needs-arbiter**.
