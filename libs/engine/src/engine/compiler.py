"""Compiler: compile DSL AST to runtime types.

Maps:
- LoopFile → Source + parse pipeline
- VertexFile loops → Spec instances
- DSL parse steps → runtime ParseOp
- DSL fold ops → runtime FoldOp
- VertexFile vertices → recursive child compilation
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Callable

from lang.ast import (
    BoundaryAfter,
    BoundaryEvery,
    BoundaryWhen,
    FoldAvg,
    FoldBy,
    FoldCollect,
    FoldCount,
    FoldLatest,
    FoldMax,
    FoldMin,
    FoldSum,
    FoldWindow,
    FromFile,
    InlineSource,
    LoopDef,
    LoopFile,
    Pick,
    Select,
    Skip,
    SourceParams,
    SourcesBlock,
    Split,
    TemplateSource,
    Transform,
    Trigger,
    VertexFile,
)
from lang.ast import Explode as DslExplode
from lang.ast import Project as DslProject
from lang.ast import Where as DslWhere
from lang.ast import Coerce as DslCoerce
from lang.ast import FoldOp as DslFoldOp
from lang.ast import LStrip as DslLStrip
from lang.ast import ParseStep as DslParseStep
from lang.ast import Replace as DslReplace
from lang.ast import RStrip as DslRStrip
from lang.ast import Strip as DslStrip

if TYPE_CHECKING:
    from atoms import Boundary, Field, Source, Spec
    from atoms import Coerce as RuntimeCoerce
    from atoms import FoldOp as RuntimeFoldOp
    from atoms import ParseOp as RuntimeParseOp
    from atoms import Pick as RuntimePick
    from atoms import Rename as RuntimeRename
    from atoms import Select as RuntimeSelect
    from atoms import Skip as RuntimeSkip
    from atoms import Split as RuntimeSplit
    from atoms import Transform as RuntimeTransform
    from .vertex import Vertex


# -----------------------------------------------------------------------------
# Parse Step Mapping
# -----------------------------------------------------------------------------


def map_skip(step: Skip) -> RuntimeSkip:
    """Map DSL Skip to runtime Skip."""
    from atoms import Skip as RuntimeSkip

    # DSL skip uses regex pattern
    # Runtime skip has startswith, contains, equals
    pattern = step.pattern

    # Detect pattern type
    if pattern.startswith("^"):
        # ^Foo means startswith
        return RuntimeSkip(startswith=pattern[1:])
    else:
        # Otherwise treat as contains
        return RuntimeSkip(contains=pattern)


def map_split(step: Split) -> RuntimeSplit:
    """Map DSL Split to runtime Split."""
    from atoms import Split as RuntimeSplit

    return RuntimeSplit(delim=step.delimiter)


def map_pick(step: Pick) -> tuple[RuntimePick, RuntimeRename | None]:
    """Map DSL Pick to runtime Pick + optional Rename.

    DSL: pick 0, 4, 5 -> fs, pct, mount
    Runtime: Pick(0, 4, 5) + Rename({0: "fs", 1: "pct", 2: "mount"})
    """
    from atoms import Pick as RuntimePick
    from atoms import Rename as RuntimeRename

    pick = RuntimePick(*step.indices)

    if step.names:
        # Create rename mapping: position in picked list -> name
        mapping = {i: name for i, name in enumerate(step.names)}
        rename = RuntimeRename(mapping)
        return pick, rename
    else:
        return pick, None


def map_transform(step: Transform) -> list[RuntimeTransform | RuntimeCoerce]:
    """Map DSL Transform to runtime Transform + Coerce ops.

    DSL: pct: strip "%" | int
    Runtime: Transform("pct", strip="%"), Coerce({"pct": int})
    """
    from atoms import Coerce as RuntimeCoerce
    from atoms import Transform as RuntimeTransform

    result: list[RuntimeTransform | RuntimeCoerce] = []

    # Collect transform operations for this field
    strip_chars = None
    lstrip_chars = None
    rstrip_chars = None
    replace_pair = None
    coerce_type = None

    for op in step.operations:
        if isinstance(op, DslStrip):
            strip_chars = op.chars
        elif isinstance(op, DslLStrip):
            lstrip_chars = op.chars
        elif isinstance(op, DslRStrip):
            rstrip_chars = op.chars
        elif isinstance(op, DslReplace):
            replace_pair = (op.old, op.new)
        elif isinstance(op, DslCoerce):
            # Map type name to Python type
            type_map = {"int": int, "float": float, "bool": bool, "str": str}
            coerce_type = type_map.get(op.type)

    # Create Transform if any string ops were specified
    if strip_chars or lstrip_chars or rstrip_chars or replace_pair:
        result.append(
            RuntimeTransform(
                field=step.field,
                strip=strip_chars,
                lstrip=lstrip_chars,
                rstrip=rstrip_chars,
                replace=replace_pair,
            )
        )

    # Create Coerce if type conversion was specified
    if coerce_type:
        result.append(RuntimeCoerce({step.field: coerce_type}))

    return result


def map_select(step: Select) -> RuntimeSelect:
    """Map DSL Select to runtime Select."""
    from atoms import Select as RuntimeSelect

    return RuntimeSelect(*step.fields)


def map_explode(step: DslExplode) -> "RuntimeParseOp":
    """Map DSL Explode to runtime Explode."""
    from atoms import Explode as RuntimeExplode

    return RuntimeExplode(path=step.path, carry=step.carry)


def map_project(step: DslProject) -> "RuntimeParseOp":
    """Map DSL Project to runtime Project."""
    from atoms import Project as RuntimeProject

    return RuntimeProject(fields=step.fields)


def map_where(step: DslWhere) -> "RuntimeParseOp":
    """Map DSL Where to runtime Where."""
    from atoms import Where as RuntimeWhere

    return RuntimeWhere(path=step.path, op=step.op, value=step.value)


def map_parse_steps(steps: tuple[DslParseStep, ...]) -> list[RuntimeParseOp]:
    """Map DSL parse steps to runtime parse ops."""
    result: list[RuntimeParseOp] = []

    for step in steps:
        if isinstance(step, Skip):
            result.append(map_skip(step))
        elif isinstance(step, Split):
            result.append(map_split(step))
        elif isinstance(step, Pick):
            pick, rename = map_pick(step)
            result.append(pick)
            if rename:
                result.append(rename)
        elif isinstance(step, Select):
            result.append(map_select(step))
        elif isinstance(step, Transform):
            result.extend(map_transform(step))
        elif isinstance(step, DslExplode):
            result.append(map_explode(step))
        elif isinstance(step, DslProject):
            result.append(map_project(step))
        elif isinstance(step, DslWhere):
            result.append(map_where(step))

    return result


# -----------------------------------------------------------------------------
# Fold Op Mapping
# -----------------------------------------------------------------------------


_FOLD_MAP: dict[type, tuple[Callable, str]] | None = None


def _get_fold_map() -> dict[type, tuple[Callable, str]]:
    """Lazy-build the DSL→runtime fold dispatch table."""
    global _FOLD_MAP  # noqa: PLW0603
    if _FOLD_MAP is not None:
        return _FOLD_MAP
    from atoms import Avg, Collect, Count, Latest, Max, Min, Sum, Upsert, Window

    _FOLD_MAP = {
        FoldBy:      (lambda t, op: Upsert(target=t, key=op.key_field), "dict"),
        FoldCount:   (lambda t, op: Count(target=t),                     "int"),
        FoldSum:     (lambda t, op: Sum(target=t, field=op.field),       "float"),
        FoldLatest:  (lambda t, op: Latest(target=t),                    "datetime"),
        FoldCollect: (lambda t, op: Collect(target=t, max=op.max_items), "list"),
        FoldMax:     (lambda t, op: Max(target=t, field=op.field),       "float"),
        FoldMin:     (lambda t, op: Min(target=t, field=op.field),       "float"),
        FoldAvg:     (lambda t, op: Avg(target=t, field=op.field),       "float"),
        FoldWindow:  (lambda t, op: Window(target=t, field=op.field, size=op.size), "list"),
    }
    return _FOLD_MAP


def map_fold_op(target: str, op: DslFoldOp) -> RuntimeFoldOp:
    """Map DSL FoldOp to runtime FoldOp."""
    entry = _get_fold_map().get(type(op))
    if entry is None:
        raise ValueError(f"Unknown fold op type: {type(op)}")
    return entry[0](target, op)


# -----------------------------------------------------------------------------
# Field Type Inference
# -----------------------------------------------------------------------------


def infer_field_type(target: str, op: DslFoldOp) -> str:
    """Infer the state field type from a fold op."""
    entry = _get_fold_map().get(type(op))
    return entry[1] if entry else "str"


# -----------------------------------------------------------------------------
# LoopFile Mapping
# -----------------------------------------------------------------------------


def map_loop_file(loop: LoopFile) -> Source:
    """Map LoopFile AST to runtime Source.

    Returns a Source configured with:
    - command: the shell command (None for pure timer)
    - kind: fact kind
    - observer: who observed
    - every: repeat interval (seconds)
    - trigger: kinds that trigger this source (for on: syntax)
    - format: output interpretation
    - parse: compiled parse pipeline

    Timing modes:
    - loop.every + no on: → polling source
    - loop.on + no every: → triggered source
    - loop.every + no source: → pure timer (emits ticks)
    """
    from atoms import Source
    from lang.ast import Duration

    # Validate format at compile time
    if loop.format not in ("lines", "json", "ndjson", "blob"):
        raise ValueError(
            f"format must be 'lines', 'json', 'ndjson', or 'blob', got {loop.format!r}"
        )

    # Compile parse pipeline
    parse_ops = map_parse_steps(loop.parse) if loop.parse else None

    # Map trigger if present
    trigger = None
    if loop.on is not None:
        trigger = loop.on.kinds

    return Source(
        command=loop.source,
        kind=loop.kind,
        observer=loop.observer,
        every=Duration.parse(loop.every).seconds() if loop.every else None,
        trigger=trigger,
        format=loop.format,
        parse=parse_ops,
        env=loop.env,
    )


# -----------------------------------------------------------------------------
# Template Instantiation
# -----------------------------------------------------------------------------


def substitute_vars(text: str, params: dict[str, str]) -> str:
    r"""Replace {{var}} with values from params."""
    import re

    def replacer(match: re.Match) -> str:
        key = match.group(1)
        if key in params:
            return params[key]
        # Leave unmatched variables as-is
        return match.group(0)

    return re.sub(r"\{\{(\w+)\}\}", replacer, text)


def instantiate_template(loop_ast: LoopFile, params: dict[str, str]) -> LoopFile:
    """Create a new LoopFile with variables substituted."""
    return LoopFile(
        kind=substitute_vars(loop_ast.kind, params),
        observer=substitute_vars(loop_ast.observer, params),
        source=substitute_vars(loop_ast.source, params) if loop_ast.source else None,
        every=substitute_vars(loop_ast.every, params) if loop_ast.every else None,
        on=loop_ast.on,
        format=substitute_vars(loop_ast.format, params),
        timeout=substitute_vars(loop_ast.timeout, params),
        env={k: substitute_vars(v, params) for k, v in loop_ast.env.items()} if loop_ast.env else None,
        parse=loop_ast.parse,
        path=loop_ast.path,
    )


def substitute_loop_def(loop_def: LoopDef, params: dict[str, str]) -> LoopDef:
    """Create a new LoopDef with boundary kind substituted."""
    from lang.ast import BoundaryWhen

    boundary = loop_def.boundary
    if boundary and isinstance(boundary, BoundaryWhen):
        # Substitute vars in the boundary kind
        new_kind = substitute_vars(boundary.kind, params)
        boundary = BoundaryWhen(kind=new_kind)

    return LoopDef(folds=loop_def.folds, boundary=boundary)


def _load_params_file(file_path: Path) -> list[SourceParams]:
    """Load parameter rows from an external file.

    File format:
    - Lines starting with # are comments
    - Blank lines are skipped
    - First content line is the header (whitespace-separated column names)
    - Subsequent lines are data rows
    - Last column gets remainder (handles URLs with query strings)
    """
    text = file_path.read_text()
    lines = text.splitlines()

    header: list[str] | None = None
    params: list[SourceParams] = []

    for lineno, raw in enumerate(lines, start=1):
        line = raw.strip()
        if not line or line.startswith("#"):
            continue

        if header is None:
            header = line.split()
            continue

        # Data row: split with limit so last column gets remainder
        parts = line.split(None, len(header) - 1)
        if len(parts) != len(header):
            raise ValueError(
                f"{file_path}:{lineno}: expected {len(header)} columns, got {len(parts)}"
            )
        params.append(SourceParams(values=dict(zip(header, parts))))

    return params


def compile_sources(
    vertex: VertexFile,
    base_dir: Path,
) -> tuple[list["Source"], dict[str, "Spec"]]:
    """Compile sources from a vertex, handling both paths and templates.

    Returns:
        (sources, specs) where specs contains any loop specs from templates
    """
    from lang import parse_loop_file

    sources: list["Source"] = []
    specs: dict[str, "Spec"] = {}

    for source_entry in vertex.sources or []:
        if isinstance(source_entry, TemplateSource):
            # Load template
            template_path = source_entry.template
            if not template_path.is_absolute():
                template_path = base_dir / template_path
            loop_ast = parse_loop_file(template_path)

            # Collect all params: from file first, then inline with rows
            all_params: list[SourceParams] = []
            if isinstance(source_entry.from_, FromFile):
                from_path = source_entry.from_.path
                if not from_path.is_absolute():
                    from_path = base_dir / from_path
                all_params.extend(_load_params_file(from_path))
            all_params.extend(source_entry.params)

            # Instantiate for each param row
            for param_row in all_params:
                instantiated = instantiate_template(loop_ast, param_row.values)
                sources.append(compile_loop(instantiated))

                # If template has a loop spec, create spec for this instance
                if source_entry.loop:
                    kind = param_row.values.get("kind")
                    if kind:
                        substituted_loop_def = substitute_loop_def(
                            source_entry.loop, param_row.values
                        )
                        specs[kind] = map_loop_def_to_spec(kind, substituted_loop_def)
        else:
            # Simple path
            loop_path = source_entry
            if not loop_path.is_absolute():
                loop_path = base_dir / loop_path
            loop_ast = parse_loop_file(loop_path)
            sources.append(compile_loop(loop_ast))

    return sources, specs


def compile_sources_block(block: SourcesBlock, vertex_name: str) -> "SequentialSource":
    """Compile a sources block with execution mode into a SequentialSource.

    Each inline source becomes a regular Source (one-shot, no polling).
    The SequentialSource wraps them with the execution mode semantics.
    """
    from atoms import Source as RuntimeSource
    from atoms import SequentialSource

    inner_sources = []
    for inline in block.sources:
        inner_sources.append(
            RuntimeSource(
                command=inline.command,
                kind=inline.kind,
                observer=vertex_name,
            )
        )

    return SequentialSource(
        sources=tuple(inner_sources),
        _observer=vertex_name,
    )


# -----------------------------------------------------------------------------
# VertexFile Mapping
# -----------------------------------------------------------------------------


def map_boundary(boundary: BoundaryWhen | BoundaryAfter | BoundaryEvery) -> Boundary:
    """Map DSL boundary to runtime Boundary."""
    from atoms import Boundary

    if isinstance(boundary, BoundaryWhen):
        return Boundary(kind=boundary.kind, mode="when", reset=True)
    elif isinstance(boundary, BoundaryAfter):
        return Boundary(count=boundary.count, mode="after", reset=True)
    elif isinstance(boundary, BoundaryEvery):
        return Boundary(count=boundary.count, mode="every", reset=True)
    else:
        raise ValueError(f"Unknown boundary type: {type(boundary)}")


def map_loop_def_to_spec(name: str, loop_def) -> Spec:
    """Map a VertexFile loop definition to a runtime Spec.

    The Spec includes:
    - name: loop name
    - state_fields: inferred from fold declarations
    - folds: compiled fold ops
    - boundary: optional boundary trigger
    """
    from atoms import Field, Spec

    # Build state fields from fold declarations
    state_fields = []
    folds = []

    for decl in loop_def.folds:
        # Infer field type
        field_type = infer_field_type(decl.target, decl.op)
        state_fields.append(Field(name=decl.target, kind=field_type))

        # Map fold op
        folds.append(map_fold_op(decl.target, decl.op))

    # Map boundary if present
    boundary = None
    if loop_def.boundary:
        boundary = map_boundary(loop_def.boundary)

    return Spec(
        name=name,
        about=f"Generated from DSL loop '{name}'",
        state_fields=tuple(state_fields),
        folds=tuple(folds),
        boundary=boundary,
    )


def map_vertex_file(vertex: VertexFile) -> dict[str, Spec]:
    """Map VertexFile AST to dict of Spec instances.

    Returns a dict mapping loop name to compiled Spec.
    """
    specs = {}
    for name, loop_def in vertex.loops.items():
        specs[name] = map_loop_def_to_spec(name, loop_def)
    return specs


# -----------------------------------------------------------------------------
# Compiled Vertex Tree
# -----------------------------------------------------------------------------


@dataclass
class CompiledVertex:
    """A compiled vertex with specs and nested children.

    Represents the result of recursively compiling a .vertex file
    and all its child vertices.
    """

    name: str
    specs: dict[str, Spec]
    children: dict[str, "CompiledVertex"]
    routes: dict[str, str] | None = None
    store: Path | None = None
    path: Path | None = None
    sources: list | None = None
    template_specs: dict | None = None


def collect_all_sources(compiled: CompiledVertex) -> tuple[list, dict]:
    """Collect sources and template specs from a compiled vertex tree."""
    sources = list(compiled.sources or [])
    specs = dict(compiled.template_specs or {})
    for child in compiled.children.values():
        child_sources, child_specs = collect_all_sources(child)
        sources.extend(child_sources)
        specs.update(child_specs)
    return sources, specs


class CircularVertexError(Exception):
    """Raised when vertex composition creates a cycle."""

    def __init__(self, path: Path, chain: list[Path]) -> None:
        chain_str = " → ".join(str(p) for p in chain)
        super().__init__(f"Circular vertex reference: {chain_str} → {path}")
        self.path = path
        self.chain = chain


def compile_vertex_recursive(
    vertex: VertexFile,
    *,
    _visited: set[Path] | None = None,
    _chain: list[Path] | None = None,
) -> CompiledVertex:
    """Recursively compile a .vertex file and all child vertices.

    Args:
        vertex: The parsed VertexFile AST
        _visited: Internal - tracks visited paths for cycle detection
        _chain: Internal - tracks current path for error messages

    Returns:
        CompiledVertex with specs and nested children

    Raises:
        CircularVertexError: If vertex composition creates a cycle

    Child vertices can be specified two ways:
        - vertices: explicit list of paths
        - discover: glob pattern matching .vertex files
    """
    from glob import glob as globfn

    from lang import parse_vertex_file

    # Initialize tracking on first call
    if _visited is None:
        _visited = set()
    if _chain is None:
        _chain = []

    # Check for cycles
    if vertex.path is not None:
        resolved = vertex.path.resolve()
        if resolved in _visited:
            raise CircularVertexError(resolved, _chain.copy())
        _visited.add(resolved)
        _chain.append(resolved)

    # Compile this vertex's specs
    specs = map_vertex_file(vertex)

    # Compile this vertex's own sources
    base_dir = vertex.path.parent if vertex.path else Path.cwd()
    own_sources, own_template_specs = compile_sources(vertex, base_dir)

    # Compile sources blocks (e.g. sources sequential { ... })
    for block in vertex.sources_blocks or []:
        own_sources.append(compile_sources_block(block, vertex.name))

    # Collect child vertex paths from explicit list and discovery
    child_paths: list[Path] = []

    # Add explicit vertices
    if vertex.vertices:
        for child_path in vertex.vertices:
            if not child_path.is_absolute():
                child_path = base_dir / child_path
            child_paths.append(child_path)

    # Discover vertices via glob pattern
    if vertex.discover:
        pattern = str(base_dir / vertex.discover)
        for discovered in globfn(pattern, recursive=True):
            discovered_path = Path(discovered)
            # Only include .vertex files from discover pattern
            if discovered_path.suffix == ".vertex":
                # Skip self-reference
                if vertex.path and discovered_path.resolve() == vertex.path.resolve():
                    continue
                # Avoid duplicates with explicit vertices
                if discovered_path.resolve() not in {p.resolve() for p in child_paths}:
                    child_paths.append(discovered_path)

    # Recursively compile children
    children: dict[str, CompiledVertex] = {}
    for child_path in child_paths:
        # Parse and compile child
        child_ast = parse_vertex_file(child_path)
        child_compiled = compile_vertex_recursive(
            child_ast,
            _visited=_visited,
            _chain=_chain.copy(),
        )
        children[child_compiled.name] = child_compiled

    return CompiledVertex(
        name=vertex.name,
        specs=specs,
        children=children,
        routes=vertex.routes,
        store=vertex.store,
        path=vertex.path,
        sources=own_sources or None,
        template_specs=own_template_specs or None,
    )


# -----------------------------------------------------------------------------
# Public API
# -----------------------------------------------------------------------------


def compile_loop(loop: LoopFile) -> Source:
    """Compile a .loop file to a runtime Source."""
    return map_loop_file(loop)


def compile_vertex(vertex: VertexFile) -> dict[str, Spec]:
    """Compile a .vertex file to runtime Spec instances.

    For simple cases without child vertices. Use compile_vertex_recursive
    for vertices with nested children.
    """
    return map_vertex_file(vertex)


def collect_search_fields(
    vertex: VertexFile, base_dir: Path
) -> dict[str, tuple[str, ...]]:
    """Collect search field declarations from a vertex and its templates.

    Returns {kind: (field1, field2, ...)} for kinds that declare search.
    Used by vertex_search to know which payload fields to extract for FTS5.
    """
    fields: dict[str, tuple[str, ...]] = {}

    # Direct loops
    for kind, loop_def in vertex.loops.items():
        if loop_def.search:
            fields[kind] = loop_def.search

    # Template loops — resolve params to get actual kind names
    for source_entry in vertex.sources or []:
        if isinstance(source_entry, TemplateSource):
            if source_entry.loop and source_entry.loop.search:
                all_params: list[SourceParams] = []
                if isinstance(source_entry.from_, FromFile):
                    from_path = source_entry.from_.path
                    if not from_path.is_absolute():
                        from_path = base_dir / from_path
                    if from_path.exists():
                        all_params.extend(_load_params_file(from_path))
                all_params.extend(source_entry.params)
                for param_row in all_params:
                    kind = param_row.values.get("kind")
                    if kind:
                        fields[kind] = source_entry.loop.search

    return fields


# -----------------------------------------------------------------------------
# Vertex Materialization
# -----------------------------------------------------------------------------


FoldOverride = tuple[dict, "Callable[[dict, dict], dict]"]
"""A fold override: (initial_state, fold_function)."""


def materialize_vertex(
    compiled: CompiledVertex,
    *,
    fold_overrides: dict[str, FoldOverride] | None = None,
) -> "Vertex":
    """Instantiate a runtime Vertex tree from a CompiledVertex.

    Creates a Vertex with all specs registered as fold engines, and
    recursively materializes child vertices via add_child().

    Args:
        compiled: The compiled vertex tree from compile_vertex_recursive
        fold_overrides: Optional dict mapping kind → (initial, fold_fn)
            to use custom fold functions instead of declarative Spec.apply.
            Useful when Spec's declarative folds can't express the logic.

    Returns:
        A fully wired Vertex with children attached. Child ticks will
        automatically become facts that re-enter the parent.

    Example:
        compiled = compile_vertex_recursive(parse_vertex_file("system.vertex"))
        vertex = materialize_vertex(compiled)

        # With custom folds:
        vertex = materialize_vertex(compiled, fold_overrides={
            "pulse": (PULSE_INITIAL, pulse_fold),
        })
    """
    from .loop import Loop
    from .projection import Projection
    from .vertex import Vertex

    store = None
    if compiled.store is not None:
        from atoms import Fact

        store_path = compiled.store
        if not store_path.is_absolute() and compiled.path is not None:
            store_path = compiled.path.parent / store_path

        if store_path.suffix in ('.db', '.sqlite'):
            from .sqlite_store import SqliteStore

            store = SqliteStore(
                path=store_path,
                serialize=Fact.to_dict,
                deserialize=Fact.from_dict,
            )
        else:
            from .store import EventStore

            store = EventStore(
                path=store_path,
                serialize=Fact.to_dict,
                deserialize=Fact.from_dict,
            )

    vertex = Vertex(compiled.name, store=store)
    overrides = fold_overrides or {}

    # Set pattern-based routes if specified
    if compiled.routes:
        vertex.set_routes(compiled.routes)

    # Register specs (or overrides) as fold engines
    for name, spec in compiled.specs.items():
        boundary = spec.boundary
        reset = boundary.reset if boundary else True

        if name in overrides:
            # Use custom fold
            initial, fold_fn = overrides[name]
            if boundary and boundary.count is not None:
                # Count-based boundary: use Loop
                loop = Loop(
                    name=name,
                    projection=Projection(initial, fold=fold_fn),
                    boundary_kind=boundary.kind,
                    boundary_count=boundary.count,
                    boundary_mode=boundary.mode,
                    reset=reset,
                )
                vertex.register_loop(loop)
            else:
                # Kind-based boundary: use register()
                vertex.register(
                    name,
                    initial,
                    fold_fn,
                    boundary=boundary.kind if boundary else None,
                    reset=reset,
                )
        else:
            # Use declarative Spec.apply
            if boundary and boundary.count is not None:
                # Count-based boundary: use Loop
                loop = Loop(
                    name=name,
                    projection=Projection(spec.initial_state(), fold=spec.apply),
                    boundary_kind=boundary.kind,
                    boundary_count=boundary.count,
                    boundary_mode=boundary.mode,
                    reset=reset,
                )
                vertex.register_loop(loop)
            else:
                # Kind-based boundary: use register()
                vertex.register(
                    name,
                    spec.initial_state(),
                    spec.apply,
                    boundary=boundary.kind if boundary else None,
                    reset=reset,
                )

    # Recursively materialize and attach children
    for child_name, child_compiled in compiled.children.items():
        # Pass down any overrides that match child kinds
        child_overrides = {
            k: v for k, v in overrides.items()
            if k in child_compiled.specs
        }
        child_vertex = materialize_vertex(
            child_compiled,
            fold_overrides=child_overrides if child_overrides else None,
        )
        vertex.add_child(child_vertex)

    return vertex
