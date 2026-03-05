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

# --- Read full fold BEFORE opening new session ---
# Root .vertex discovers identity + project stores. --observer all sees across observers.
# Prompt lens renders identity as narrative, session as handoff, filters resolved items.
system_prompt=$(loops fold --observer all --lens prompt --plain 2>/dev/null || echo "")

# --- Session boundary — mark arrival after reading ---
loops emit project session name="$observer" status="open" 2>/dev/null || true

# --- Launch ---
if $dry_run; then
  echo "$system_prompt"
else
  exec claude --system-prompt "$system_prompt"
fi
