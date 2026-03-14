#!/bin/bash
set -euo pipefail
uv run --with pytest --package loops pytest apps/loops/tests/test_fetch.py apps/loops/tests/test_cli.py -q
