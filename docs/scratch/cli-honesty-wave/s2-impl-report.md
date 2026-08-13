# S2 impl report — exit-discipline family

Slice: cli-honesty-wave S2 (design:implementation/cli-honesty-wave, ratified)
Branch: worktree off `cli-honesty-wave`
Commits: `2b3e837` (c), `548bbc2` (a + b + tests), report commit follows.

## What changed

### (a) `ls` unknown vertex — friction:ls-vertex-not-found-exits-zero

`sl ls projcets` now exits **1** (read's unresolvable-vertex code) with the
error on **stderr**, plus did-you-mean:

```
vertex not found: projcets
Did you mean: projects, project?
Known vertices: cli-completion, comms, ..., tasked, tasks
```

(Plain multi-line `print` to stderr, exactly like read's validator —
painted's `Block.text` flattens newlines, so `_err` would have collapsed
the three-line shape into one run-on line. Other ls error dicts keep the
single-line `Error: ...` painted render on stderr.)

- `_unknown_vertex_message(name)` added in `commands/resolve.py` — the
  vertex-name sibling of `_validate_kind_or_exit`'s kind treatment (same
  three-line shape: miss / close matches / full list). Candidates come from
  the existing `enumerate_vertices()` — reused, not re-detected.
- Both ls entry paths covered: the listing (`_run_ls`) and the kind descent
  (`_run_kind_stat`).

### (b) `ls --kind bogus` — friction:ls-kind-flag-no-validation

`sl ls tasked --kind bogus-kind` now runs **read's validator verbatim**
(`commands.resolve._validate_kind_or_exit`): exit **2**, stderr,
did-you-mean, declared-kinds list. No 0-entries render.

- Descent path (`_run_kind_stat`): the validator call is gated on
  `count == 0 and not entries`. Rationale (documented in a comment at the
  call site): ls lists **live undeclared** kinds (`tick.*`, `_sync.*`) as
  containment rows — an unconditional declared-kinds check would refuse
  descent into rows ls itself just listed. Read has no live listing, hence
  the extra gate here only. Declared-but-empty kinds pass the validator
  silently (kind IS declared) and keep the honest 0-entries render — same
  stance as read.
- Composed path (`_run_ls` with `--kind X --observer ...`, which bypasses
  the descent): the narrow is validated against the merged (declared ∪
  live) kind set the listing itself shows, deferring to the same validator
  on a miss.

### Mechanism (both a and b)

`_run_ls` / `_run_kind_stat` now fetch **up-front**; an error dict routes
through the new `_exit_on_fetch_error` (stderr + exit 1, did-you-mean
variant when `missing_vertex` is stamped on the dict), and `run_cli`
renders the precomputed data (`fetch=lambda: data`). The fetch functions
keep returning error dicts unchanged for direct data-API callers (existing
`test_ls_unified` fetch/lens tests untouched and passing);
`fetch_kind_stat` additionally returns `vertex_path` (needed by the
validator).

### (c) reindex hint — friction:reindex-hint-omits-vertex-target

`lenses/fold.py` `_render_search` footer now renders
`` `sl store reindex <vertex>` `` using `data.vertex` (the Surface it is
rendering inside). Bare-form prose reference in the docstring updated too.
No golden pinned the old text.

## Exit-code mapping (deliberate, matches read)

| Error | Code | Precedent |
|---|---|---|
| unknown vertex | 1 | read's unresolvable-vertex path (`cli/views/fold.py` run(): exit 1) |
| undeclared kind | 2 | read's `_validate_kind_or_exit` (`sys.exit(2)`) |
| other fetch errors (parse failure, aggregation no-store, `--key` on collect-fold) | 1 | generic error class, non-negotiable clause |

The 1-vs-2 asymmetry is inherited from read, not invented here.
`_validate_kind_or_exit`'s `sys.exit(2)` is propagated, not caught —
behavior-preserving reuse.

## Files touched

- `apps/loops/src/loops/commands/ls.py` — up-front fetch, `_exit_on_fetch_error`,
  kind validation on both paths, `missing_vertex`/`vertex_path` keys
- `apps/loops/src/loops/commands/resolve.py` — `_unknown_vertex_message`
- `apps/loops/src/loops/lenses/fold.py` — vertex-named reindex hint
- `apps/loops/tests/test_ls_exit_discipline.py` — new, 8 tests pinning all
  three fixes + valid-invocation exit 0
- `apps/loops/tests/test_ls_flag_grammar.py` — re-pinned
  `test_unknown_name_renders_empty` → `test_unknown_name_exits_2_like_read`

## Test evidence

- `uv run --package loops pytest apps/loops/tests` — **2450 passed, 1 xfailed**
- `./dev check` (repo root; apps/loops has no ./dev script) — 59 passed
- Live exercise via the worktree build (`uv run --package loops loops ...` —
  NOT `sl`, which resolves to the stale global install; verified with
  `command -v` inside the env per the arbiter correction):
  - `loops ls projcets` → exit 1, stdout empty, stderr carries
    not-found + did-you-mean + known-vertices
  - `loops ls tasked --kind bogus-kind` → exit 2, stdout empty, stderr
    carries read's exact validator message
  - `loops ls tasked --kind task` → exit 0, normal render

## Deviations

None from the contract. Two contract-driven consequences worth naming
(not deviations — mandated by the NON-NEGOTIABLE "every error path exits
nonzero with the error on stderr"):

1. ls's non-vertex/kind error dicts (vertex parse failure, aggregation
   with no own store, `--key` on a collect-fold) also flipped from
   stdout-render-at-0 to stderr + exit 1.
2. `test_ls_flag_grammar.py::test_unknown_name_renders_empty` pinned the
   overturned behavior and was re-pinned to the new contract (its old
   docstring claimed read-consistency, which now means exit 2).

Read's own unknown-vertex phrasing ("No vertex resolved — run `loops
init` first.") was left untouched — the contract's parity direction is
ls ← read; upgrading read's message with the shared did-you-mean helper
is a natural follow-up, out of S2 scope.
