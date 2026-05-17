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

# --- Side effects (no stdout needed) ---
$LOOPS emit project session name="$observer" status=open >/dev/null 2>&1 || true
$LOOPS sync ~/.config/loops/comms/discord/discord.vertex --force >/dev/null 2>&1 || true

# --- Collect context ---
# Identity is already in the system prompt header (via agent config).
# additionalContext carries (in priority order — most actionable first):
#
#   1. MENTIONS — direct addresses since last sync (discord). The thing
#      that should make me act before anything else. Surfaced separately
#      because comms summary-counts ("discord: 62") triggers drill-later;
#      addressee + freshness + body triggers act-now. Per the
#      painted/first-disclosure-via-existing-headlines decision: surface
#      enough substance to earn the drill-down, not just enough to know
#      it exists.
#   2. PROJECT LANDING — session_landing lens output: NOW (window
#      dashboard), TOUCHED (focus-marked items), UNPACK (drill-down
#      commands). Answers "what was happening, what's already in flight."
#   3. ARCS — `sl read project thread/<name> --diff` of the top-N open/partial threads.
#      Where TOUCHED carries current state, ARCS carries trajectory —
#      what transitioned at each emit, refs added/removed. Renders
#      what changed since I last looked at the arc, not just where it
#      ended up. Composes with TOUCHED; doesn't duplicate it.
#
# Comms-via-vertex was previously surfaced here; removed 2026-05-16 because
# we stopped using it lately and the mcp comms work likely dissolves into
# transport + vertex config once vouch-as-lib lands. Re-add when the
# replacement shape is clear.
mentions=$($HOME/.config/loops/bin/mentions-block "$observer" 2>/dev/null || true)
project=$($LOOPS read project --lens session_landing --plain 2>/dev/null || true)

# ARCS IN FLIGHT — lifecycle diff for the most-recently-touched open threads.
# Why: session_landing's TOUCHED block shows the current state of each thread,
# but the actionable signal is "what changed since you last looked." read
# --diff renders that — status transitions, ref churn, just the deltas — which
# is much sharper than re-reading the full body of each touched item.
# Selection: top 2 open/partial threads by recency. Both signal "in-flight"
# and bias toward fresh work. Output is capped per-thread to keep the
# additionalContext within reasonable size.
export REPO_ROOT
export LOOPS_BIN="$LOOPS"
arcs=$("$REPO_ROOT/.venv/bin/python3" "$REPO_ROOT/.claude/hooks/arcs-block.py" 2>/dev/null || true)

context=""
[[ -n "$mentions" ]] && context+="$mentions"$'\n'
[[ -n "$project" ]]  && context+="$project"$'\n\n'
[[ -n "$arcs" ]] && context+="$arcs"$'\n'

# --- Emit as JSON additionalContext for reliable injection ---
if [[ -n "$context" ]]; then
  jq -n --arg ctx "$context" '{
    hookSpecificOutput: {
      hookEventName: "SessionStart",
      additionalContext: $ctx
    }
  }'
fi
