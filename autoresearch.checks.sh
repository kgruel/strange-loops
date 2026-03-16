#!/usr/bin/env bash
set -euo pipefail
uv run --package engine pytest libs/engine/tests -x -q && uv run --package loops pytest apps/loops/tests -x -q --ignore=apps/loops/tests/test_health.py --ignore=apps/loops/tests/test_readiness_lens.py --ignore=apps/loops/tests/golden
