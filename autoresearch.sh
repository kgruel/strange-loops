#!/bin/bash
set -euo pipefail

# Test coverage efficiency benchmark (stairstep methodology)
#
# Primary metric: efficiency = test_LOC × test_time_s / covered_lines (lower = better)
#
# Timing and coverage are measured separately — coverage instrumentation adds
# ~1.7x overhead that would inflate the efficiency metric.
# Noise reduction: 1 warmup + N clean timed runs, take minimum.
# Parses pytest's internal duration ("N passed in X.XXs") to exclude uv overhead.
# Coverage is deterministic — one instrumented run, parsed separately.
#
# See autoresearch.md for full methodology.

# --- Target configuration ---
PKG="loops"
TEST_DIR="apps/loops/tests"
SRC_DIR="apps/loops/src/loops"
NUM_RUNS=2
PYTEST_EXTRA="--ignore=apps/loops/tests/golden"

# --- Pre-check: syntax errors in test files ---
# uv --quiet suppresses install/uninstall chatter while keeping subprocess stderr
# (py_compile errors) visible.
for f in $(find "$TEST_DIR" -name "test_*.py" -o -name "conftest.py"); do
    uv --quiet run python -c "import py_compile; py_compile.compile('$f', doraise=True)"
done

# --- Count test LOC (non-empty, non-comment lines) ---
TEST_LOC=0
for f in $(find "$TEST_DIR" -name "test_*.py" -o -name "conftest.py"); do
    LOC=$(grep -v '^\s*$' "$f" | grep -v '^\s*#' | wc -l | tr -d ' ')
    TEST_LOC=$((TEST_LOC + LOC))
done

# --- Warmup run (no coverage, primes caches + imports) ---
echo "Warmup run..."
rm -f .coverage coverage.json
uv --quiet run --package "$PKG" pytest "$TEST_DIR" ${PYTEST_EXTRA:-} -x -q --tb=short | tail -3

# --- Timed runs: clean pytest (no coverage instrumentation) ---
# Timing and coverage are measured separately. Coverage instrumentation adds
# ~1.7x overhead, which inflates the efficiency metric and distorts decisions.
TIMES=()
for i in $(seq 1 $NUM_RUNS); do
    echo "Timed run $i/$NUM_RUNS..."
    OUTPUT=$(uv --quiet run --package "$PKG" pytest "$TEST_DIR" ${PYTEST_EXTRA:-} -x -q --tb=short)
    echo "$OUTPUT" | tail -3
    # Extract pytest duration: "711 passed in 2.73s" or "711 passed, 1 warning in 2.73s"
    T=$(echo "$OUTPUT" | grep -oE 'in [0-9]+\.[0-9]+s' | tail -1 | sed 's/in //; s/s//')
    if [ -z "$T" ]; then
        echo "ERROR: Could not parse pytest duration"
        exit 1
    fi
    TIMES+=("$T")
    echo "  run $i: ${T}s"
done

# --- Take minimum time ---
TEST_TIME=$(python3 -c "print(min($( IFS=,; echo "${TIMES[*]}" )))")
echo "Times: ${TIMES[*]} → min: ${TEST_TIME}s"

# --- Coverage run: separate from timing (instrumentation adds ~1.7x overhead) ---
echo "Coverage run..."
rm -f .coverage coverage.json
uv --quiet run --package "$PKG" pytest "$TEST_DIR" ${PYTEST_EXTRA:-} -x -q --tb=short \
    --cov="$SRC_DIR" --cov-branch --cov-report=json | tail -3
COVERAGE_JSON=$(cat coverage.json)
rm -f coverage.json .coverage

# Parse all coverage fields in one Python call
read COVERED TOTAL MISS PCT BRANCH_COV BRANCH_TOTAL BRANCH_PCT <<< $(echo "$COVERAGE_JSON" | python3 -c "
import json, sys
d = json.load(sys.stdin)
t = d['totals']
nb = t.get('num_branches', 0)
cb = t.get('covered_branches', 0)
bpct = round(100 * cb / nb, 1) if nb > 0 else 0
print(t['covered_lines'], t['num_statements'], t['missing_lines'],
      round(t['percent_covered'], 1), cb, nb, bpct)
")

# Per-file miss breakdown
MISSING=$(echo "$COVERAGE_JSON" | python3 -c "
import json, sys
d = json.load(sys.stdin)
for fname, fdata in sorted(d['files'].items()):
    lines = fdata.get('missing_lines', [])
    if lines:
        short = fname.replace('libs/engine/src/', '')
        print(f'  {short}: {len(lines)} miss — L{\",\".join(str(l) for l in lines[:10])}{\"...\" if len(lines)>10 else \"\"}')
")

# --- Compute metrics ---
if [ "$COVERED" -eq 0 ]; then
    EFFICIENCY=99999
else
    EFFICIENCY=$(python3 -c "print(round($TEST_LOC * $TEST_TIME / $COVERED, 2))")
fi

echo ""
echo "=== Coverage Efficiency ($PKG) ==="
echo "Test LOC:        $TEST_LOC"
echo "Test time:       ${TEST_TIME}s (min of $NUM_RUNS runs, no coverage overhead)"
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
