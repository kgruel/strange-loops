#!/usr/bin/env bash
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
LOOPS="$REPO_ROOT/.venv/bin/loops"

[[ -x "$LOOPS" ]] || exit 0

observer="$($LOOPS whoami 2>/dev/null || echo "unknown")"

# Mechanical session delta — counts facts by kind since session open.
# Safety net: even without narrative wrap-up, the tick carries a summary.
summary="$(python3 "$REPO_ROOT/.claude/hooks/session-delta.py" "$LOOPS" "$observer" 2>/dev/null || true)"
if [[ -n "$summary" ]]; then
  $LOOPS emit project log "$summary" 2>/dev/null || true
fi

# Close the session — triggers boundary, produces tick
$LOOPS emit project session name="$observer" status=closed 2>/dev/null || true
