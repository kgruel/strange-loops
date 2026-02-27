#!/usr/bin/env bash
# DESC: Auto-format code (ruff format)
# Usage: ./dev fmt
source "$(dirname "$0")/lib/dev.sh"

main() {
    cd "$PROJECT_ROOT"

    step "Format"
    run_uv ruff format src/ tests/ > /dev/null 2>&1 && ok || { fail; exit 1; }

    echo -e "\n${GREEN}Formatted${NC}"
}

main "$@"
