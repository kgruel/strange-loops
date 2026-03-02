#!/usr/bin/env bash
# lib/paths.sh - Project path constants
# Usage: sourced by dev.sh
# Dependencies: none

PROJECT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
SRC_DIR="$PROJECT_ROOT/src/painted"
TESTS_DIR="$PROJECT_ROOT/tests"
