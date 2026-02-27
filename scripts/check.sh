#!/usr/bin/env bash
# DESC: Fast-fail gate: arch → lint → unit → golden
# Usage: ./dev check [-v]
source "$(dirname "$0")/lib/dev.sh"

main() {
    local verbose=0

    for arg in "$@"; do
        case "$arg" in
            -v|--verbose) verbose=1 ;;
            --help|-h)
                echo "Usage: ./dev check [-v]"
                echo "  -v  Show verbose output on each step"
                exit 0
                ;;
        esac
    done

    cd "$PROJECT_ROOT"

    if [ $verbose -eq 1 ]; then
        echo -e "${BOLD}=== Architecture ===${NC}"
        run_uv pytest tests/unit/test_architecture_invariants.py -v --tb=short
        echo ""
        echo -e "${BOLD}=== Lint ===${NC}"
        run_uv ty check src/
        run_uv ruff format --check src/ tests/
        echo ""
        echo -e "${BOLD}=== Unit ===${NC}"
        run_uv pytest tests/unit/ -v --tb=short
        echo ""
        echo -e "${BOLD}=== Golden ===${NC}"
        run_uv pytest tests/golden/ -v --tb=short
    else
        step "Arch"
        run_uv pytest tests/unit/test_architecture_invariants.py -q --tb=line > /dev/null 2>&1 && ok || { fail; run_uv pytest tests/unit/test_architecture_invariants.py -v --tb=short; exit 1; }

        step "Lint"
        run_uv ty check src/ > /dev/null 2>&1 && run_uv ruff format --check src/ tests/ > /dev/null 2>&1 && ok || { fail; run_uv ty check src/; run_uv ruff format --check src/ tests/; exit 1; }

        step "Unit"
        run_uv pytest tests/unit/ -q --tb=line > /dev/null 2>&1 && ok || { fail; run_uv pytest tests/unit/ -q --tb=short; exit 1; }

        step "Golden"
        run_uv pytest tests/golden/ -q --tb=line > /dev/null 2>&1 && ok || { fail; run_uv pytest tests/golden/ -q --tb=short; exit 1; }
    fi

    echo -e "\n${GREEN}All checks passed${NC}"
}

main "$@"
