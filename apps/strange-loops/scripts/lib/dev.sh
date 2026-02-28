#!/usr/bin/env bash
# Shared dev helpers for strange-loops

DEV_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
SRC_DIR="$DEV_ROOT/src"
TESTS_DIR="$DEV_ROOT/tests"

# Colors (disabled if not a terminal)
if [ -t 1 ]; then
    RED='\033[0;31m'; GREEN='\033[0;32m'; YELLOW='\033[0;33m'
    BLUE='\033[0;34m'; BOLD='\033[1m'; NC='\033[0m'
else
    RED=''; GREEN=''; YELLOW=''; BLUE=''; BOLD=''; NC=''
fi

ok()   { echo -e "${GREEN}[OK]${NC} $*"; }
fail() { echo -e "${RED}[FAIL]${NC} $*" >&2; }
step() { echo -e "${BLUE}[...]${NC} $*"; }
warn() { echo -e "${YELLOW}[WARN]${NC} $*" >&2; }

run_uv() {
    uv run --package strange-loops "$@"
}

require_command() {
    local name="$1" hint="$2"
    if ! command -v "$name" &>/dev/null; then
        fail "$name not found. $hint"
        exit 1
    fi
}
