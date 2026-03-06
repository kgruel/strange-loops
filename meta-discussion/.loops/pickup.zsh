#!/usr/bin/env zsh
# meta-discussion pickup — bootstrap meta-claude session
# Uses `loops whoami` for observer resolution and `--lens prompt` for
# system-prompt-optimized rendering. LOOPS_OBSERVER is exported so all
# reads scope to your identity and emits are tagged automatically.

set -euo pipefail
cd "$(dirname "$0")/.."
source "$(git rev-parse --show-toplevel)/.venv/bin/activate"

dry_run=false
[[ "${1:-}" == "--dry-run" ]] && dry_run=true

# --- Resolve observer from .vertex chain ---
observer=$(loops whoami 2>/dev/null || echo "")
if [[ -z "$observer" ]]; then
  echo "No observer identity resolved."
  exit 1
fi
export LOOPS_OBSERVER="$observer"

# --- Read full fold BEFORE opening new session ---
# Root .vertex discovers identity + project + meta stores.
# Prompt lens renders identity as narrative, session as handoff, filters resolved items.
system_prompt=$(loops fold --observer all --lens prompt --plain 2>/dev/null || echo "")

# --- Launch (or dry-run) ---
if $dry_run; then
  echo "$system_prompt"
else
  # Session boundary — only on real launch, after reading handoff
  loops emit meta session name="$observer" status="open" 2>/dev/null || true
  exec claude --system-prompt "$system_prompt"
fi
