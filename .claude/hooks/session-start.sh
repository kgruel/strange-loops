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

# --- Collect context ---
# Identity is already in the system prompt header (via agent config).
# additionalContext carries: prior session tick + current state + comms.
# Read comms BEFORE emitting check — so "new" means "since last session."
# Prior sessions: listing mode shows when, who, duration — temporal context.
# Drill-down (0:N) re-folds the same data as the fold view, so use listing.
prior=$($LOOPS read project --ticks --since 3d --plain 2>/dev/null | head -15 || true)
project=$($LOOPS read project --lens session_start --plain 2>/dev/null || true)
comms=$($LOOPS read comms --observer all --lens comms --plain -q 2>/dev/null || true)

# Advance cursor after reading — marks what we've seen
$LOOPS emit comms/native check name="$observer" >/dev/null 2>&1 || true

context=""
[[ -n "$prior" && "$prior" != "(no substantive facts)" ]] && context+="$prior"$'\n\n'
[[ -n "$project" ]]  && context+="$project"$'\n\n'
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
