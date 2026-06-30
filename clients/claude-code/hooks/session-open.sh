#!/bin/bash
# SessionStart (1/2): mark the session open in this repo's project vertex.
HOOK_DIR="${CLAUDE_PLUGIN_ROOT:+$CLAUDE_PLUGIN_ROOT/hooks}"
HOOK_DIR="${HOOK_DIR:-$(cd "$(dirname "$0")" && pwd)}"
source "$HOOK_DIR/lib.sh"
[ -f "$V" ] || exit 0   # not a loops-dogfooding repo → no-op cleanly
command -v "$SL" >/dev/null 2>&1 || { echo "loops plugin: sl not found — session not recorded" >&2; exit 0; }
# Stderr is intentionally NOT suppressed: a real emit/signing failure should
# surface (silent data loss is the worst failure for a trust substrate).
"$SL" emit "$V" session name="$OBS" status=open --observer "$OBS" -q
