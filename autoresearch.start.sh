#!/usr/bin/env bash
set -euo pipefail

NAME="autoresearch/read-latency"
VERTEX=".loops/autoresearch/read-latency.vertex"
BRANCH="$(git rev-parse --abbrev-ref HEAD)"
WORKTREE="/tmp/loops-ar-$(echo $NAME | tr / -)"

# Create isolated workspace from current branch
echo "Creating worktree at $WORKTREE from $BRANCH..."
git worktree add "$WORKTREE" -b "autoresearch/$NAME-$(date +%Y%m%d)" "$BRANCH"
cd "$WORKTREE"

# Init submodules and sync deps
MAIN_REPO="$(git worktree list | head -1 | awk '{print $1}')"
git submodule update --init --recursive --reference "$MAIN_REPO/libs/painted" 2>/dev/null \
  || git submodule update --init --recursive
uv sync --package loops

# Kick off — the run wrapper handles agent + benchmark + emit
echo "Starting autoresearch loop..."
./autoresearch.run.sh

echo "Autoresearch running in $WORKTREE"
echo "Watch with: cd $WORKTREE && loops read autoresearch --live"
echo "Clean up with: git worktree remove $WORKTREE"
