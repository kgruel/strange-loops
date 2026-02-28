#!/usr/bin/env bash
# DESC: Auto-fix lint + type check
# Usage: ./dev lint
source "$(dirname "$0")/lib/dev.sh"

main() {
    cd "$DEV_ROOT"

    step "ruff fix"
    run_uv ruff check --fix src/ tests/ 2>&1
    if [ $? -ne 0 ]; then fail "ruff fix"; exit 1; fi
    ok "ruff"

    step "ty check"
    run_uv ty check src/ 2>&1
    if [ $? -ne 0 ]; then fail "type check"; exit 1; fi
    ok "types"
}

main
