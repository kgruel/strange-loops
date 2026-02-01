"""Mapper: compile DSL AST to runtime types.

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

from .ast import (
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
    LoopFile,
    Pick,
    Skip,
    Split,
    Transform,
    Trigger,
    VertexFile,
)
from .ast import Coerce as DslCoerce
from .ast import FoldOp as DslFoldOp
from .ast import LStrip as DslLStrip
from .ast import ParseStep as DslParseStep
from .ast import Replace as DslReplace
from .ast import RStrip as DslRStrip
from .ast import Strip as DslStrip

if TYPE_CHECKING:
    from data import Boundary, Field, Source, Spec
    from data import Coerce as RuntimeCoerce
    from data import FoldOp as RuntimeFoldOp
    from data import ParseOp as RuntimeParseOp
    from data import Pick as RuntimePick
    from data import Rename as RuntimeRename
    from data import Skip as RuntimeSkip
    from data import Split as RuntimeSplit
    from data import Transform as RuntimeTransform
    from vertex import Vertex


# -----------------------------------------------------------------------------
# Parse Step Mapping
# -----------------------------------------------------------------------------


def map_skip(step: Skip) -> RuntimeSkip:
    """Map DSL Skip to runtime Skip."""
    from data import Skip as RuntimeSkip

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
    from data import Split as RuntimeSplit

    return RuntimeSplit(delim=step.delimiter)


def map_pick(step: Pick) -> tuple[RuntimePick, RuntimeRename | None]:
    """Map DSL Pick to runtime Pick + optional Rename.

    DSL: pick 0, 4, 5 -> fs, pct, mount
    Runtime: Pick(0, 4, 5) + Rename({0: "fs", 1: "pct", 2: "mount"})
    """
    from data import Pick as RuntimePick
    from data import Rename as RuntimeRename

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
    from data import Coerce as RuntimeCoerce
    from data import Transform as RuntimeTransform

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
        elif isinstance(step, Transform):
            result.extend(map_transform(step))

    return result


# -----------------------------------------------------------------------------
# Fold Op Mapping
# -----------------------------------------------------------------------------


def map_fold_op(target: str, op: DslFoldOp) -> RuntimeFoldOp:
    """Map DSL FoldOp to runtime FoldOp."""
    from data import Avg, Collect, Count, Latest, Max, Min, Sum, Upsert, Window

    if isinstance(op, FoldBy):
        return Upsert(target=target, key=op.key_field)
    elif isinstance(op, FoldCount):
        return Count(target=target)
    elif isinstance(op, FoldSum):
        return Sum(target=target, field=op.field)
    elif isinstance(op, FoldLatest):
        return Latest(target=target)
    elif isinstance(op, FoldCollect):
        return Collect(target=target, max=op.max_items)
    elif isinstance(op, FoldMax):
        return Max(target=target, field=op.field)
    elif isinstance(op, FoldMin):
        return Min(target=target, field=op.field)
    elif isinstance(op, FoldAvg):
        return Avg(target=target, field=op.field)
    elif isinstance(op, FoldWindow):
        return Window(target=target, field=op.field, size=op.size)
    else:
        raise ValueError(f"Unknown fold op type: {type(op)}")


# -----------------------------------------------------------------------------
# Field Type Inference
# -----------------------------------------------------------------------------


def infer_field_type(target: str, op: DslFoldOp) -> str:
    """Infer the state field type from a fold op."""
    if isinstance(op, FoldBy):
        return "dict"
    elif isinstance(op, FoldCount):
        return "int"
    elif isinstance(op, FoldSum):
        return "float"  # Could be int, but float is safer
    elif isinstance(op, FoldLatest):
        return "datetime"
    elif isinstance(op, FoldCollect):
        return "list"
    elif isinstance(op, (FoldMax, FoldMin)):
        return "float"  # Numeric comparison
    elif isinstance(op, FoldAvg):
        return "float"  # Running average
    elif isinstance(op, FoldWindow):
        return "list"  # Sliding buffer
    else:
        return "str"


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
    from data import Source

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
        every=loop.every.seconds() if loop.every else None,
        trigger=trigger,
        format=loop.format,
        parse=parse_ops,
    )


# -----------------------------------------------------------------------------
# VertexFile Mapping
# -----------------------------------------------------------------------------


def map_boundary(boundary: BoundaryWhen) -> Boundary:
    """Map DSL boundary to runtime Boundary."""
    from data import Boundary

    return Boundary(kind=boundary.kind, reset=True)


def map_loop_def_to_spec(name: str, loop_def) -> Spec:
    """Map a VertexFile loop definition to a runtime Spec.

    The Spec includes:
    - name: loop name
    - state_fields: inferred from fold declarations
    - folds: compiled fold ops
    - boundary: optional boundary trigger
    """
    from data import Field, Spec

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
    path: Path | None = None


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

    from .parser import parse_vertex_file

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

    # Collect child vertex paths from explicit list and discovery
    base_dir = vertex.path.parent if vertex.path else Path.cwd()
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
        path=vertex.path,
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
    from vertex import Vertex

    vertex = Vertex(compiled.name)
    overrides = fold_overrides or {}

    # Register specs (or overrides) as fold engines
    for name, spec in compiled.specs.items():
        if name in overrides:
            # Use custom fold
            initial, fold_fn = overrides[name]
            boundary_kind = spec.boundary.kind if spec.boundary else None
            reset = spec.boundary.reset if spec.boundary else True
            vertex.register(
                name,
                initial,
                fold_fn,
                boundary=boundary_kind,
                reset=reset,
            )
        else:
            # Use declarative Spec.apply
            boundary_kind = spec.boundary.kind if spec.boundary else None
            reset = spec.boundary.reset if spec.boundary else True
            vertex.register(
                name,
                spec.initial_state(),
                spec.apply,
                boundary=boundary_kind,
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
