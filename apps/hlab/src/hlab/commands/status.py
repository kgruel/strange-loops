"""Status command — fetch homelab stack status.

Pure data fetch, no rendering knowledge.
"""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path

from engine import load_vertex_program

from ..folds import HEALTH_INITIAL, health_fold


HERE = Path(__file__).parent.parent
VERTEX_FILE = HERE / "loops/status.vertex"


def _load_program():
    """Load vertex program from DSL files."""
    return load_vertex_program(
        VERTEX_FILE,
        default_fold_override=(HEALTH_INITIAL, health_fold),
    )


def load():
    """Load vertex and sources from DSL files.

    Returns:
        tuple of (vertex, sources)
    """
    program = _load_program()
    return program.vertex, program.sources


def load_with_expected():
    """Load vertex and sources with expected stack names.

    Returns:
        tuple of (vertex, sources, expected_stack_names)
        Used by streaming mode for spinner display.
    """
    program = _load_program()
    return program.vertex, program.sources, program.expected_ticks


def make_fetcher(args=None) -> Callable[[], dict[str, dict]]:
    """Create a zero-arg fetcher for status data."""
    def fetch() -> dict[str, dict]:
        return _load_program().collect(rounds=1)
    return fetch
