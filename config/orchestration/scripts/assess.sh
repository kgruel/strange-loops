#!/usr/bin/env bash
set -euo pipefail

# Assess open tasks — the orchestrator's decision point.
#
# Called by boundary run clause when a task fact with status=open arrives.
# Reads open tasks, selects model (from task fact or default), gathers
# project context, and emits a worker assignment (status=assigned).
#
# This is where the orchestrator's judgment lives. Currently heuristic;
# grows toward a full orchestrator claude call that reads project context
# and makes informed model/approach decisions.

REPO="${LOOPS_REPO:-/Users/kaygee/Code/loops}"
LOOPS="${REPO}/.venv/bin/loops"

if [[ ! -x "$LOOPS" ]]; then
  echo "error: loops binary not found at $LOOPS" >&2
  exit 1
fi

# Query fold state — find tasks with status=open
fold_json=$("$LOOPS" read orchestration --json 2>/dev/null || echo '{}')
open_tasks=$(echo "$fold_json" \
  | jq -r '.sections[]? | select(.kind == "task") | .items[]? | select(.payload.status == "open") | .payload.name' 2>/dev/null || true)

if [[ -z "$open_tasks" ]]; then
  echo "assess: no open tasks" >&2
  exit 0
fi

while IFS= read -r task_name; do
  echo "assess: ${task_name}" >&2

  # Extract task details from fold state
  task_json=$(echo "$fold_json" \
    | jq -c ".sections[]? | select(.kind == \"task\") | .items[]? | select(.payload.name == \"${task_name}\") | .payload" 2>/dev/null || echo '{}')

  prompt=$(echo "$task_json" | jq -r '.prompt // "No prompt provided"' 2>/dev/null)

  # Model selection: explicit in task fact, or default to sonnet
  model=$(echo "$task_json" | jq -r '.model // "sonnet"' 2>/dev/null)

  branch="worker/${task_name}"

  echo "assess: ${task_name} → model=${model}" >&2

  # Emit worker assignment — this triggers the dispatch boundary
  "$LOOPS" emit orchestration worker \
    name="${task_name}" \
    status=assigned \
    model="${model}" \
    branch="${branch}" \
    prompt="${prompt}" \
    2>/dev/null || true

  # Update task status to assigned
  "$LOOPS" emit orchestration task \
    name="${task_name}" \
    status=assigned \
    model="${model}" \
    2>/dev/null || true

done <<< "$open_tasks"
