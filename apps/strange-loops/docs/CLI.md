# CLI Reference

Auto-generated from argparse definitions in `src/strange_loops/cli.py`.

```
Usage: strange-loops <command> [options]
```

Task orchestration built on loops

## Commands

- [`dashboard`](#dashboard) — Task dashboard
- [`note`](#note) — Emit a session note
- [`project`](#project) — Project coordination surface
- [`session`](#session) — Session lifecycle
- [`task`](#task) — Task lifecycle
- [`version`](#version) — Show version

---

## `dashboard`

Task dashboard

## `note`

Emit a session note

| Argument | Description | Required |
|----------|-------------|----------|
| `message` | Note text | required |
| `--observer` | Observer identity |  |

## `project`

Project coordination surface

### `bridge`

Bridge task ticks to project completions

| Argument | Description | Required |
|----------|-------------|----------|
| `--observer` | Observer identity |  |

### `emit`

Emit a project fact

| Argument | Description | Required |
|----------|-------------|----------|
| `kind` | Fact kind (decision, thread, plan) | required |
| `parts` | KEY=VALUE pairs and/or message |  |
| `--observer` | Observer identity |  |

### `log`

Show project log

| Argument | Description | Required |
|----------|-------------|----------|
| `--since` | Time range (e.g. 7d, 24h) (default: `7d`) |  |
| `--kind` | Filter by fact kind |  |
| `--json` | JSONL output (default: `False`) |  |

### `status`

Show project status

| Argument | Description | Required |
|----------|-------------|----------|
| `--json` | JSON output (default: `False`) |  |

## `session`

Session lifecycle

### `end`

End a session

| Argument | Description | Required |
|----------|-------------|----------|
| `--observer` | Observer identity |  |

### `log`

Show session log

| Argument | Description | Required |
|----------|-------------|----------|
| `--since` | Time range (e.g. 7d, 24h) (default: `7d`) |  |
| `--kind` | Filter by fact kind |  |
| `--json` | JSONL output (default: `False`) |  |

### `start`

Start a session

| Argument | Description | Required |
|----------|-------------|----------|
| `--observer` | Observer identity |  |

### `status`

Show session status

| Argument | Description | Required |
|----------|-------------|----------|
| `--json` | JSON output (default: `False`) |  |

## `task`

Task lifecycle

### `assign`

Assign a task (creates worktree)

| Argument | Description | Required |
|----------|-------------|----------|
| `name` | Task name | required |
| `--harness` | Harness type (default: shell) (default: `shell`) |  |
| `--observer` | Observer identity |  |

### `close`

Close a task (remove worktree)

| Argument | Description | Required |
|----------|-------------|----------|
| `name` | Task name | required |
| `--observer` | Observer identity |  |

### `create`

Create a task

| Argument | Description | Required |
|----------|-------------|----------|
| `name` | Task name (used as branch name) | required |
| `--title` | Human-readable title |  |
| `--base` | Base branch (default: current branch) |  |
| `--description` | Task description |  |
| `--observer` | Observer identity |  |

### `diff`

Show task worktree diff

| Argument | Description | Required |
|----------|-------------|----------|
| `name` | Task name | required |

### `list`

List all tasks

| Argument | Description | Required |
|----------|-------------|----------|
| `--json` | JSON output (default: `False`) |  |

### `log`

Show task log

| Argument | Description | Required |
|----------|-------------|----------|
| `name` | Task name | required |
| `--since` | Time range (e.g. 7d, 24h) (default: `7d`) |  |
| `--kind` | Filter by fact kind |  |
| `--json` | JSONL output (default: `False`) |  |
| `--follow` | Follow new facts (default: `False`) |  |

### `merge`

Squash merge task branch

| Argument | Description | Required |
|----------|-------------|----------|
| `name` | Task name | required |
| `--force` | Merge even with uncommitted changes (default: `False`) |  |
| `--observer` | Observer identity |  |

### `run`

Create, assign, and send in one step

| Argument | Description | Required |
|----------|-------------|----------|
| `name` | Task name (branch, worktree, fact key) | required |
| `--description` | Work specification / prompt for harness | required |
| `--harness` | Harness .loop file (default: shell) (default: `shell`) |  |
| `--title` | Human-readable title (default: name) |  |
| `--base` | Base branch (default: current branch) |  |
| `--observer` | Observer identity |  |

### `send`

Send work to a task

| Argument | Description | Required |
|----------|-------------|----------|
| `name` | Task name | required |
| `shell_command` | Shell command to run in worktree | required |
| `--observer` | Observer identity |  |

### `status`

Show task status

| Argument | Description | Required |
|----------|-------------|----------|
| `name` | Task name (omit for all) |  |
| `--json` | JSON output (default: `False`) |  |

### `stop`

Stop a running task worker

| Argument | Description | Required |
|----------|-------------|----------|
| `name` | Task name | required |
| `--observer` | Observer identity |  |

## `version`

Show version
