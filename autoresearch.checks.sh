#!/usr/bin/env bash
# Correctness checks for emit-path autoresearch.
# Must pass after every kept change.
set -euo pipefail

# Engine tests — vertex, store, replay, boundaries (587 tests)
uv run --package engine pytest libs/engine/tests -x -q

# Emit tests — fact routing through vertex stores (24 tests)
uv run --package loops pytest apps/loops/tests/test_emit.py -x -q

# Golden snapshot tests — output stability (41 tests)
uv run --package loops pytest apps/loops/tests/golden -x -q
