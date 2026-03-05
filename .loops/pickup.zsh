#!/usr/bin/env zsh
# .loops/pickup.zsh — bootstrap a claude session with identity + handoff
# Uses `loops whoami` for observer resolution and `--lens prompt` for
# system-prompt-optimized rendering. LOOPS_OBSERVER is exported so all
# reads scope to your identity and emits are tagged automatically.

set -euo pipefail
cd "$(git rev-parse --show-toplevel)"
source .venv/bin/activate

dry_run=false
[[ "${1:-}" == "--dry-run" ]] && dry_run=true

# --- Resolve observer from .vertex chain ---
observer=$(loops whoami 2>/dev/null || echo "")
if [[ -z "$observer" ]]; then
  echo "No observer identity resolved."
  echo "Declare observers in .loops/.vertex or emit: loops identity emit self name=name \"your-name\""
  exit 1
fi
export LOOPS_OBSERVER="$observer"

# --- Session boundary — mark arrival before anything else ---
loops emit project session name="$observer" status="open" 2>/dev/null || true

# --- Identity context (observer-scoped — sees only your facts) ---
identity=$(loops identity fold --lens prompt --plain 2>/dev/null || echo "")

# --- Handoff (observer-scoped — last session's resolved state IS the handoff) ---
handoff=$(loops fold project --kind session --lens prompt --plain 2>/dev/null || echo "")

# --- Open tasks (all observers — tasks are shared, use --observer="" to unscope) ---
tasks=$(loops fold project --kind task --observer all --lens prompt --plain 2>/dev/null || echo "")

# --- Build system prompt ---
system_prompt="# Identity
$identity"

[[ -n "$handoff" && "$handoff" != "(empty)" ]] && system_prompt="$system_prompt

# Last Session Handoff
$handoff"

[[ -n "$tasks" && "$tasks" != "(empty)" ]] && system_prompt="$system_prompt

# Open Tasks
$tasks"

# --- Launch ---
if $dry_run; then
  echo "$system_prompt"
else
  exec claude --system-prompt "$system_prompt"
fi
