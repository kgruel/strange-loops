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

VERTEX=".loops/autoresearch/prompt-test.vertex"
BENCHMARK="uv run python benchmarks/benchmark_read.py"
METRIC="read_ms"
SYSTEM_PROMPT="/Users/kaygee/.config/loops/autoresearch/system-prompt.md"

cd /Users/kaygee/Code/loops
BEFORE=$(git rev-parse HEAD)

# --- Agent turn ---
# System prompt cached; user prompt is current fold state (XML).
# Agent may exit non-zero (killed, timeout, error) — don't fail the script.
claude --dangerously-skip-permissions --model sonnet \
  --max-turns 50 \
  --system-prompt "$(cat "$SYSTEM_PROMPT")" \
  -p "$(uv run loops read "$VERTEX" --lens autoresearch_prompt --plain)" \
  || true

AFTER=$(git rev-parse HEAD)

# --- Benchmark and record ---
if [ "$BEFORE" != "$AFTER" ]; then
  DESC=$(git log -1 --format=%s)
  RESULT=$($BENCHMARK 2>&1) || true
  VALUE=$(echo "$RESULT" | grep "^${METRIC}=" | head -1 | cut -d= -f2)

  if [ -n "$VALUE" ]; then
    uv run loops emit "$VERTEX" experiment \
      commit="$(git rev-parse --short HEAD)" \
      status=keep \
      "${METRIC}=${VALUE}" \
      description="$DESC"
  else
    uv run loops emit "$VERTEX" experiment \
      commit="$(git rev-parse --short HEAD)" \
      status=keep \
      description="$DESC (no ${METRIC} in benchmark output)"
  fi
else
  uv run loops emit "$VERTEX" experiment \
    commit="$(git rev-parse --short HEAD)" \
    status=discard \
    description="No changes committed"
fi
