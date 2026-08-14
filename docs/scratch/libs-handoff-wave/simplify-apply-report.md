# libs-handoff simplify-apply report

Branch: `fix/libs-handoff-simplify` (reset onto libs-handoff-wave HEAD `86e2aaf5`).
Suites at end, all green: engine 1464p/1s, lang 574p/3s, store 113p,
loops 2522p/1xf, root tests/ 59p. (Note: `uv run --package engine pytest
libs/engine/tests` fails 4 test_topology tests pre-existing on the wave —
they import the loops app, absent from the engine-package env; the root-env
run passes.)

| # | Item | Status | Commit |
|---|------|--------|--------|
| 1 | Write-surface into probe | **applied** — `canonical_writable` = full surface (canonical + index writable-or-creatable + dir for WAL/SHM) via new public `probe.write_surface_reason`; `ceremony._backend_not_writable` deleted; plan's dead conjunct + unreachable fallback deleted; new probe tests incl. read-only-dir vertex case | `a305cc2e` |
| 2 | Index-rebuild into store open | **applied** — `JsonlStore.__init__` catches `sqlite3.Error`, discards index + sidecars, rebuilds from log (re-raises on locked-error and on missing log — never destroys a live or sole artifact); preflight's discard/retry + `index_rebuilt` dissolve (`recovered = not report.ok`); flat `sqlite3.Error → unreadable` arm kept for double-failure; new tests: corrupt-.db-with-intact-log via direct open / `open_canonical_store` / `ensure_index`, no-log refusal, AUDIT_THEN_OPEN-still-refuses pin | `54b994a0` |
| 3 | Preflight `_result` factory | **applied** — 12 constructions → one factory; `agreed=report.ok` convention in docstring (:253 hardcode was value-identical drift); `post_report` rides only recovered results (sanctioned behavior change) | `a47c72c3` |
| 4 | Ceremony apply dedup + single open | **applied** — edit-mode currency pre-check deleted (CAS is sole staleness authority); one absorb call site with per-mode `stale_exc`/`refuse_exc`/stale-format tables; ONE `(sqlite3.Error, OSError)` needs-recovery arm; store opens ONCE before `_write_intent` (open failure = refused, zero residue — R2-04 two-scope floor preserved; mid-absorb = needs-recovery, intent left) | `9e959a75` |
| 5 | Delete `_reject_shared_line` | **applied** — parser oracle (`_verified`) is the sole detector; split-each-kind hint folded into the kind-set violation message; one test re-pinned from the old guard's message to preserved-or-refused | `99524e50` |
| 6 | Kind-subtree helper | **applied** — `engine/sql_util.kind_subtree_predicate` (LIKE/GLOB rationale in docstring once); 4 sites migrated (store_reader:2, vertex_reader, store/slice) | `f18d742e` |
| 7 | `sqlite_sidecars` in residence | **applied** — returns `(-wal, -shm)` only; migrated store/jsonl.py `_remove_partial`, store/compact.py `_total_size`, and item 2's rebuild uses it | `4ccf36a5` |
| 8 | Drop `signature_present` | **applied** — both attestation dataclasses keep `signed` only; tests updated; no CLI change (CLI reads `signed`) | `3bab390a` |
| 9 | `deserialize_row` over `deserialize_records` | **applied** — records + refuse-if-multiple, same message/exception; one dispatch. Minor precedence note: a *malformed* batch line now raises its structural error instead of the refusal message (no test pinned it) | `f7eb9042` |
| 10 | Plan single-resolve | **partial** — one store handle spans `declaration_head` + `resolve_declaration_documents` in the edit branch. The `load_declaration_status` dedupe is unreachable ceremony-side: `declaration_generation` resolves internally and declaration.py is off-limits by ruling — skipped with reason | `eb11f180` |
| 11 | Attestation from the write's own result | **applied** — `append_attested` / `append_tick_attested` return the committed row's signature directly (P1 "write operation's actual result" clause); per-emit SELECT and per-tick PRAGMA+SELECT gone from the receipt path; `fact_signature`/`tick_signature_state` kept as public read-back (and Vertex getattr fallback keeps EventStore/FileStore tri-state None); ticks PRAGMA probe cached (`_ticks_have_chain_columns`, adopts `_chain_ready`). Two handle tests re-pointed their failure monkeypatch at the attested seam | `4d6ae48e` |
| 12 | `_validate_batch` split | **applied** — `validate_rows=` flag: structural half always; per-row `_validate` only on deserialize (serialize rows just left `_encode_obj`) | `30308497` |
| 13 | One-liner sweep | **applied** — `q=_q` alias dropped; `_BARE_NAME_CHARS` module-level frozenset; one-element tuple fell with item 3; "recover double open" was the preflight discard/retry pair, dissolved by item 2 (ceremony.recover's store-open + resolve-read has no seam without touching declaration.py — not changed) | `c41925b8` |
