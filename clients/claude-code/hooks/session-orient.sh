#!/bin/bash
# SessionStart (2/2): orient block — pointer-over-payload, target < 2KB.
# Surfaces where the last session sealed, what's open, what moved lately, and
# WHICH LENSES to run for depth (the block is a map, not the territory).
HOOK_DIR="${CLAUDE_PLUGIN_ROOT:+$CLAUDE_PLUGIN_ROOT/hooks}"
HOOK_DIR="${HOOK_DIR:-$(cd "$(dirname "$0")" && pwd)}"
source "$HOOK_DIR/lib.sh"
[ -f "$V" ] || exit 0   # not a loops-dogfooding repo → no orient block
command -v "$SL" >/dev/null 2>&1 || exit 0   # no sl → skip silently (don't print a degenerate all-zeros block)

seal=$("$SL" read "$V" --kind seal --plain 2>/dev/null | grep '^  ' | grep -v '^ *$' | tail -1 | sed 's/^ *//' | cut -c1-180)
open_t=$("$SL" read "$V" --kind thread --plain 2>/dev/null | grep -c ': open ·')
open_f=$("$SL" read "$V" --kind friction --plain 2>/dev/null | grep -c ': open ·')
adopted=$("$SL" read "$V" --kind thread --plain 2>/dev/null | grep -c ': adopted ·')

echo "== loops orient =="
echo "last seal: ${seal:-none}"
echo "open: ${open_t} threads · ${open_f} frictions · ${adopted} adopted-practices"
echo "moved in last 3d:"
"$SL" read "$V" --facts --since 3d --plain 2>/dev/null \
  | grep -E '^\s+[0-9]{2}:[0-9]{2} \[(thread|decision|friction)\]' \
  | head -5 | cut -c1-160
echo "deeper: sl read project --lens reconcile (staleness) · --ticks (windows) · --kind log --plain (reroutes) · --kind friction --plain (backlog)"
