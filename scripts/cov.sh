#!/usr/bin/env bash
# DESC: Run tests with coverage report
# Usage: ./dev cov [--html]
source "$(dirname "$0")/lib/dev.sh"

main() {
    local html=0

    for arg in "$@"; do
        case "$arg" in
            --html) html=1 ;;
            --help|-h)
                echo "Usage: ./dev cov [--html]"
                echo "  --html  Generate HTML report in htmlcov/"
                exit 0
                ;;
        esac
    done

    cd "$PROJECT_ROOT"

    if [ $html -eq 1 ]; then
        run_uv pytest tests/ -q --cov=src/painted --cov-branch --cov-report=html --cov-report=term-missing
        echo -e "\n${BLUE}HTML report:${NC} htmlcov/index.html"
    else
        run_uv pytest tests/ -q --cov=src/painted --cov-branch --cov-report=term-missing
    fi
}

main "$@"
