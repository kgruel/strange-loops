#!/usr/bin/env bash
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
LOOPS="$REPO_ROOT/.venv/bin/loops"

[[ -x "$LOOPS" ]] || exit 0

observer="$($LOOPS whoami 2>/dev/null || echo "unknown")"

output=$($LOOPS fold comms --observer all --lens comms --plain -q 2>/dev/null || true)
$LOOPS emit comms/native check name="$observer" 2>/dev/null || true

case "$output" in
  ''|'(quiet)') ;;
  *) echo "$output" ;;
esac
