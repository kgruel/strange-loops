# strange-loops

Task orchestration built on loops. Harness-agnostic, loops-first.

## What This Is

An orchestration system where tasks are loops. Facts flow in (task events),
fold (accumulate state per task), boundary fires (task complete), tick comes
out. The vertex IS the task registry. The store IS the task database.

Workers run in git worktrees. The harness is pluggable — Claude Code, Codex,
shell scripts, whatever produces facts. Painted renders everything.

## Build & Test

```bash
./dev check            # lint + test (CI gate)
./dev test             # pytest only
./dev lint             # ty + ruff
./dev fmt              # auto-format
```

Or via uv from monorepo root:

```bash
uv run --package strange-loops pytest apps/strange-loops/tests
```

## Structure

```
src/strange_loops/
  cli.py              # Thin dispatcher
  commands/           # Subcommand implementations
tests/
  conftest.py         # Shared fixtures (home, workspace)
  test_smoke.py       # Import + entry point smoke test
scripts/
  lib/dev.sh          # Shared helpers (logging, paths, run_uv)
  check.sh            # CI gate: lint → test
  lint.sh             # ty + ruff
  test.sh             # pytest passthrough
  fmt.sh              # ruff format
```

## Dependencies

- `atoms`, `engine`, `lang` — loops monorepo libs (workspace)
- `painted` — terminal rendering (path dep to ~/Code/painted)

## Conventions

- CLI is thin dispatcher. Logic lives in `commands/` submodules.
- Tests mirror src structure. Factories over mocks.
- `./dev check` must pass before commit.
- Harness implementations are pluggable — implement the interface, not the backend.
- Tasks are facts. State is fold. Completion is tick.

## Key Concepts

| Concept | Loops Equivalent |
|---------|-----------------|
| Task | Loop in a vertex |
| Task state | Fold over task facts |
| Task complete | Boundary → Tick |
| Worker | Source (harness-specific .loop) |
| Task registry | Vertex + SqliteStore |
| Progress | Facts (queryable) |
| Stage | Fact kind with status payload |
