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
  cli.py              # Thin dispatcher — argparse, lazy imports
  store.py            # Shared store helpers (observer, emit_fact, require_store)
  worktree.py         # Git worktree operations (create, remove, list, diff)
  harness.py          # Shell harness runner (spawn detached, capture output as facts)
  commands/
    session.py        # Session lifecycle (start, end, status, log)
    task.py           # Task lifecycle (create, assign, send, status, list, diff, merge, close)
tests/
  conftest.py         # Shared fixtures (home, workspace)
  test_smoke.py       # Import + entry point smoke test
  test_store.py       # Store helpers
  test_session.py     # Session commands (16 tests)
  test_task.py        # Task commands end to end (14 tests)
  test_worktree.py    # Git worktree operations against real repos (8 tests)
  test_harness.py     # Harness runner (5 tests)
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

## Patterns

### Command shape

Every command follows: require store → fold state → validate → act → emit fact → render.
This is the skeleton for all task commands. Session commands use the same shape minus fold.

### Query-time fold

No compile-time Spec/Vertex machinery yet. State is derived at read time:
pull all facts → filter by task name → group by kind → keep latest per kind.
`_task_state()` in task.py is the fold. Same pattern as loops session.

### Store sharing

One store (`./data/tasks.db`), one fact stream. Session facts and task facts
coexist. The kind prefix (`session.`, `task.`, `worker.`) is the namespace.
`session log --kind worker.output` queries across concerns.

### Async worker model

`task send` spawns a detached process (`start_new_session=True`) and returns
immediately. The harness process writes to the same SQLite store in WAL mode.
No IPC, no sockets — shared store is the coordination channel. PID liveness
checked via `os.kill(pid, 0)` at query time.

### Payload rendering

Log renderer iterates all payload keys (`k=v` pairs), not a hardcoded
whitelist. Observer shown when present. Chronological order (oldest first)
— the log reads as narrative.

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

## CLI Reference

```bash
# Session
strange-loops session start [--observer NAME]
strange-loops session end [--observer NAME]
strange-loops session status [--json]
strange-loops session log [--since 7d] [--kind KIND] [--json]

# Task lifecycle
strange-loops task create NAME [--title T] [--base BRANCH] [--description D]
strange-loops task assign NAME [--harness shell]
strange-loops task send NAME "shell command"
strange-loops task status [NAME] [--json]
strange-loops task list [--json]
strange-loops task diff NAME
strange-loops task merge NAME [--force]
strange-loops task close NAME
```

## What's NOT built yet

- No Claude/Codex harnesses — shell only (others are just different commands)
- No .vertex file — store path is a constant, fold is query-time
- No TUI Surface — static painted blocks only
- No automatic stage advancement — explicit CLI commands
- No peer-to-peer worker communication — hub-and-spoke only
- No `task.progress` facts — worker output is the progress for now
- Status doesn't auto-advance on worker.stopped — check `worker` field or advance manually
