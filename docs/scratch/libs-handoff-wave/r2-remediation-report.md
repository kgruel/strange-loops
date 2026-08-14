# R2 remediation report — fix/libs-handoff-r2

Branch: `fix/libs-handoff-r2` off `libs-handoff-wave` (769adf2b, the sol r2
stdout commit). One commit per finding; every regression test verified
failing pre-fix by stash-mutation of the implementation file(s).

## Disposition table

| Finding | Severity | Disposition | Fix | Commit | Regression tests (failing pre-fix) |
|---|---|---|---|---|---|
| SOL-R2-01 raw strings evade splitter + guard → silent sibling deletion | blocker | **fixed (arbiter ruling: construction over detection)** | The PARSER is now the safety oracle: `add/edit/remove_vertex_kind` parse before mutation, re-parse after, and admit only the exact requested delta — kind-set delta, definition-equality (`__eq__` on the frozen AST) of every untouched kind, and equality of all non-kind vertex fields. Any mismatch raises `ValueError` naming the preserved-content violation; the original text is never replaced. The lexical splitter/shared-line guard remain best-effort transformation with no safety claim. Sibling loss is inexpressible regardless of lexical evasion class. | `fix(lang): SOL-R2-01` | `TestParserOraclePostcondition` in `libs/lang/tests/test_vertex_mutation.py`: sol's exact `##"…"##` repro (add→edit→remove sequence, `test_full_sequence_never_loses_task`), escaped-quote variant, comment-on-shared-line variant, non-kind-content refusal. Each op must fully preserve or refuse cleanly. |
| SOL-R2-02 fourth LIKE site in `store/slice.py` | major | **fixed** | Same binary equality/`substr` prefix predicate as the three engine sites (`(kind = ? OR substr(kind, 1, length(?) + 1) = ? \|\| '.')`, three params per kind). | `fix(store): SOL-R2-02` | `test_kind_filter_is_not_a_like_pattern` (`a_b` no longer matches `axb.child`/`a%b.child`), `test_kind_filter_is_case_sensitive` (`A_B.child` excluded) in `libs/store/tests/test_slice.py`. |
| SOL-R2-03 RTO leaks raw `sqlite3.DatabaseError` on corrupt derived index | major | **fixed** | `_recover_then_open` catches `sqlite3.Error` on the open; the index is DERIVED and the log valid, so recovery deletes the index (+ `-wal`/`-shm`) and retries the open, rebuilding from the log — `status="recovered"`, `recovered=True` (forced, independent of pre-audit verdict), both reports attached. If the rebuild open also fails: typed `"unreadable"` with the pre-recovery report. jsonl-canonical branch only; the log is never touched. | `fix(engine): SOL-R2-03` | `test_recover_then_open_rebuilds_a_non_sqlite_index` (non-sqlite bytes; rebuilt counts asserted), `test_recover_then_open_rebuilds_a_truncated_sqlite_header` in `libs/engine/tests/test_probe_preflight.py`. |
| SOL-R2-04 JSONL applicability probes only the log; ro store dir → raw `OperationalError` + intent residue | major | **fixed** | New `_backend_not_writable(canonical)`: canonical file + derived index (`index_path_for`, creatable-via-writable-ancestor counts) + containing directory (sqlite WAL/SHM siblings). Used by plan's applicability and apply's pre-intent gate. Race floor, two scopes with different guarantees: an expected `sqlite3.Error`/`OSError` at the post-intent OPEN provably mutated nothing (no log byte) → typed `"refused"` + `_remove_intent`, zero residue; a failure DURING `absorb_genesis`/`absorb_edit` is ambiguous on a JSONL-canonical store (log line commits before the index row) → intent LEFT in place, typed `"needs-recovery"` — `recover_declaration_update` classifies not-applied vs applied from the log with existing machinery. Catch scope ends at the receipt; the file step stays `needs-recovery` as before. | `fix(engine): SOL-R2-04` | `test_plan_on_readonly_store_dir_is_not_applicable`, `test_forced_apply_on_readonly_store_dir_is_typed_with_no_intent` (sol's repro shape: store in own subdir, dir ro, canonical writable) on both backends, in `libs/engine/tests/test_ceremony_orchestration.py`. |
| SOL-R2-05 single-line expansion eats trailing comment after block close | minor | **fixed (per sol's direction)** | The closing line preserves the complete suffix after the matching `}`. A mislocated close from a raw-string lexical gap is caught by the R2-01 parser oracle; the splice stays best-effort. | `fix(lang): SOL-R2-05` | `test_single_line_expansion_preserves_trailing_comment` pins `// keep this loops comment`. |
| SOL-R2-06 test docstring still claims "every feature the grammar carries" | minor | **fixed** | Narrowed to "every supported declarative feature (fold/boundary/search/preview/edge/lifecycle)"; parse pipelines named as outside the domain by contract. | `docs(lang): SOL-R2-06` | n/a (doc sweep). |

No finding required judgment beyond the fences; nothing routed to needs-arbiter.

## Behavior deltas worth knowing

- `edit_vertex_kind`/`remove_vertex_kind` now require the INPUT text to
  parse (they previously only parsed the output). Unparseable input refuses
  with `"input is not a parseable vertex"` — one existing test asserted the
  old `"single-line"` message on a fixture that is actually invalid KDL
  (`decision { } task { }` without `;`); updated to expect the parse
  refusal, with a parseable variant still pinning the no-kind-loss refusal.
- `PreflightResult.recovered` is now also True when the pre-audit could not
  see the damage class (index unreadable as sqlite) but a rebuild ran.

## Suite results (post-fix)

| Suite | Command | Result |
|---|---|---|
| lang | `uv run --package lang pytest libs/lang/tests` | 574 passed, 3 skipped |
| engine | `uv run --package engine pytest libs/engine/tests` | 1457 passed, 1 skipped |
| store | `uv run --package store pytest libs/store/tests` | 113 passed |
| loops | `uv run --package loops pytest apps/loops/tests` | 2522 passed, 1 xfailed |
| root | `uv run pytest tests` | 59 passed |

Baseline note (lang): sol's r2 log reports "Lang: 1501 passed, 69 skipped";
this environment yields 574/3 for every selection tried (`--package lang`
and workspace env, `libs/lang` and `libs/lang/tests`). Engine (+6) and
store (+2) reconcile exactly against sol's numbers after the new tests, so
the lang delta is a counting/selection difference on sol's side, not a
shrunk suite — flagged rather than silently tabled.

Note: the workspace-env form `uv run pytest libs/engine/tests` shows 29
failures in `test_behavior`/`test_integration`/`test_store`/`test_tick`
(Stream/Projection/FileWriter legacy surface) — untouched by this branch's
diff and environmental (the inverse of the known `--package` import
artifact); the package-env run above is clean. Flagging for the wave lead
rather than chasing here.
