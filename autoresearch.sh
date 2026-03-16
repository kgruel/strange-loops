#!/bin/bash
set -euo pipefail

# Benchmark: ms per coverage point (lower is better)
# Secondary metrics track structural efficiency of the test suite:
# - test_loc: total Python test lines
# - test_loc_per_cov: lines of tests per covered item
# - cov_per_test_loc: covered items per test line

PYTHON=.venv/bin/python3
cd /Users/kaygee/Code/loops
rm -f .coverage .coverage.* coverage.json

# Warmup: compile .pyc files
$PYTHON -c "
import compileall
for d in ['libs/atoms/src', 'libs/engine/src', 'libs/lang/src', 'apps/loops/src',
          'libs/atoms/tests', 'libs/engine/tests', 'libs/lang/tests', 'apps/loops/tests']:
    compileall.compile_dir(d, quiet=2)
" 2>/dev/null

total_time=0

run_pkg() {
  local pkg=$1 test_dir=$2
  shift 2
  output=$(uv run --package "$pkg" pytest "$test_dir" -q \
    -W ignore::ResourceWarning \
    --cov=atoms --cov=engine --cov=lang --cov=loops \
    --cov-branch --cov-append \
    "$@" 2>&1)
  secs=$(echo "$output" | grep -oE '[0-9]+ passed in [0-9.]+s' | grep -oE '[0-9.]+s$' | tr -d 's')
  if [ -z "$secs" ]; then echo "FAILED: $output" >&2; exit 1; fi
  total_time=$(echo "$total_time + $secs" | bc)
}

run_pkg atoms libs/atoms/tests
run_pkg engine libs/engine/tests
run_pkg lang libs/lang/tests
run_pkg loops apps/loops/tests \
  --ignore=apps/loops/tests/test_health.py \
  --ignore=apps/loops/tests/test_readiness_lens.py \
  --ignore=apps/loops/tests/test_session.py \
  --ignore=apps/loops/tests/test_cli.py

uv run --package loops coverage json --quiet 2>/dev/null

total_cov=$($PYTHON -c "import json; d=json.load(open('coverage.json')); t=d['totals']; print(t['covered_lines'] + t['covered_branches'])")
branch_pct=$($PYTHON -c "import json; d=json.load(open('coverage.json')); t=d['totals']; print(f\"{t['covered_branches']/t['num_branches']*100:.1f}\")")
ms_per_cov=$($PYTHON -c "print(f'{$total_time * 1000 / $total_cov:.3f}' if $total_cov > 0 else '999')")

test_loc=$(find libs apps -path '*/tests/*.py' -type f -print0 | xargs -0 wc -l | tail -1 | awk '{print $1}')
test_loc_per_cov=$($PYTHON -c "print(f'{$test_loc / $total_cov:.4f}' if $total_cov > 0 else '999')")
cov_per_test_loc=$($PYTHON -c "print(f'{$total_cov / $test_loc:.4f}' if $test_loc > 0 else '0')")

echo "METRIC ms_per_cov=$ms_per_cov"
echo "METRIC total_secs=$total_time"
echo "METRIC branch_pct=$branch_pct"
echo "METRIC total_cov=$total_cov"
echo "METRIC test_loc=$test_loc"
echo "METRIC test_loc_per_cov=$test_loc_per_cov"
echo "METRIC cov_per_test_loc=$cov_per_test_loc"

rm -f .coverage .coverage.* coverage.json
