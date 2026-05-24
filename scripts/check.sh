#!/usr/bin/env bash
# DESC: Repo-wide checks — documentation drift (bin/gen-docs.py --check)
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"

echo "→ documentation drift check (cli-catalog + api-reference __all__ coverage)"
uv run --package loops python bin/gen-docs.py --check
