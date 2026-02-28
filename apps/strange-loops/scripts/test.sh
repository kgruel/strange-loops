#!/usr/bin/env bash
# DESC: Run tests
# Usage: ./dev test [pytest args...]
source "$(dirname "$0")/lib/dev.sh"

main() {
    cd "$DEV_ROOT"
    run_uv pytest "$@"
}

main "$@"
