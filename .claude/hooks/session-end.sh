#!/usr/bin/env bash
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
LOOPS="$REPO_ROOT/.venv/bin/loops"

[[ -x "$LOOPS" ]] || exit 0

observer="$($LOOPS whoami 2>/dev/null || echo "unknown")"
$LOOPS emit project session name="$observer" status=closed 2>/dev/null || true
