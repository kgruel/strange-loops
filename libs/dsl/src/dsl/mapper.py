"""Mapper: compile DSL AST to runtime types.

Maps:
- LoopFile → Source + parse pipeline
- VertexFile loops → Spec instances
- DSL parse steps → runtime ParseOp
- DSL fold ops → runtime FoldOp
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from .ast import (
    BoundaryWhen,
    FoldBy,
    FoldCollect,
    FoldCount,
    FoldLatest,
    FoldMax,
    FoldMin,
    FoldSum,
    LoopFile,
    Pick,
    Skip,
    Split,
    Transform,
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
    from data import Collect, Count, Latest, Max, Min, Sum, Upsert

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
    else:
        return "str"


# -----------------------------------------------------------------------------
# LoopFile Mapping
# -----------------------------------------------------------------------------


def map_loop_file(loop: LoopFile) -> Source:
    """Map LoopFile AST to runtime Source.

    Returns a Source configured with:
    - command: the shell command
    - kind: fact kind
    - observer: who observed
    - every: repeat interval (seconds)
    - format: output interpretation
    - parse: compiled parse pipeline
    """
    from data import Source

    # Compile parse pipeline
    parse_ops = map_parse_steps(loop.parse) if loop.parse else None

    return Source(
        command=loop.source,
        kind=loop.kind,
        observer=loop.observer,
        every=loop.every.seconds() if loop.every else None,
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
# Public API
# -----------------------------------------------------------------------------


def compile_loop(loop: LoopFile) -> Source:
    """Compile a .loop file to a runtime Source."""
    return map_loop_file(loop)


def compile_vertex(vertex: VertexFile) -> dict[str, Spec]:
    """Compile a .vertex file to runtime Spec instances."""
    return map_vertex_file(vertex)
