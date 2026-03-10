#!/usr/bin/env bash
set -euo pipefail

# Dispatch assigned workers — the mechanical half of two-phase dispatch.
#
# Called by boundary run clause when a worker fact with status=assigned arrives.
# Reads assigned workers from fold state, creates worktrees, launches claude.
#
# Phase 1 (assess.sh) already made the judgment calls — model selection,
# context gathering, prompt enrichment. This script just executes.
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

# Query fold state — find workers with status=assigned
# JSON is FoldState format: .sections[].items[].payload
fold_json=$("$LOOPS" read orchestration --json 2>/dev/null || echo '{}')
assigned_workers=$(echo "$fold_json" \
  | jq -r '.sections[]? | select(.kind == "worker") | .items[]? | select(.payload.status == "assigned") | .payload.name' 2>/dev/null || true)

if [[ -z "$assigned_workers" ]]; then
  echo "dispatch: no assigned workers" >&2
  exit 0
fi

while IFS= read -r worker_name; do
  echo "dispatch: ${worker_name}" >&2

  # Extract worker details from fold state — assess.sh packed these
  worker_json=$(echo "$fold_json" \
    | jq -c ".sections[]? | select(.kind == \"worker\") | .items[]? | select(.payload.name == \"${worker_name}\") | .payload" 2>/dev/null || echo '{}')

  prompt=$(echo "$worker_json" | jq -r '.prompt // "No prompt provided"' 2>/dev/null)
  model=$(echo "$worker_json" | jq -r '.model // "sonnet"' 2>/dev/null)
  branch=$(echo "$worker_json" | jq -r '.branch // "worker/'"${worker_name}"'"' 2>/dev/null)

  worktree="${WORKER_DIR}/${worker_name}"

  # Create worktree if it doesn't already exist (idempotent)
  if [[ -d "$worktree" ]]; then
    echo "dispatch: worktree already exists for ${worker_name}, skipping" >&2
    continue
  fi

  # Create worktree from HEAD
  (cd "$REPO" && git worktree add "$worktree" -b "$branch" HEAD 2>/dev/null) || {
    echo "dispatch: failed to create worktree for ${worker_name}" >&2
    continue
  }

  # Mark worker as running before launch
  "$LOOPS" emit orchestration worker \
    name="${worker_name}" \
    status=running \
    model="${model}" \
    branch="${branch}" \
    2>/dev/null || true

  # Update task status to running
  "$LOOPS" emit orchestration task \
    name="${worker_name}" \
    status=running \
    2>/dev/null || true

  echo "dispatch: ${worker_name} → model=${model} branch=${branch}" >&2

  # Map model name to claude flag
  # claude --model accepts: sonnet, opus, haiku (Claude Code CLI model names)
  model_flag=""
  if [[ "$model" != "sonnet" ]]; then
    model_flag="--model ${model}"
  fi

  # Launch worker — fire and forget
  # Worker runs as a detached process with the task prompt
  (
    cd "$worktree"
    # CLAUDECODE= clears parent session context
    # shellcheck disable=SC2086
    env CLAUDECODE= LOOPS_OBSERVER="orchestrator/worker-${worker_name}" \
      claude --print ${model_flag} -p "$prompt" > "${worktree}/worker.log" 2>&1

    # Worker finished — emit completion
    "$LOOPS" emit orchestration worker \
      name="${worker_name}" \
      status=completed \
      model="${model}" \
      branch="${branch}" \
      2>/dev/null || true

    "$LOOPS" emit orchestration task \
      name="${worker_name}" \
      status=completed \
      2>/dev/null || true

    # Clean up worktree
    (cd "$REPO" && git worktree remove "$worktree" --force 2>/dev/null) || true
  ) &

  echo "dispatch: launched worker for ${worker_name} (pid $!)" >&2

done <<< "$assigned_workers"
