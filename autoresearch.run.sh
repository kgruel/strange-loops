#!/usr/bin/env bash
set -euo pipefail

VERTEX=".loops/autoresearch/read-latency.vertex"
BENCHMARK="uv run python benchmarks/benchmark_read.py"
METRIC="read_ms"

BEFORE=$(git rev-parse HEAD)

# Agent works — one-shot, exits when done
claude --dangerously-skip-permissions -p \
  "$(uv run loops read $VERTEX --lens autoresearch_prompt --plain)"

AFTER=$(git rev-parse HEAD)

if [ "$BEFORE" != "$AFTER" ]; then
  # Agent committed — benchmark the result
  RESULT=$($BENCHMARK 2>&1)
  VALUE=$(echo "$RESULT" | grep "^${METRIC}=" | head -1 | cut -d= -f2)
  DESC=$(git log -1 --format=%s)
  if [ -n "$VALUE" ]; then
    uv run loops emit "$VERTEX" experiment \
      commit="$(git rev-parse --short HEAD)" status=keep \
      ${METRIC}="$VALUE" description="$DESC"
  else
    uv run loops emit "$VERTEX" experiment \
      commit="$(git rev-parse --short HEAD)" status=keep \
      description="$DESC (benchmark parse failed)"
  fi
else
  # Agent didn't commit — record as discard
  uv run loops emit "$VERTEX" experiment \
    commit="$(git rev-parse --short HEAD)" status=discard \
    description="No changes committed"
fi
