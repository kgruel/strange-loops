#!/usr/bin/env bash
set -euo pipefail

# Dispatch open tasks from the orchestration vertex.
#
# Called by boundary run clause when a task fact with status=open arrives.
# Queries fold state, finds open tasks, creates worktrees, launches workers.
#
# Workers are lightweight — no loops identity, no persistent state. They
# run in isolated worktrees and emit facts back to the orchestration vertex.

SCRIPT_DIR="$(cd -P "$(dirname "$0")" && pwd)"

# Resolve loops binary from the monorepo venv
REPO="${LOOPS_REPO:-/Users/kaygee/Code/loops}"
LOOPS="${REPO}/.venv/bin/loops"

if [[ ! -x "$LOOPS" ]]; then
  echo "error: loops binary not found at $LOOPS" >&2
  exit 1
fi

# Worker worktrees live here
WORKER_DIR="${LOOPS_WORKER_DIR:-/tmp/loops-workers}"
mkdir -p "$WORKER_DIR"

# Query fold state — find tasks with status=open
# JSON is FoldState format: .sections[].items[].payload
fold_json=$("$LOOPS" read orchestration --json 2>/dev/null || echo '{}')
open_tasks=$(echo "$fold_json" \
  | jq -r '.sections[]? | select(.kind == "task") | .items[]? | select(.payload.status == "open") | .payload.name' 2>/dev/null || true)

if [[ -z "$open_tasks" ]]; then
  echo "dispatch: no open tasks" >&2
  exit 0
fi

while IFS= read -r task_name; do
  echo "dispatch: ${task_name}" >&2

  # Extract task prompt from fold state
  prompt=$(echo "$fold_json" \
    | jq -r ".sections[]? | select(.kind == \"task\") | .items[]? | select(.payload.name == \"${task_name}\") | .payload.prompt // \"No prompt provided\"" 2>/dev/null || echo "No prompt provided")

  worktree="${WORKER_DIR}/${task_name}"
  branch="worker/${task_name}"

  # Create worktree if it doesn't already exist (idempotent)
  if [[ -d "$worktree" ]]; then
    echo "dispatch: worktree already exists for ${task_name}, skipping" >&2
    continue
  fi

  # Create worktree from HEAD
  (cd "$REPO" && git worktree add "$worktree" -b "$branch" HEAD 2>/dev/null) || {
    echo "dispatch: failed to create worktree for ${task_name}" >&2
    continue
  }

  # Mark task as assigned before launching worker
  "$LOOPS" emit orchestration task name="${task_name}" status=assigned 2>/dev/null || true

  # Launch worker — fire and forget
  # Worker runs as a detached process with the task prompt
  (
    cd "$worktree"
    env CLAUDECODE= LOOPS_OBSERVER="kyle/worker-${task_name}" \
      claude --print -p "$prompt" > "${worktree}/worker.log" 2>&1

    # Worker finished — emit completion
    "$LOOPS" emit orchestration task name="${task_name}" status=completed 2>/dev/null || true

    # Clean up worktree
    (cd "$REPO" && git worktree remove "$worktree" --force 2>/dev/null) || true
  ) &

  echo "dispatch: launched worker for ${task_name} (pid $!)" >&2

done <<< "$open_tasks"
