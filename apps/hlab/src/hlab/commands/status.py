"""Status command — fetch homelab stack status.

Pure data fetch, no rendering knowledge.
"""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path

from engine import VertexProgram, load_vertex_program

from ..config import resolve_vars
from ..folds import HEALTH_INITIAL, health_fold


HERE = Path(__file__).parent.parent
VERTEX_FILE = HERE / "loops/status.vertex"


def _load_program():
    """Load vertex program from DSL files."""
    return load_vertex_program(
        VERTEX_FILE,
        vars=resolve_vars(),
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
    stack = getattr(args, "stack", None)
    want_stats = getattr(args, "stats", False)
    want_logs = getattr(args, "logs", False)

    def fetch() -> dict[str, dict]:
        program = _load_program()
        if stack:
            program = VertexProgram(
                vertex=program.vertex,
                sources=[(s, c) for s, c in program.sources if s.kind == stack],
                expected_ticks=[stack],
                path=program.path,
                run_dispatcher=program.run_dispatcher,
            )
        result = program.sync(force=True)
        results = {t.name: t.payload for t in result.ticks}

        if want_stats or want_logs:
            from .enrichment import enrich_all
            results = enrich_all(results, stats=want_stats, logs=want_logs)

        return results
    return fetch
