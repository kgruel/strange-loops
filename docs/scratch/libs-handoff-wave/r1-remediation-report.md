# R1 remediation report — libs-handoff wave

Branch `fix/libs-handoff-r1` off `libs-handoff-wave` (5a9d1829). Every fix
carries a regression test observed FAILING against the pre-fix source
(verified by stashing `src/` and re-running) and one commit per finding.

| Finding | Commit | Disposition | Evidence |
|---|---|---|---|
| SOL-R1-01 (blocker) — single-line loops expansion leaves siblings sharing a line; later edit/remove silently deletes them | 26611005 | FIXED | Root cause: `kdl_insert_child` single-line expansion now splits every top-level child onto its own line via `kdl_split_top_level_nodes` (quote-, escape-, and brace-aware; handles both `;` and `}`-boundary separation). Fail-loud per arbiter ruling: `edit_vertex_kind`/`remove_vertex_kind` refuse with ValueError when the kind's physical line carries sibling nodes. Tests: add→edit→remove on a multi-child single-line block preserves all unrelated kinds; hand-authored shared lines refuse on both verbs. 4 tests failed pre-fix (edit/remove silently dropped `task`), pass post-fix. |
| SOL-R1-02 — kind filter uses SQLite LIKE (`_`/`%` wildcards, ASCII case-insensitive) | f9728a94 | FIXED | All three kind-filter sites converted to exact equality OR `substr(kind, 1, length(?) + 1) = ? \|\| '.'`: `store_reader.query_facts`, `store_reader.facts_between`, and the sibling combined-vertex UNION ALL path in `vertex_reader._combined_facts` (same bug, same finding). Tests: underscore, percent, case-distinction leaks on all three paths — 5 failed pre-fix, pass post-fix. Docstring claims updated to match. |
| SOL-R1-03 — RECOVER_THEN_OPEN leaks raw JsonlCodecError on canonical corruption | dd1e5b4b | FIXED | `_recover_then_open` converts `(JsonlCodecError, UnicodeDecodeError)` and `OSError` into typed PreflightResult `status="unreadable"` (closed vocabulary kept — corruption recovery cannot fix means the canonical artifact cannot be read), pre-recovery audit report attached, opened/recovered False, no store handle. Tests: newline-terminated corrupt suffix, invalid UTF-8, unknown discriminator — 3 failed pre-fix (raw JsonlCodecError escaped), pass post-fix. |
| SOL-R1-04 — plan applicability uses vertex-file writability; apply raises raw OperationalError AFTER creating an intent | 05c8323c | FIXED | `TargetInfo` gains `canonical_writable: bool \| None` (None iff `canonical_path` is None); `writable` keeps its existing probed-path meaning, both docstrings state the split, all 8 construction sites + `as_dict` updated — every existing probe test stays meaningful. `plan_declaration_update` applicability = vertex-file writable AND canonical-store writable, with its own reason string when the store is the blocker. `apply_declaration_update` gates on canonical-artifact writability BEFORE intent creation (and before the edit-mode currency pre-check whose store open can itself fail raw) → typed `refused`, zero intent residue. Tests (both backends, chmod 0444 on the canonical artifact): plan not applicable; forced apply (preview.applicable overridden) → typed refusal, no intent file. 4 failed pre-fix, pass post-fix. |
| SOL-R1-05 — LoopDef serializer rejects valid parse pipelines vs its round-trip claim | ceb0f02e | FIXED (contract narrowed, per arbiter ruling) | No serializer widening (zero corpus usage; scope-the-claim). Module + `loop_def_to_kdl` docstrings now enumerate the supported domain (fold/boundary/search/preview/edge/lifecycle), scope the reparse-equivalence claim to that domain, and state the parse-pipeline ValueError as documented contract — no full-LoopDef round-trip claimed anywhere (grep of src/docs clean). The refusal message names the narrowed contract. Test pins the refusal AS contract (message wording + docstring claims); failed pre-fix on the old message, passes post-fix. |

## Suite results (post-remediation)

| Suite | Result |
|---|---|
| `uv run --package lang pytest libs/lang/tests` | 562 passed, 3 skipped |
| `uv run pytest libs/engine/tests` | 1451 passed, 1 skipped |
| `uv run --package loops pytest apps/loops/tests` | 2522 passed, 1 xfailed |
| `uv run pytest tests/` | 59 passed |

Note for verifiers: the prescribed form `uv run --package engine pytest
libs/engine/tests` shows 4 `test_topology.py::TestTopologyCacheResolution`
failures that are an environment artifact — those tests import
`loops.main`, which is absent from the engine-only package env. The
workspace-env run (`uv run pytest libs/engine/tests`, above) is the one
that must pass, and does.

No arbiter-stops: all five findings fit inside their remediation fences.
