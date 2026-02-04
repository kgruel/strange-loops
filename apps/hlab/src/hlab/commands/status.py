"""Status command — fetch homelab stack status.

Pure data fetch, no rendering knowledge.
"""

from __future__ import annotations

import asyncio
from collections.abc import Callable
from pathlib import Path

from dsl import load_vertex_program
from data import Runner

from ..folds import HEALTH_INITIAL, health_fold


HERE = Path(__file__).parent.parent
VERTEX_FILE = HERE / "loops/status.vertex"


def load():
    """Load vertex and sources from DSL files.

    Returns:
        tuple of (vertex, sources)
    """
    program = load_vertex_program(
        VERTEX_FILE,
        default_fold_override=(HEALTH_INITIAL, health_fold),
    )
    return program.vertex, program.sources


def load_with_expected():
    """Load vertex and sources with expected stack names.

    Returns:
        tuple of (vertex, sources, expected_stack_names)
        Used by streaming mode for spinner display.
    """
    program = load_vertex_program(
        VERTEX_FILE,
        default_fold_override=(HEALTH_INITIAL, health_fold),
    )
    return program.vertex, program.sources, program.expected_ticks


def make_fetcher(args=None) -> Callable[[], dict[str, dict]]:
    """Create a zero-arg fetcher for status data."""
    def fetch() -> dict[str, dict]:
        return asyncio.run(_fetch_stacks())
    return fetch


async def _fetch_stacks() -> dict[str, dict]:
    """Fetch all stacks and return {stack_name: payload}.

    This is pure data fetch with no rendering knowledge.
    payload = {containers: [...], healthy: N, total: M}
    """
    vertex, sources = load()
    runner = Runner(vertex)
    for s in sources:
        runner.add(s)

    stacks = {}
    async for tick in runner.run():
        stacks[tick.name] = tick.payload
    return stacks
