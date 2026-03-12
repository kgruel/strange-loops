# strange-loops — task orchestration

Tasks are loops. Workers run in worktrees. The store is the coordination channel. Start at Level 0. Only escalate when you hit a trigger.

**You are here** in the abstraction chain:

```
vertex store (state)  →  strange-loops (app)  →  engine (runtime)  →  atoms (data)
tasks.db, project.db     task create/send/merge   Vertex, Store        Fact, Spec
```

Below: `libs/engine/` provides SqliteStore and vertex fold. `libs/atoms/` defines facts. `libs/painted/` renders all display commands.

---

## Level 0 — Use it

**Trigger**: I need to orchestrate a task or check status.

```bash
# One-shot: create + assign worktree + spawn harness
strange-loops task run tui-design \
  --title "Design TUI layout" \
  --harness sonnet \
  --description "Research painted primitives and design a persistent dashboard TUI"

# Monitor
strange-loops task log tui-design --follow    # live tail (polls every 2s)
strange-loops task status                     # all tasks
strange-loops dashboard --live                # full dashboard

# Review and merge
strange-loops task diff tui-design            # what the worker changed
strange-loops task merge tui-design           # merge worktree into base
strange-loops task close tui-design           # cleanup

# Session
strange-loops session start
strange-loops note "observation about X" --observer claude
strange-loops session log --since 1h

# Project knowledge
strange-loops project emit decision topic=X "rationale"
strange-loops project status
```

Harnesses: `shell` (raw command), `sonnet` (Claude), `codex`, `gemini-flash`. Workers run in git worktrees at `.worktrees/<name>/`.

**Don't reach for yet**: Store internals, lifecycle fold, command implementation.

---

## Level 1 — Configure, don't code

**Trigger**: I need to adjust task behavior, add a harness, or change what data is tracked.

**Task state is derived from facts, not stored directly.** Before modifying app source, understand what's configurable:

- **Task lifecycle** — facts accumulate (`task.create`, `task.stage`, `worker.output`, `task.tick`). State is always fold-at-read-time, never pre-materialized. Changing lifecycle means changing what facts get emitted and how the spec folds them.
- **Harness configuration** — harnesses are shell commands with templates. Adding a new AI harness is a new entry in the harness registry, not a new command.
- **Project knowledge** — `project emit` and `session` commands use the same vertex/fold pattern as the loops CLI. Decisions, threads, plans fold by topic/name.

**Two stores, two concerns:**
- `./data/tasks.db` — session + task + worker facts (the task loop)
- `./data/project.db` — decision + thread + plan facts (the project loop)

Kind prefix (`session.`, `task.`, `worker.`) namespaces within the task store.

**Don't reach for yet**: Command implementation, lifecycle vertex spec, worktree internals.

---

## Level 2 — Understand the architecture

**Trigger**: I need to modify a command or understand the data model.

**Two command patterns** (same as loops CLI):

**Display commands** — fetch + lens + `run_cli`:
- `commands/*.py`: `fetch_*(sp, ...) -> dict` (data retrieval, no rendering)
- `lenses/*.py`: `*_view(data, zoom, width) -> Block` (pure function)
- `cli.py`: pre-dispatches display commands to `run_cli`

**Action commands** — require store → fold state → validate → act → emit fact → render.

**Key concept mapping:**

| Concept | Loops equivalent |
|---------|-----------------|
| Task | Loop in a vertex |
| Task state | Fold over task facts |
| Task complete | Boundary → Tick |
| Worker | Source (harness-specific) |
| Task registry | Vertex + SqliteStore |
| Progress | Facts (queryable) |

**Don't reach for yet**: Harness implementation, worktree internals, lifecycle vertex spec.

---

## Level 3 — Query-time fold and worker model

**Trigger**: I need to understand how task state is derived or how workers communicate.

**Query-time fold** — state derived at read time:
```
pull all facts → filter by task name → apply spec fold → derive state
```

`lifecycle.py` compiles a vertex spec for task state. `fold_task_state()` and `fold_all_tasks()` do the fold. No pre-materialized state — always computed from facts.

**Async worker model:**
- `task send` / `task run` spawns a detached process (`start_new_session=True`)
- Harness captures worker stdout line-by-line as `worker.output` facts
- On exit: emits `worker.output.complete` + `task.stage` + `task.tick`
- Worker runs in a git worktree (full monorepo copy)
- **No IPC, no sockets** — shared SQLite store (WAL mode) is the coordination channel

**Session narration** — no HANDOFF.md for this project. The project loop is the continuity mechanism:
```bash
strange-loops project status        # review decisions, open threads
strange-loops session log --since 1h  # recent activity
```

---

## Key conventions

- CLI is thin dispatcher. Display commands pre-dispatch to `run_cli`.
- Tests mirror src structure. Factories over mocks.
- Snapshot tests: text goldens for visual output, direct assertions for JSON. `--update-goldens` to regenerate.
- Regenerate CLI.md after argparse changes: `uv run --package strange-loops python scripts/gen_cli_docs.py`
- Tasks are facts. State is fold. Completion is tick.
- `./dev check` must pass before commit.

## Build & test

```bash
./dev check                                                    # CI gate
uv run --package strange-loops pytest apps/strange-loops/tests  # from monorepo root
```
