"""High-level helpers for running a .vertex program.

This module exists to reduce per-command boilerplate when wiring DSL sources
and vertices together.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Callable

from .mapper import FoldOverride, compile_sources, compile_vertex_recursive, materialize_vertex
from .parser import parse_vertex_file
from .validator import validate

if TYPE_CHECKING:
    from data import Source
    from vertex import Vertex


@dataclass(frozen=True)
class VertexProgram:
    """A fully-materialized vertex plus its compiled sources."""

    vertex: Vertex
    sources: list[Source]
    expected_ticks: list[str]


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
    expected_ticks = sorted(compiled.specs.keys())
    return VertexProgram(vertex=vertex, sources=sources, expected_ticks=expected_ticks)

