"""Status command — fetch homelab stack status.

Pure data fetch, no rendering knowledge.
"""

from __future__ import annotations

import asyncio
from collections.abc import Callable
from pathlib import Path

from dsl import parse_vertex_file, compile_vertex_recursive, compile_sources, materialize_vertex
from data import Runner

from ..folds import HEALTH_INITIAL, health_fold


HERE = Path(__file__).parent.parent
VERTEX_FILE = HERE / "loops/status.vertex"


def load():
    """Load vertex and sources from DSL files.

    Returns:
        tuple of (vertex, sources)
    """
    ast = parse_vertex_file(VERTEX_FILE)

    # Compile sources from the vertex file (handles templates and simple paths)
    sources, template_specs = compile_sources(ast, VERTEX_FILE.parent)

    # Compile the vertex tree
    compiled = compile_vertex_recursive(ast)

    # Merge template specs into compiled vertex specs
    compiled.specs.update(template_specs)

    # Override all stack folds with health computation
    fold_overrides = {
        kind: (HEALTH_INITIAL, health_fold)
        for kind in template_specs.keys()
    }
    vertex = materialize_vertex(compiled, fold_overrides=fold_overrides)

    return vertex, sources


def load_with_expected():
    """Load vertex and sources with expected stack names.

    Returns:
        tuple of (vertex, sources, expected_stack_names)
        Used by streaming mode for spinner display.
    """
    ast = parse_vertex_file(VERTEX_FILE)
    sources, template_specs = compile_sources(ast, VERTEX_FILE.parent)
    compiled = compile_vertex_recursive(ast)
    compiled.specs.update(template_specs)

    # Get expected stack names from template specs
    expected = list(template_specs.keys())

    fold_overrides = {
        kind: (HEALTH_INITIAL, health_fold)
        for kind in expected
    }
    vertex = materialize_vertex(compiled, fold_overrides=fold_overrides)

    return vertex, sources, expected


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
