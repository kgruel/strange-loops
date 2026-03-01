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
  cli.py              # Thin dispatcher — argparse, lazy imports, note command
  store.py            # Shared store helpers (observer, emit_fact, require_store)
  worktree.py         # Git worktree operations (create, remove, list, diff)
  harness.py          # Shell harness runner (spawn detached, capture output as facts)
  lifecycle.py        # Query-time fold — compiled vertex spec for task state
  commands/
    session.py        # Session lifecycle (start, end, status, log)
    task.py           # Task lifecycle (create, assign, send, run, status, list, diff, merge, close)
    dashboard.py      # Dashboard — fetch/render/fetch_stream wired through painted run_cli
    project.py        # Project coordination (emit, status, log)
tests/
  conftest.py         # Shared fixtures (home, workspace, git_repo)
  test_smoke.py       # Import + entry point smoke test
  test_store.py       # Store helpers
  test_session.py     # Session commands
  test_task.py        # Task commands end to end
  test_dashboard.py   # Dashboard helpers + CLI integration
  test_project.py     # Project commands
  test_snapshots.py   # Golden-file tests (text output) + direct assertions (JSON output)
  test_worktree.py    # Git worktree operations against real repos
  test_harness.py     # Harness runner
  test_lifecycle.py   # Vertex spec compilation + fold
  snapshots/          # Golden files for text CLI output (visual rendering only)
docs/
  CLI.md              # Auto-generated from argparse (run scripts/gen_cli_docs.py)
scripts/
  gen_cli_docs.py     # Generate docs/CLI.md from argparse definitions
  lib/dev.sh          # Shared helpers (logging, paths, run_uv)
  check.sh            # CI gate: lint → test
  lint.sh             # ty + ruff
  test.sh             # pytest passthrough
  fmt.sh              # ruff format
```

## Dependencies

- `atoms`, `engine`, `lang` — loops monorepo libs (workspace)
- `painted` — terminal rendering (path dep to ~/Code/painted)

## Session Narration

No HANDOFF.md or LOG.md for this project. The project loop is the
continuity mechanism. The session log is the handoff.

**During work — emit notes as you go:**

```bash
strange-loops note "observation about X" --observer claude
```

Notes are `session.note` facts in the task store. They show up in
`session log` and filter with `--kind session.note`.

**For durable decisions, threads, plans:**

```bash
strange-loops project emit decision topic=X "rationale for choosing Y"
strange-loops project emit thread name=X status=open "what we're investigating"
strange-loops project emit thread name=X status=resolved "outcome"
strange-loops project emit plan name=X status=next "what we're doing next"
```

**At session boundaries:**

```bash
strange-loops project status        # review decisions, open threads, plans
strange-loops session log --since 1h  # review recent activity
```

The project vertex carries forward across sessions. `project status` is
the first thing to read when resuming work.

**This applies to workers too.** Workers running in subtask worktrees share
the same CLAUDE.md. Emit notes for significant observations. Use project
emit for decisions that affect the broader project.

## Conventions

- CLI is thin dispatcher. Logic lives in `commands/` submodules.
- `note` is inline in cli.py — too small for its own module.
- Dashboard delegates to painted `run_cli` (bypasses argparse for mode/zoom).
- Tests mirror src structure. Factories over mocks.
- `./dev check` must pass before commit.
- Snapshot tests: text goldens for visual output, direct assertions for JSON.
  Run `--update-goldens` to regenerate text snapshots after intentional changes.
- Regenerate CLI.md after argparse changes: `uv run --package strange-loops python scripts/gen_cli_docs.py`
- Harness implementations are pluggable — implement the interface, not the backend.
- Tasks are facts. State is fold. Completion is tick.

## Patterns

### Command shape

Every command follows: require store → fold state → validate → act → emit fact → render.
This is the skeleton for all task commands. Session commands use the same shape minus fold.

### Query-time fold

State is derived at read time via compiled vertex spec:
pull all facts → filter by task name → apply spec fold → derive state.
`fold_task_state()` and `fold_all_tasks()` in lifecycle.py.

### Store sharing

Two stores, two concerns:
- `./data/tasks.db` — session + task + worker facts (the task loop)
- `./data/project.db` — decision + thread + plan facts (the project loop)

Kind prefix (`session.`, `task.`, `worker.`) is the namespace within the task store.
`session log --kind worker.output` queries across concerns.

### Async worker model

`task send` / `task run` spawns a detached process (`start_new_session=True`)
and returns immediately. The harness process writes to the same SQLite store
in WAL mode. No IPC, no sockets — shared store is the coordination channel.

### Running a task end to end

```bash
# One-shot: create + assign worktree + spawn harness
strange-loops task run tui-design \
  --title "Design TUI layout" \
  --harness sonnet \
  --description "Research painted primitives and design a persistent dashboard TUI"

# Watch live (polls every 2s, Ctrl-C to stop)
strange-loops task log tui-design --follow

# Review what the worker produced
strange-loops task diff tui-design

# Merge, then close
strange-loops task merge tui-design
strange-loops task close tui-design
```

Available harnesses (in `loops/harnesses/`):
- `shell` — runs `{{command}}` raw. Use with `task send`.
- `sonnet` — `claude -p` with sonnet, 25 turns, text output. Use with `task run`.
- `codex`, `gemini-flash` — same pattern, different models.

Mechanics: harness captures worker stdout line-by-line as `worker.output`
facts. On exit, emits `worker.output.complete` + `task.stage` + `task.tick`.
Worker runs in a git worktree at `.worktrees/<name>/` (full monorepo copy).

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
| Session note | Fact with kind session.note |
| Project decision | Fact with kind decision, grouped by topic |

## CLI Reference

See `docs/CLI.md` for the full auto-generated reference. Key commands:

```bash
# Session
strange-loops session start [--observer NAME]
strange-loops session end [--observer NAME]
strange-loops session status [--json]
strange-loops session log [--since 7d] [--kind KIND] [--json]

# Notes
strange-loops note "message" [--observer NAME]

# Task lifecycle
strange-loops task create NAME [--title T] [--base BRANCH] [--description D]
strange-loops task assign NAME [--harness shell]
strange-loops task send NAME "shell command"
strange-loops task run NAME --description "prompt" [--harness shell] [--title T] [--base B]
strange-loops task status [NAME] [--json]
strange-loops task list [--json]
strange-loops task log NAME [--since 7d] [--kind KIND] [--json] [--follow]
strange-loops task diff NAME
strange-loops task merge NAME [--force]
strange-loops task close NAME
strange-loops task stop NAME [--observer NAME]

# Dashboard
strange-loops dashboard [--live] [-q] [--json]

# Project
strange-loops project emit KIND [KEY=VALUE...] [message]
strange-loops project status [--json]
strange-loops project log [--since 7d] [--kind KIND] [--json]
```

## What's NOT built yet

- Harness visibility is final-output only — `claude -p --output-format text` shows result, not intermediate research
- No TUI Surface — static painted blocks + live repaint only
- No automatic stage advancement — explicit CLI commands
- No peer-to-peer worker communication — hub-and-spoke only
