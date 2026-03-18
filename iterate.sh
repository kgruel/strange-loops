#!/usr/bin/env bash
set -euo pipefail

# iterate.sh — one BOUNDED AGENT TURN
#
# Run clause target for autoresearch vertex. Spawns one-shot agent,
# benchmarks the result, emits turn-completing experiment fact.
# The vertex boundary drives iteration — this script is one turn.
#
# Variables below are stamped by `loops init`. To change config
# after init, edit this file or re-init.

VERTEX=".loops/autoresearch/read-latency.vertex"
BENCHMARK="uv run python benchmarks/benchmark_read.py"
METRIC="read_ms"
CHECKS=""  # optional: path to checks script (test suite gate)
SYSTEM_PROMPT="/Users/kaygee/.config/loops/autoresearch/system-prompt.md"

BEFORE=$(git rev-parse HEAD)

# --- Agent turn ---
# System prompt cached; user prompt is current fold state (XML).
# Agent may exit non-zero (crash, timeout) — capture but don't fail.
AGENT_EXIT=0
claude --dangerously-skip-permissions \
  --system-prompt "$(cat "$SYSTEM_PROMPT")" \
  -p "$(uv run loops read "$VERTEX" --lens autoresearch_prompt --plain)" \
  || AGENT_EXIT=$?

AFTER=$(git rev-parse HEAD)

# --- Benchmark and record ---
if [ "$BEFORE" = "$AFTER" ]; then
  # No changes committed
  uv run loops emit "$VERTEX" experiment \
    commit="$(git rev-parse --short HEAD)" \
    status=discard \
    description="No changes committed"
  exit 0
fi

DESC=$(git log -1 --format=%s)

# Agent crashed?
if [ "$AGENT_EXIT" -ne 0 ]; then
  uv run loops emit "$VERTEX" experiment \
    commit="$(git rev-parse --short HEAD)" \
    status=crash \
    description="Agent exited $AGENT_EXIT: $DESC"
  exit 0
fi

# Run benchmark — capture all METRIC lines
RESULT=$($BENCHMARK 2>&1) || true

# Parse all metrics from output (lines matching KEY=VALUE)
METRIC_ARGS=()
PRIMARY_VALUE=""
while IFS= read -r line; do
  key=$(echo "$line" | cut -d= -f1)
  val=$(echo "$line" | cut -d= -f2)
  METRIC_ARGS+=("${key}=${val}")
  if [ "$key" = "$METRIC" ]; then
    PRIMARY_VALUE="$val"
  fi
done < <(echo "$RESULT" | grep -E '^[a-zA-Z_]+=' || true)

# Determine status
STATUS="keep"
if [ -z "$PRIMARY_VALUE" ]; then
  STATUS="keep"  # no metric = keep (can't compare)
  METRIC_ARGS+=("description=$DESC (no ${METRIC} in output)")
else
  METRIC_ARGS+=("description=$DESC")
fi

# Run checks gate if configured
if [ -n "$CHECKS" ] && [ -f "$CHECKS" ]; then
  if ! bash "$CHECKS" > /dev/null 2>&1; then
    STATUS="checks_failed"
  fi
fi

uv run loops emit "$VERTEX" experiment \
  commit="$(git rev-parse --short HEAD)" \
  status="$STATUS" \
  "${METRIC_ARGS[@]}"
