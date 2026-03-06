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

# 1. Session marker + project context
$LOOPS emit project session name="$observer" status=open 2>/dev/null || true
$LOOPS fold project --lens prompt --plain 2>/dev/null || true

# 2. Identity
$LOOPS fold identity --lens prompt --plain 2>/dev/null || true

# 3. Comms — poll discord, show new messages, mark check-in
$LOOPS run ~/.config/loops/comms/discord/discord.vertex --plain -q 2>/dev/null || true
$LOOPS fold comms --observer all --lens comms --plain -q 2>/dev/null || true
$LOOPS emit comms/native check name="$observer" 2>/dev/null || true
