#!/usr/bin/env bash
# DESC: Run ty check + ruff format check
# Usage: ./dev lint
source "$(dirname "$0")/lib/dev.sh"

main() {
    cd "$PROJECT_ROOT"

    step "Types"
    run_uv ty check src/ > /dev/null 2>&1 && ok || { fail; run_uv ty check src/; exit 1; }

    step "Format"
    run_uv ruff format --check src/ tests/ > /dev/null 2>&1 && ok || { fail; run_uv ruff format --check src/ tests/; exit 1; }

    echo -e "\n${GREEN}Lint clean${NC}"
}

main "$@"
