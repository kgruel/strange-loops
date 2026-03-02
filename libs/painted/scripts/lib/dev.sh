#!/usr/bin/env bash
# lib/dev.sh - Shared helpers for dev scripts
# Usage: source "$(dirname "$0")/lib/dev.sh"
# Dependencies: none
#
# Single entry point for dev scripts. Sources paths,
# provides logging helpers and uv runner.

set -euo pipefail

# Source paths
_LIB_DIR="$(dirname "${BASH_SOURCE[0]}")"
source "$_LIB_DIR/paths.sh"

# Colors (disabled if not a terminal)
if [ -t 1 ]; then
    RED=$'\033[0;31m'
    GREEN=$'\033[0;32m'
    YELLOW=$'\033[0;33m'
    BLUE=$'\033[0;34m'
    BOLD=$'\033[1m'
    DIM=$'\033[2m'
    NC=$'\033[0m'
else
    RED='' GREEN='' YELLOW='' BLUE='' BOLD='' DIM='' NC=''
fi

# Logging
ok()   { echo -e "${GREEN}ok${NC}"; }
fail() { echo -e "${RED}failed${NC}"; }
step() { printf "%s... " "$1"; }

# Run a command via uv in the project package
# Usage: run_uv <command> [args...]
run_uv() {
    uv run --package painted "$@"
}
