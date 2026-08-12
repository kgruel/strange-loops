# R2 fix — bare `loops ls` error to stdout

Finding: `finding:chw-r2-bare-ls-error-to-stdout` (S2 gate).
Arbiter scope: route the message to stderr; nothing else.

## Diagnosis

With `LOOPS_HOME` pointing at a directory with no `.vertex` config root and
no local layer, `fetch()` inside `_run_ls_root`
(`apps/loops/src/loops/commands/population.py`) raises the
`FileNotFoundError` from `fetch_vertices` (`commands/vertices.py:299`). The
raise happens *inside* painted's `run_cli`, whose fetch-error path
(`CliRunner._emit_error`) prints error blocks to **stdout** by framework
design and returns 1. So the exit code was right and the stream was wrong —
and unfixable from inside `fetch()` (raising is the only refusal channel
fetch has, and it lands on stdout).

The finding's pointer at `resolve.py:1488` was a miss: that site routes
through `resolve._err`, which already defaults to `sys.stderr`. The stdout
print on this reproduction's path is painted's, not that line.

## Fix

Pre-flight the empty-home case in `_run_ls_root` before entering `run_cli`
— the same validate-then-refuse shape S2 used for `--kind`
(`_validate_kind_or_exit`): if the config root is missing AND the local
layer is empty (fetch's exact re-raise condition), print the byte-identical
message via `resolve._err` (stderr) and return 1. The `.exists()`
short-circuit keeps the normal path free of the extra local walk, and the
lazy fetch/completion paths are untouched.

## Reproduction

Before (wave tip, `LOOPS_HOME` at an empty dir):

```
$ loops ls --plain
EXIT=1
stdout: /…/r2fix-empty/.vertex not found. Run 'loops init' first.
stderr: (empty)
```

After:

```
$ loops ls --plain
EXIT=1
stdout: (empty)
stderr: /…/r2fix-empty/.vertex not found. Run 'loops init' first.
```

## Test

`TestBareLsEmptyHome::test_missing_root_exits_nonzero_with_stderr` appended
to `apps/loops/tests/test_ls_exit_discipline.py` — isolated `loops_home`
(no `.vertex` root), cwd pinned to an empty dir, asserts exit 1, empty
stdout, message on stderr.

Full suite: 2468 passed, 1 xfailed (baseline 2467 + the new test — no
collateral).

## Siblings (listed, not touched — per arbiter ruling)

- `commands/store.py:300` — `_resolve_store_target` raises the same
  message as `FileNotFoundError`; on bare `loops store` with no root it is
  raised inside `run_cli`'s `fetch()`, so it lands on painted's stdout
  fetch-error path — same defect class, different command path (not the
  shared read/emit path), left alone.
- `commands/emit.py:597` — `_say("No vertex found. …")` defaults to
  stderr (`out=False`); already correct.
- `commands/resolve.py:1488` — `_err` defaults to stderr; already correct
  (the finding's cited line, reported here as a miss).
