#!/usr/bin/env bash
# DESC: Run tests (pytest wrapper, passthrough args)
# Usage: ./dev test [-v] [pytest args...]
source "$(dirname "$0")/lib/dev.sh"

main() {
    cd "$PROJECT_ROOT"

    if [ $# -eq 0 ]; then
        run_uv pytest tests/ -q
    else
        run_uv pytest tests/ "$@"
    fi
}

main "$@"
