# S6 impl report — lang public KDL vertex-kind mutation API

Branch: `slice/s6-lang-kdl-mutation` (off `libs-handoff-wave` a39028e8)
Worktree: `/Users/kaygee/Code/loops/.claude/worktrees/agent-a226f27a6d92fd349`

## What was built

New module `libs/lang/src/lang/vertex_mutation.py`, exported from `lang`
(`__all__` + `_LAZY_IMPORTS`):

- `add_vertex_kind(text, kind, definition: LoopDef) -> str` — inserts via
  `kdl_insert_child(["loops"], ...)`; creates a multiline `loops { }` block
  appended at end of file when absent; refuses duplicates.
- `edit_vertex_kind(text, kind, definition) -> str` — in-place replacement of
  the kind's line span (position + surrounding content preserved).
- `remove_vertex_kind(text, kind) -> str` — via `kdl_remove_child`.
- `loop_def_to_kdl(kind, definition, indent="  ") -> str` — supported
  serializer over the lang loader grammar only (no engine imports; DAG safe):
  all 9 fold ops, all 3 boundary forms (match pairs, conditions, run), search,
  preview, edge, lifecycle.

All three mutations parse + validate (`parse_vertex` + `validate_vertex`) the
result before returning, wrapping failures as `ValueError` (e.g. removing the
last kind of a loops-only vertex refuses).

## Representability rules (reject over escape)

- Kind names: conservative bare-identifier subset (letters/digits/`_.-`, no
  leading digit/`.`/`-`); `boundary` reserved (loops-block sibling vocabulary).
- String values: KDL-quoted with `\\` and `\"` escaping; control chars /
  newlines rejected (cannot survive the line-based splice layer).
- Lifecycle `active` values containing commas rejected (loader splits on `,`
  — cannot round-trip).
- Per-kind `parse` pipelines rejected by the serializer with a clear error
  (zero corpus usage; authored by hand).
- Boundary condition values: floats emitted as numbers (`.0` dropped when
  integral), strings quoted — matches the loader's float-coercion so
  post-parse defs round-trip to equality.

## Documented one-way limitation (expand-on-insert)

Adding into a single-line `loops { ... }` block expands it across lines
(semantically equivalent, not byte-identical). Edit/remove inside a
single-line loops block is unsupported — surfaced as a clear `ValueError`
naming the limitation.

## Oracle results

`libs/lang/tests/test_vertex_mutation.py` (30 tests + 2 corpus
parametrizations over every in-repo `.vertex`, 15 files in this worktree):

- `test_corpus_add_remove_roundtrip` — add-then-remove is **byte-identical**
  to the original for every file with a multiline `loops` block; single-line
  or absent blocks assert semantic equivalence (one-way expansion/creation).
- `test_corpus_serializer_reparse_equivalence` — `loop_def_to_kdl` output
  reparses to `==` the original `LoopDef` for **every kind definition in the
  corpus** (25 kinds across 15 files).

Full suite: `uv run --package lang pytest libs/lang/tests` → **557 passed,
3 skipped** (3 skips pre-existing). Repo-root `tests/` (architecture DAG):
59 passed. Pre-existing splice suite untouched and green.

## Deviations

- The prompt's "53-file corpus" count reflects the main checkout with local
  `.loops` state; this worktree's corpus is the 15 tracked `.vertex` files —
  same test shape (rglob), environment-dependent count.
- No `./dev` script exists in `libs/lang`; gate approximated with the
  project-config ruff (new files clean; 102 pre-existing violations in the
  lib left untouched) + full pytest.
