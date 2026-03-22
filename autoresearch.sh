#!/bin/bash
set -euo pipefail

# Test coverage efficiency benchmark (stairstep methodology)
#
# Primary metric: efficiency = test_LOC × test_time_s / covered_lines (lower = better)
#
# Current target: atoms library
#
# Keep/discard rule (applied by caller, not this script):
#   covered_lines increased → keep (coverage gained)
#   covered_lines unchanged AND efficiency improved → keep
#   otherwise → discard
#
# See autoresearch.md for full methodology.

# --- Target configuration ---
PKG="atoms"
TEST_DIR="libs/atoms/tests"
SRC_DIR="libs/atoms/src/atoms"

# --- Pre-check: syntax errors in test files ---
for f in $(find "$TEST_DIR" -name "test_*.py" -o -name "conftest.py"); do
    uv run python -c "import py_compile; py_compile.compile('$f', doraise=True)"
done

# --- Count test LOC (non-empty, non-comment lines) ---
TEST_LOC=0
for f in $(find "$TEST_DIR" -name "test_*.py" -o -name "conftest.py"); do
    LOC=$(grep -v '^\s*$' "$f" | grep -v '^\s*#' | wc -l | tr -d ' ')
    TEST_LOC=$((TEST_LOC + LOC))
done

# --- Clean previous coverage data ---
rm -f .coverage coverage.json

# --- Run tests with coverage ---
echo "Running $PKG tests with coverage..."
START=$(uv run python -c "import time; print(time.monotonic())")

uv run --package "$PKG" pytest "$TEST_DIR" -x -q --tb=short \
    --cov="$SRC_DIR" --cov-branch --cov-report=json 2>&1 | tail -5

END=$(uv run python -c "import time; print(time.monotonic())")
TEST_TIME=$(uv run python -c "print(round($END - $START, 3))")

# --- Parse coverage results ---
COVERAGE_JSON=$(cat coverage.json)
rm -f coverage.json .coverage

COVERED=$(echo "$COVERAGE_JSON" | uv run python -c "import json,sys; d=json.load(sys.stdin); print(d['totals']['covered_lines'])")
TOTAL=$(  echo "$COVERAGE_JSON" | uv run python -c "import json,sys; d=json.load(sys.stdin); print(d['totals']['num_statements'])")
MISS=$(   echo "$COVERAGE_JSON" | uv run python -c "import json,sys; d=json.load(sys.stdin); print(d['totals']['missing_lines'])")
PCT=$(    echo "$COVERAGE_JSON" | uv run python -c "import json,sys; d=json.load(sys.stdin); print(round(d['totals']['percent_covered'], 1))")

BRANCH_COV=$(echo "$COVERAGE_JSON" | uv run python -c "
import json,sys; d=json.load(sys.stdin)
print(d['totals'].get('covered_branches', 0))
")
BRANCH_TOTAL=$(echo "$COVERAGE_JSON" | uv run python -c "
import json,sys; d=json.load(sys.stdin)
print(d['totals'].get('num_branches', 0))
")
BRANCH_PCT=$(echo "$COVERAGE_JSON" | uv run python -c "
import json,sys; d=json.load(sys.stdin)
t = d['totals']
nb = t.get('num_branches', 0); cb = t.get('covered_branches', 0)
print(round(100 * cb / nb, 1) if nb > 0 else 0)
")

# Per-file miss breakdown
MISSING=$(echo "$COVERAGE_JSON" | uv run python -c "
import json,sys
d=json.load(sys.stdin)
for fname, fdata in sorted(d['files'].items()):
    lines = fdata.get('missing_lines', [])
    if lines:
        short = fname.replace('libs/atoms/src/', '')
        print(f'  {short}: {len(lines)} miss — L{\",\".join(str(l) for l in lines[:10])}{\"...\" if len(lines)>10 else \"\"}')
")

# --- Compute metrics ---
if [ "$COVERED" -eq 0 ]; then
    EFFICIENCY=99999
else
    EFFICIENCY=$(uv run python -c "print(round($TEST_LOC * $TEST_TIME / $COVERED, 2))")
fi

echo ""
echo "=== Coverage Efficiency ($PKG) ==="
echo "Test LOC:        $TEST_LOC"
echo "Test time:       ${TEST_TIME}s"
echo "Covered lines:   $COVERED / $TOTAL"
echo "Missing lines:   $MISS"
echo "Coverage:        ${PCT}%"
echo "Branch coverage: ${BRANCH_PCT}% ($BRANCH_COV / $BRANCH_TOTAL)"
echo "Efficiency:      $EFFICIENCY"
echo ""
echo "Missing by file:"
echo "$MISSING"
echo ""
echo "METRIC efficiency=$EFFICIENCY"
echo "METRIC covered_lines=$COVERED"
echo "METRIC coverage_pct=$PCT"
echo "METRIC miss=$MISS"
echo "METRIC test_time_s=$TEST_TIME"
echo "METRIC test_loc=$TEST_LOC"
echo "METRIC branch_pct=$BRANCH_PCT"
