#!/bin/bash
# SessionEnd: mark the session closed, then seal (boundary → tick).
HOOK_DIR="${CLAUDE_PLUGIN_ROOT:+$CLAUDE_PLUGIN_ROOT/hooks}"
HOOK_DIR="${HOOK_DIR:-$(cd "$(dirname "$0")" && pwd)}"
source "$HOOK_DIR/lib.sh"
[ -f "$V" ] || exit 0   # not a loops-dogfooding repo → no-op cleanly
command -v "$SL" >/dev/null 2>&1 || { echo "loops plugin: sl not found — session not sealed" >&2; exit 0; }
# Stderr intentionally NOT suppressed — see session-open.sh.
"$SL" emit "$V" session name="$OBS" status=closed --observer "$OBS" -q
"$SL" seal "$V" -m "session close: $OBS" --observer "$OBS" -q
