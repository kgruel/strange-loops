#!/usr/bin/env zsh
# .loops/pickup.zsh — bootstrap a claude session with identity + handoff
# Uses `loops whoami` for observer resolution and `--lens prompt` for
# system-prompt-optimized rendering. LOOPS_OBSERVER is exported so all
# emits are tagged automatically.

set -euo pipefail
cd "$(git rev-parse --show-toplevel)"
source .venv/bin/activate

dry_run=false
[[ "${1:-}" == "--dry-run" ]] && dry_run=true

# --- Resolve observer from .vertex chain ---
observer=$(uv run loops whoami 2>/dev/null || echo "")
if [[ -z "$observer" ]]; then
  echo "No observer identity resolved."
  echo "Declare observers in .loops/.vertex or emit: loops identity emit self name=name \"your-name\""
  exit 1
fi
export LOOPS_OBSERVER="$observer"

# --- Identity context (prompt lens) ---
identity=$(uv run loops identity fold --lens prompt --plain 2>/dev/null || echo "")

# --- Handoff from meta store (stream, not fold — handoff isn't a fold kind) ---
handoff=$(uv run loops meta stream --kind handoff --since 1h --lens prompt --plain 2>/dev/null || echo "")

# --- Project context (open threads) ---
project=$(uv run loops project fold --kind thread --lens prompt --plain 2>/dev/null || echo "")

# --- Build system prompt ---
system_prompt="# Identity
$identity"

[[ -n "$handoff" && "$handoff" != "(empty)" ]] && system_prompt="$system_prompt

# Last Session Handoff
$handoff"

[[ -n "$project" && "$project" != "(empty)" ]] && system_prompt="$system_prompt

# Project Threads
$project"

# --- Launch ---
if $dry_run; then
  echo "$system_prompt"
else
  exec claude --system-prompt "$system_prompt"
fi
