#!/usr/bin/env bash
# DESC: Type check + format check
# Usage: ./dev lint
source "$(dirname "$0")/lib/dev.sh"

main() {
    cd "$DEV_ROOT"

    step "ty check"
    run_uv ty check src/ 2>&1
    if [ $? -ne 0 ]; then fail "type check"; exit 1; fi
    ok "types"

    step "ruff format"
    run_uv ruff format --check src/ tests/ 2>&1
    if [ $? -ne 0 ]; then fail "formatting"; exit 1; fi
    ok "format"
}

main
