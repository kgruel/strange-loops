#!/usr/bin/env zsh
# meta-discussion pickup — bootstrap meta-claude session
# Runs from meta-discussion/ to resolve observer and context correctly.

set -euo pipefail
cd "$(dirname "$0")/.."
source "$(git rev-parse --show-toplevel)/.venv/bin/activate"

dry_run=false
[[ "${1:-}" == "--dry-run" ]] && dry_run=true

# --- Resolve observer from .vertex chain ---
observer=$(uv run loops whoami 2>/dev/null || echo "")
if [[ -z "$observer" ]]; then
  echo "No observer identity resolved."
  exit 1
fi
export LOOPS_OBSERVER="$observer"

# --Session boundary - mark arrival before anything else ---
uv run loops meta emit session name="$observer" status=active 2>dev/null || echo ""

# --- Identity context (prompt lens) ---
identity=$(uv run loops identity fold --lens prompt --plain 2>/dev/null || echo "")

# --- Handoff from meta store (fold collect 1 = latest) ---
handoff=$(uv run loops meta fold --kind handoff --lens prompt --plain 2>/dev/null || echo "")

# --- Open tasks from project store ---
tasks=$(uv run loops project fold --kind task --lens prompt --plain 2>/dev/null || echo "")

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
