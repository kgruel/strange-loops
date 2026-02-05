"""Validator for DSL AST.

Validates:
1. Syntax — well-formed, known operations
2. Flow — operations in valid order (can't pick before split)
3. Shape inference — track types through parse pipeline
4. Cross-reference — routes reference defined loops, etc.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum, auto
from typing import TYPE_CHECKING

from .ast import (
    Coerce,
    Explode,
    LoopFile,
    ParseStep,
    Pick,
    Project,
    Skip,
    Split,
    Transform,
    VertexFile,
    Where,
)
from .errors import Location, ValidationError

if TYPE_CHECKING:
    pass


# -----------------------------------------------------------------------------
# Shape Types — track data shape through parse pipeline
# -----------------------------------------------------------------------------


class ShapeKind(Enum):
    """Kind of data shape."""

    STRING = auto()  # raw string (line)
    LIST = auto()  # list of strings (after split)
    DICT = auto()  # dict with named fields (after pick with names)


@dataclass
class Shape:
    """Data shape at a point in the parse pipeline."""

    kind: ShapeKind
    fields: tuple[str, ...] | None = None  # Field names if DICT
    field_types: dict[str, str] | None = None  # Field name -> type if known

    @classmethod
    def string(cls) -> Shape:
        """Initial shape: raw string."""
        return cls(ShapeKind.STRING)

    @classmethod
    def list(cls) -> Shape:
        """After split: list of strings."""
        return cls(ShapeKind.LIST)

    @classmethod
    def dict_shape(cls, fields: tuple[str, ...]) -> Shape:
        """After pick with names: dict with known fields."""
        return cls(ShapeKind.DICT, fields=fields, field_types={f: "str" for f in fields})

    def with_field_type(self, field: str, type_: str) -> Shape:
        """Return new shape with updated field type."""
        if self.kind != ShapeKind.DICT:
            raise ValueError("Cannot set field type on non-dict shape")
        new_types = dict(self.field_types or {})
        new_types[field] = type_
        return Shape(self.kind, self.fields, new_types)


# -----------------------------------------------------------------------------
# Validation Context
# -----------------------------------------------------------------------------


@dataclass
class ValidationContext:
    """Context for validation, tracking state and errors."""

    path: str | None = None
    errors: list[ValidationError] | None = None

    def __post_init__(self):
        if self.errors is None:
            self.errors = []

    def error(self, message: str, line: int = 1, hint: str | None = None) -> None:
        """Record a validation error."""
        from pathlib import Path

        loc = Location(Path(self.path) if self.path else None, line)
        self.errors.append(ValidationError(message, loc, hint))

    def has_errors(self) -> bool:
        """Check if any errors were recorded."""
        return bool(self.errors)

    def raise_if_errors(self) -> None:
        """Raise first error if any were recorded."""
        if self.errors:
            raise self.errors[0]


# -----------------------------------------------------------------------------
# Parse Pipeline Validation
# -----------------------------------------------------------------------------


def validate_parse_flow(
    steps: tuple[ParseStep, ...],
    ctx: ValidationContext,
    *,
    initial_shape: Shape | None = None,
) -> Shape:
    """Validate parse step ordering and infer output shape.

    Rules:
    - skip only valid on STRING
    - split only valid on STRING, produces LIST
    - pick only valid on LIST, produces LIST or DICT (if names given)
    - transform only valid on DICT, requires field to exist
    - where, explode, project only valid on DICT
    """
    shape = initial_shape if initial_shape is not None else Shape.string()

    for i, step in enumerate(steps):
        step_num = i + 1  # 1-indexed for error messages

        if isinstance(step, Skip):
            if shape.kind != ShapeKind.STRING:
                ctx.error(
                    f"skip (step {step_num}) requires string input, got {shape.kind.name.lower()}",
                    hint="skip must come before split",
                )
            # skip doesn't change shape

        elif isinstance(step, Split):
            if shape.kind != ShapeKind.STRING:
                ctx.error(
                    f"split (step {step_num}) requires string input, got {shape.kind.name.lower()}",
                    hint="split should come after skip (if any) and before pick",
                )
            shape = Shape.list()

        elif isinstance(step, Pick):
            if shape.kind != ShapeKind.LIST:
                ctx.error(
                    f"pick (step {step_num}) requires list input, got {shape.kind.name.lower()}",
                    hint="add `split` before `pick`",
                )
            if step.names:
                shape = Shape.dict_shape(step.names)
            # If no names, stays as LIST

        elif isinstance(step, Transform):
            if shape.kind != ShapeKind.DICT:
                ctx.error(
                    f"transform '{step.field}:' (step {step_num}) requires dict input",
                    hint="use `pick ... -> names` to create named fields first",
                )
            elif shape.fields and step.field not in shape.fields:
                ctx.error(
                    f"transform references unknown field '{step.field}'",
                    hint=f"available fields: {', '.join(shape.fields)}",
                )
            else:
                # Infer type from transform chain
                result_type = "str"
                for op in step.operations:
                    if isinstance(op, Coerce):
                        result_type = op.type
                shape = shape.with_field_type(step.field, result_type)

        elif isinstance(step, Where):
            if shape.kind != ShapeKind.DICT:
                ctx.error(
                    f"where (step {step_num}) requires dict input",
                    hint="where operates on JSON/dict data",
                )
            # Where doesn't change shape

        elif isinstance(step, Explode):
            if shape.kind != ShapeKind.DICT:
                ctx.error(
                    f"explode (step {step_num}) requires dict input",
                    hint="explode operates on JSON/dict data",
                )
            # Explode produces dict output (element from the exploded list)
            shape = Shape(ShapeKind.DICT)

        elif isinstance(step, Project):
            if shape.kind != ShapeKind.DICT:
                ctx.error(
                    f"project (step {step_num}) requires dict input",
                    hint="project operates on JSON/dict data",
                )
            fields = tuple(step.fields.keys())
            shape = Shape.dict_shape(fields)

    return shape


# -----------------------------------------------------------------------------
# Loop File Validation
# -----------------------------------------------------------------------------


def validate_loop_file(loop: LoopFile) -> tuple[Shape | None, list[ValidationError]]:
    """Validate a .loop file.

    Returns (output_shape, errors).
    """
    ctx = ValidationContext(path=str(loop.path) if loop.path else None)

    # Validate on/every mutual exclusivity
    if loop.on is not None and loop.every is not None:
        ctx.error(
            "on: and every: are mutually exclusive",
            hint="Use on: to trigger from events, or every: for interval timing",
        )

    # Validate source requirement
    if loop.source is None and loop.every is None:
        ctx.error(
            "source: is required unless every: is present (pure timer loop)",
            hint="Add source: for the command to run, or every: for a timer-only loop",
        )

    # Validate parse pipeline
    output_shape = None
    if loop.parse:
        # JSON/ndjson formats start as dict, not string
        if loop.format in ("json", "ndjson"):
            initial = Shape(ShapeKind.DICT)
        else:
            initial = None  # default: string
        output_shape = validate_parse_flow(loop.parse, ctx, initial_shape=initial)

    # Validate format-specific constraints
    if loop.format == "json" and loop.parse:
        # JSON format with parse: pick should reference JSON keys, not indices
        for step in loop.parse:
            if isinstance(step, Split):
                ctx.error(
                    "split is not valid with format: json",
                    hint="JSON is already structured; use pick to select keys",
                )
            if isinstance(step, Skip):
                ctx.error(
                    "skip is not valid with format: json",
                    hint="JSON is already structured; filter in fold instead",
                )

    return output_shape, ctx.errors


# -----------------------------------------------------------------------------
# Vertex File Validation
# -----------------------------------------------------------------------------


def validate_vertex_file(vertex: VertexFile) -> list[ValidationError]:
    """Validate a .vertex file.

    Returns list of errors.
    """
    ctx = ValidationContext(path=str(vertex.path) if vertex.path else None)

    # Check routes reference defined loops
    if vertex.routes:
        for kind, loop_name in vertex.routes.items():
            if loop_name not in vertex.loops:
                ctx.error(
                    f"route '{kind}' references undefined loop '{loop_name}'",
                    hint=f"defined loops: {', '.join(vertex.loops.keys())}",
                )

    # Check each loop definition
    for loop_name, loop_def in vertex.loops.items():
        # Validate fold declarations
        if not loop_def.folds and loop_def.boundary is None:
            ctx.error(f"loop '{loop_name}' has no fold declarations")

        # Check for duplicate fold targets
        targets = [f.target for f in loop_def.folds]
        seen = set()
        for target in targets:
            if target in seen:
                ctx.error(f"loop '{loop_name}' has duplicate fold target '{target}'")
            seen.add(target)

    return ctx.errors


# -----------------------------------------------------------------------------
# Public API
# -----------------------------------------------------------------------------


def validate_loop(loop: LoopFile) -> Shape | None:
    """Validate a .loop file, raising on first error.

    Returns the output shape of the parse pipeline.
    """
    shape, errors = validate_loop_file(loop)
    if errors:
        raise errors[0]
    return shape


def validate_vertex(vertex: VertexFile) -> None:
    """Validate a .vertex file, raising on first error."""
    errors = validate_vertex_file(vertex)
    if errors:
        raise errors[0]


def validate(ast: LoopFile | VertexFile) -> Shape | None:
    """Validate any DSL AST, raising on first error.

    Returns output shape for LoopFile, None for VertexFile.
    """
    if isinstance(ast, LoopFile):
        return validate_loop(ast)
    else:
        validate_vertex(ast)
        return None
