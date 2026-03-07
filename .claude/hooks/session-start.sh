#!/usr/bin/env bash
set -euo pipefail

# Resolve loops binary from the monorepo venv
REPO_ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
LOOPS="$REPO_ROOT/.venv/bin/loops"

if [[ ! -x "$LOOPS" ]]; then
  echo "warning: loops binary not found at $LOOPS" >&2
  exit 0
fi

observer="$($LOOPS whoami 2>/dev/null || echo "unknown")"

# --- Side effects (no stdout needed) ---
$LOOPS emit project session name="$observer" status=open >/dev/null 2>&1 || true
$LOOPS sync ~/.config/loops/comms/discord/discord.vertex --force >/dev/null 2>&1 || true
$LOOPS emit comms/native check name="$observer" >/dev/null 2>&1 || true

# --- Collect context ---
project=$($LOOPS read project --lens prompt --plain 2>/dev/null || true)
identity=$($LOOPS read identity --plain 2>/dev/null || true)
comms=$($LOOPS read comms --observer all --lens comms --plain -q 2>/dev/null || true)

context=""
[[ -n "$project" ]]  && context+="$project"$'\n\n'
[[ -n "$identity" ]] && context+="$identity"$'\n\n'
[[ -n "$comms" && "$comms" != "(quiet)" ]] && context+="$comms"

# --- Emit as JSON additionalContext for reliable injection ---
if [[ -n "$context" ]]; then
  jq -n --arg ctx "$context" '{
    hookSpecificOutput: {
      hookEventName: "SessionStart",
      additionalContext: $ctx
    }
  }'
fi
