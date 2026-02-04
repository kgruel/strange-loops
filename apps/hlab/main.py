"""hlab — homelab monitoring.

Usage:
    uv run python -m apps.hlab.main              # Styled output (default)
    uv run python -m apps.hlab.main -q           # Minimal one-liner
    uv run python -m apps.hlab.main -v           # Detailed with borders
    uv run python -m apps.hlab.main -vv          # Full detail
    uv run python -m apps.hlab.main -i           # Interactive TUI (q to quit)
    uv run python -m apps.hlab.main --json       # JSON output
    uv run python -m apps.hlab.main --plain      # No ANSI codes
"""

from __future__ import annotations

import sys

from .harness import run
from .commands.status import fetch_stacks, load_with_expected


def main() -> int:
    """Entry point for hlab status command."""
    return run(
        fetch_stacks,
        description="Homelab status monitoring",
        prog="hlab",
        loader=load_with_expected,
    )


if __name__ == "__main__":
    sys.exit(main())
