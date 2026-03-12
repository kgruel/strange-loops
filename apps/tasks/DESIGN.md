# strange-loops: Design

Task orchestration as loops. Self-referential by nature — the orchestrator
is itself a loop that spawns loops.

## The Insight

Subtask, Claude Code agent teams, CrewAI, LangGraph — all orchestration
systems share the same shape: facts flow in (task events), state accumulates
(task tracking), boundaries fire (task completion), ticks emerge (results).

This IS the loops model. The orchestration system doesn't need its own
abstractions — it needs a vertex.

## Architecture

```
strange-loops
    │
    ├── Vertex (task registry)
    │   ├── store: ./data/tasks.db
    │   └── loops:
    │       ├── task     { fold { items "by" "name" } }
    │       ├── worker   { fold { items "by" "task" } }
    │       └── stage    { fold { items "by" "task" } }
    │
    ├── Sources (harnesses)
    │   ├── claude.loop      # Claude Code worker
    │   ├── codex.loop       # Codex worker
    │   └── shell.loop       # Plain shell script
    │
    ├── Worktrees (.worktrees/, gitignored)
    │   ├── task-name-1/     # Isolated checkout
    │   └── task-name-2/
    │
    └── UI (painted)
        ├── task list        # Zoom-aware status view
        ├── task detail      # Progress + facts
        └── diff view        # Worktree changes
```

## Fact Kinds

| Kind | Key | Grouping | What it captures |
|------|-----|----------|------------------|
| `task.created` | `name` | by name | Task definition, description, base branch |
| `task.stage` | `name` | by name | Stage transitions (plan, implement, review, ready) |
| `task.assigned` | `name` | by name | Worker assignment (harness, worktree path) |
| `task.progress` | `name` | by name | Worker progress (tool calls, lines changed) |
| `task.completed` | `name` | by name | Boundary — task done, result summary |
| `task.merged` | `name` | by name | Integrated into base branch |
| `worker.started` | `task` | by task | Harness spawned |
| `worker.output` | `task` | collect | Worker's fact stream (observations) |
| `worker.stopped` | `task` | by task | Harness exited (success/error) |

## Harness Interface

A harness is a Source — a `.loop` file that knows how to invoke a worker
and produce facts from its output.

```
command: "claude-code --worktree {{worktree}} --prompt {{prompt}}"
kind: "worker.output"
format: ndjson
every: (once)
```

The harness abstraction is just template substitution on a Source.
Different harnesses = different .loop files. Same vertex, same store,
same fold logic.

## Worktree Strategy

```
.worktrees/           # gitignored
  task-name/          # git worktree, branched from base
```

Owned by strange-loops. Created on `task assign`, cleaned on `task close`.
Merge strategy is configurable per task (squash, rebase, merge commit).

## CLI Shape

```bash
strange-loops task create <name> --title "..." --base main
strange-loops task assign <name> --harness claude
strange-loops task send <name> "prompt text"
strange-loops task status [name]
strange-loops task diff <name>
strange-loops task merge <name>
strange-loops task close <name>
strange-loops task list

strange-loops log [--since 24h] [--kind task.stage]
strange-loops status                    # all active tasks, zoom-aware
```

## What's NOT v1

- No peer-to-peer worker communication — hub-and-spoke only
- No automatic stage advancement — explicit CLI commands
- No cross-repo orchestration — single repo per vertex
- No live TUI — static + JSON output first, interactive later
- No A2A protocol — local only

## Prior Art

- **Subtask** — git worktrees + SQLite index + pluggable harnesses.
  strange-loops keeps the worktree isolation and harness abstraction,
  replaces the custom DB with a loops vertex store.
- **Claude Code agent teams** — Task/Team/SendMessage + worktrees.
  strange-loops can wrap this as a harness while adding stage model
  and painted UI.
- **Industry patterns** — isolation by default, narrow coordination
  channels, plan-then-execute, code-first over graph-first.
