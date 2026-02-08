"""High-level helpers for running a .vertex program.

This module exists to reduce per-command boilerplate when wiring DSL sources
and vertices together.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Any, Callable

from .compiler import FoldOverride, compile_sources, compile_vertex_recursive, materialize_vertex
from lang import parse_vertex_file
from lang import validate

if TYPE_CHECKING:
    from atoms import Source
    from .tick import Tick
    from .vertex import Vertex


@dataclass(frozen=True)
class VertexProgram:
    """A fully-materialized vertex plus its compiled sources."""

    vertex: Vertex
    sources: list[Source]
    expected_ticks: list[str]

    @property
    def has_polling(self) -> bool:
        """True if any source uses interval-based polling."""
        return any(s.every is not None for s in self.sources)

    async def run(
        self, grant: Any = None, *, on_error: Callable | None = None,
    ) -> AsyncIterator[Tick]:
        """Run all sources and yield ticks as boundaries fire."""
        from atoms import Runner

        runner = Runner(self.vertex, on_error=on_error)
        for source in self.sources:
            runner.add(source)
        async for tick in runner.run(grant):
            yield tick

    async def collect_async(
        self, *, rounds: int | None = None, grant: Any = None
    ) -> dict[str, Any]:
        """Run all sources, return {tick_name: payload}.

        Args:
            rounds: Number of complete rounds to collect. A round completes
                when every name in expected_ticks has fired at least once.
                None (default) = run until all sources exhaust.
            grant: Optional grant for identity gating.
        """
        results: dict[str, Any] = {}
        if rounds is None:
            async for tick in self.run(grant):
                results[tick.name] = tick.payload
            return results

        seen_this_round: set[str] = set()
        expected = set(self.expected_ticks)
        completed_rounds = 0

        async for tick in self.run(grant):
            results[tick.name] = tick.payload
            seen_this_round.add(tick.name)
            if seen_this_round >= expected:
                completed_rounds += 1
                if completed_rounds >= rounds:
                    break
                seen_this_round = set()

        return results

    def collect(
        self, *, rounds: int | None = None, grant: Any = None
    ) -> dict[str, Any]:
        """Run all sources synchronously, return {tick_name: payload}."""
        import asyncio

        return asyncio.run(self.collect_async(rounds=rounds, grant=grant))


def load_vertex_program(
    vertex_path: Path,
    *,
    fold_overrides: dict[str, FoldOverride] | None = None,
    default_fold_override: FoldOverride | None = None,
    validate_ast: bool = True,
) -> VertexProgram:
    """Load a .vertex file into a runnable (vertex, sources) program.

    Compiles template sources and merges any generated loop specs into the
    compiled vertex, then materializes a runtime Vertex.

    Args:
        vertex_path: Path to the .vertex file.
        fold_overrides: Optional per-kind fold overrides.
        default_fold_override: Optional override applied to all compiled kinds
            (unless overridden by fold_overrides).
        validate_ast: Whether to validate the parsed VertexFile AST.

    Returns:
        VertexProgram with materialized Vertex, compiled Sources, and
        expected tick names (sorted compiled spec keys).
    """
    ast = parse_vertex_file(vertex_path)
    if validate_ast:
        validate(ast)

    sources, template_specs = compile_sources(ast, vertex_path.parent)
    compiled = compile_vertex_recursive(ast)
    compiled.specs.update(template_specs)

    overrides: dict[str, FoldOverride] = {}
    if default_fold_override is not None:
        overrides = {kind: default_fold_override for kind in compiled.specs.keys()}
    if fold_overrides:
        overrides.update(fold_overrides)

    vertex = materialize_vertex(compiled, fold_overrides=overrides or None)
    # Only specs with boundaries produce ticks (boundary-less = memory pattern)
    expected_ticks = sorted(
        name for name, spec in compiled.specs.items() if spec.boundary is not None
    )
    return VertexProgram(vertex=vertex, sources=sources, expected_ticks=expected_ticks)
