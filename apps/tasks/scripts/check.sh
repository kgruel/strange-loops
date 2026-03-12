#!/usr/bin/env bash
# DESC: Format + lint + test (CI gate)
# Usage: ./dev check [-v]
source "$(dirname "$0")/lib/dev.sh"

VERBOSE=false
for arg in "$@"; do
    case "$arg" in
        -v|--verbose) VERBOSE=true ;;
    esac
done

run_step() {
    local label="$1"; shift
    step "$label"
    if $VERBOSE; then
        "$@"
    else
        output=$("$@" 2>&1)
    fi
    if [ $? -ne 0 ]; then
        fail "$label"
        $VERBOSE || echo "$output"
        exit 1
    fi
    ok "$label"
}

main() {
    cd "$DEV_ROOT"

    run_step "fmt"   bash "$DEV_ROOT/scripts/fmt.sh"
    run_step "lint"  bash "$DEV_ROOT/scripts/lint.sh"
    run_step "test"  bash "$DEV_ROOT/scripts/test.sh"

    echo ""
    ok "All checks passed"
}

main
