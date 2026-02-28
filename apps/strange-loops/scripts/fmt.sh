#!/usr/bin/env bash
# DESC: Auto-format code
# Usage: ./dev fmt
source "$(dirname "$0")/lib/dev.sh"

main() {
    cd "$DEV_ROOT"
    run_uv ruff format src/ tests/
    ok "formatted"
}

main
