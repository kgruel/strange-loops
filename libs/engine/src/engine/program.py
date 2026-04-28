"""High-level helpers for running a .vertex program.

This module exists to reduce per-command boilerplate when wiring DSL sources
and vertices together.
"""

from __future__ import annotations

# pathlib deferred to function bodies
TYPE_CHECKING = False

from .compiler import FoldOverride, collect_all_sources, compile_vertex_recursive, materialize_vertex, substitute_vars
from lang import parse_vertex_file
from lang.ast import SourceParams, TemplateSource, VertexFile

if TYPE_CHECKING:
    from pathlib import Path
    from typing import Any, Callable
    from atoms import Fact, Source
    from .cadence import Cadence
    from .executor import SyncResult
    from .tick import Tick
    from .vertex import Vertex


# Dispatcher contract: (command, tick_name, vertex_path) -> None.
# Engine calls this when a tick with .run is born; implementation
# (e.g. subprocess execution) lives in the consumer.
RunDispatcher = "Callable[[str, str, Path], None]"


class VertexProgram:
    """A fully-materialized vertex plus its compiled sources with cadences.

    Carries an optional run_dispatcher callback. When set, ticks with
    .run produced by receive() or sync() are dispatched at the place
    they're born — no longer the caller's responsibility to remember.
    """

    __slots__ = ("vertex", "sources", "expected_ticks", "path", "run_dispatcher")

    def __init__(
        self,
        vertex: Vertex,
        sources: list[tuple[Source, Cadence]],
        expected_ticks: list[str],
        *,
        path: Path | None = None,
        run_dispatcher: Callable[[str, str, Path], None] | None = None,
    ):
        object.__setattr__(self, "vertex", vertex)
        object.__setattr__(self, "sources", sources)
        object.__setattr__(self, "expected_ticks", expected_ticks)
        object.__setattr__(self, "path", path)
        object.__setattr__(self, "run_dispatcher", run_dispatcher)

    def __setattr__(self, name, value):
        raise AttributeError(f"cannot assign to field '{name}'")

    def __repr__(self):
        return f"VertexProgram(vertex={self.vertex!r}, sources={self.sources!r})"

    @property
    def name(self) -> str:
        """Vertex name — exposed at program level so callers don't reach into .vertex."""
        return self.vertex.name

    @property
    def has_store(self) -> bool:
        """Whether the underlying vertex is backed by a durable store."""
        return getattr(self.vertex, "_store", None) is not None

    def _dispatch_tick(self, tick: Tick) -> None:
        """Fire run_dispatcher for a tick with .run, if dispatcher and path are set."""
        if self.run_dispatcher is None or self.path is None:
            return
        if not getattr(tick, "run", None):
            return
        self.run_dispatcher(tick.run, tick.name, self.path)

    def receive(self, fact: Fact, grant: Any = None) -> Tick | None:
        """Route a fact through the vertex; dispatch run-clause if the resulting tick has one.

        Single-fact entry that consolidates ``vertex.receive(fact)`` with
        run-clause dispatch. Use this in place of ``program.vertex.receive(fact)``
        from CLI/app code so any registered dispatcher fires automatically.
        """
        tick = self.vertex.receive(fact, grant) if grant is not None else self.vertex.receive(fact)
        if tick is not None:
            self._dispatch_tick(tick)
        return tick

    async def sync_async(
        self,
        grant: Any = None,
        *,
        on_error: Callable | None = None,
        force: bool = False,
    ) -> SyncResult:
        """One-shot sync: evaluate cadence, run qualifying sources, dispatch run-clauses."""
        from .executor import Executor

        executor = Executor(self.vertex, self.sources, on_error=on_error)
        result = await executor.sync_async(grant=grant, force=force)
        for tick in result.ticks:
            self._dispatch_tick(tick)
        return result

    def sync(
        self,
        grant: Any = None,
        *,
        on_error: Callable | None = None,
        force: bool = False,
    ) -> SyncResult:
        """Synchronous wrapper around sync_async."""
        import asyncio

        return asyncio.run(self.sync_async(grant, on_error=on_error, force=force))


def _substitute_vertex_vars(ast: VertexFile, vars: dict[str, str]) -> VertexFile:
    """Resolve {{var}} references in template source param values.

    Walks ast.sources, and for each TemplateSource, substitutes vars in
    each SourceParams.values dict's values. Returns a new VertexFile with
    resolved params. Non-template sources are passed through unchanged.
    """
    if not ast.sources:
        return ast

    new_sources: list = []
    for entry in ast.sources:
        if isinstance(entry, TemplateSource):
            new_params = tuple(
                SourceParams(
                    values={k: substitute_vars(v, vars) for k, v in row.values.items()}
                )
                for row in entry.params
            )
            new_sources.append(
                TemplateSource(
                    template=entry.template,
                    params=new_params,
                    from_=entry.from_,
                    loop=entry.loop,
                )
            )
        else:
            new_sources.append(entry)

    return VertexFile(
        name=ast.name,
        loops=ast.loops,
        store=ast.store,
        discover=ast.discover,
        sources=tuple(new_sources),
        vertices=ast.vertices,
        routes=ast.routes,
        emit=ast.emit,
        sources_blocks=ast.sources_blocks,
        path=ast.path,
    )


def load_vertex_program(
    vertex_path: Path,
    *,
    vars: dict[str, str] | None = None,
    fold_overrides: dict[str, FoldOverride] | None = None,
    default_fold_override: FoldOverride | None = None,
    validate_ast: bool = True,
    skip_sources: bool = False,
    run_dispatcher: Callable[[str, str, Path], None] | None = None,
) -> VertexProgram:
    """Load a .vertex file into a runnable (vertex, sources) program.

    Compiles template sources and merges any generated loop specs into the
    compiled vertex, then materializes a runtime Vertex.

    Args:
        vertex_path: Path to the .vertex file.
        vars: Optional dict of variables to substitute in template source
            param values before compilation. Resolves {{var}} references.
        fold_overrides: Optional per-kind fold overrides.
        default_fold_override: Optional override applied to all compiled kinds
            (unless overridden by fold_overrides).
        validate_ast: Whether to validate the parsed VertexFile AST.

    Returns:
        VertexProgram with materialized Vertex, compiled Sources, and
        expected tick names (sorted compiled spec keys).
    """
    ast = parse_vertex_file(vertex_path)
    if vars:
        ast = _substitute_vertex_vars(ast, vars)
    if validate_ast:
        from lang import validate
        validate(ast)

    compiled = compile_vertex_recursive(ast)
    if skip_sources:
        sources: list = []
    else:
        sources, template_specs = collect_all_sources(compiled)
        compiled.specs.update(template_specs)

        # Validate trigger dependencies form a DAG — fail early on cycles
        from .executor import validate_dependency_graph

        validate_dependency_graph(sources)

    overrides: dict[str, FoldOverride] = {}
    if default_fold_override is not None:
        overrides = {kind: default_fold_override for kind in compiled.specs.keys()}
    if fold_overrides:
        overrides.update(fold_overrides)

    vertex = materialize_vertex(compiled, fold_overrides=overrides or None)

    # Replay stored facts to rebuild fold state — makes one-shot CLI
    # invocations indistinguishable from a persistent runtime
    vertex.replay()

    # Only specs with boundaries produce ticks (boundary-less = memory pattern)
    expected_ticks = sorted(
        name for name, spec in compiled.specs.items() if spec.boundary is not None
    )
    return VertexProgram(
        vertex=vertex,
        sources=sources,
        expected_ticks=expected_ticks,
        path=vertex_path,
        run_dispatcher=run_dispatcher,
    )
