#!/usr/bin/env zsh
# .loops/pickup.zsh — bootstrap a claude session with identity + handoff
# The system prompt is the fold output. No jq, no reshaping — the command
# produces what we need because we own the fold definition.
# LOOPS_OBSERVER is exported so all emits are tagged automatically.

set -euo pipefail
cd "$(git rev-parse --show-toplevel)"
source .venv/bin/activate

dry_run=false
[[ "${1:-}" == "--dry-run" ]] && dry_run=true

# --- Read identity fold (declaration-ordered, full text when piped) ---
identity=$(uv run loops identity fold --plain 2>/dev/null || echo "")

if [[ -z "$identity" ]]; then
  echo "No identity found. Run: uv run loops identity emit self name=name \"your-name\""
  exit 1
fi

# Extract observer name from fold JSON (need the raw name value)
observer=$(uv run loops identity fold --json 2>/dev/null | python3 -c "
import sys, json
data = json.load(sys.stdin)
for s in data.get('sections', []):
    if s['kind'] == 'self':
        for item in s['items']:
            if item.get('name') == 'name':
                print(item['message'].split('.')[0])
                sys.exit(0)
" 2>/dev/null || echo "")

if [[ -z "$observer" ]]; then
  echo "No self/name found in identity store."
  exit 1
fi

export LOOPS_OBSERVER="$observer"

# --- Read latest handoff from this observer ---
handoff=$(uv run loops meta stream --kind handoff --since 7d --json 2>/dev/null | python3 -c "
import sys, json
data = json.load(sys.stdin)
obs = '$observer'
for f in data.get('facts', []):
    if f.get('observer') == obs:
        print(f['payload']['message'])
        sys.exit(0)
# Fall back to any observer's latest
for f in data.get('facts', []):
    print(f['payload']['message'])
    sys.exit(0)
" 2>/dev/null || echo "")

# --- Build system prompt ---
system_prompt="# Identity
$identity"

if [[ -n "$handoff" ]]; then
  system_prompt="$system_prompt

# Last Session Handoff
$handoff"
fi

# --- Launch ---
if $dry_run; then
  echo "$system_prompt"
else
  exec claude --system-prompt "$system_prompt"
fi
