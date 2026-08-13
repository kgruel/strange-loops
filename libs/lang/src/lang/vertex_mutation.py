"""Public vertex-kind mutation API over the generic KDL splice layer.

Text-level add/edit/remove of loop-kind definitions in `.vertex` files,
plus a supported LoopDef-to-KDL serializer. Built on
``population.kdl_insert_child`` / ``kdl_remove_child`` — comments,
whitespace, and ordering of unrelated content are preserved.

Guarantees:
- Every mutation parses and validates the result before returning.
- Insert-then-remove round-trips to byte-identical text when the ``loops``
  block already exists across multiple lines.

Documented one-way limitation (expand-on-insert): adding a kind to a
single-line ``loops { ... }`` block expands it across lines (semantically
equivalent, not byte-identical). Editing or removing a kind inside a
single-line ``loops`` block is not supported — expand it first (any insert
does) or reformat by hand.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from .ast import (
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
)
from .population import kdl_find_block, kdl_insert_child, kdl_remove_child

if TYPE_CHECKING:
    from .ast import Boundary, BoundaryCondition, LoopDef

__all__ = [
    "add_vertex_kind",
    "edit_vertex_kind",
    "loop_def_to_kdl",
    "remove_vertex_kind",
]


# ---------------------------------------------------------------------------
# Names and string values
# ---------------------------------------------------------------------------

# Conservative bare-identifier subset of KDL. The splice layer matches
# children by first token, so quoted node names are not representable —
# names outside this set are rejected rather than escaped.
_BARE_NAME_CHARS = "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789_.-"

# Node names the loops block treats specially (never kind definitions).
_RESERVED_KIND_NAMES = frozenset({"boundary"})


def _validate_kind_name(kind: str) -> None:
    if not kind:
        raise ValueError("kind name is empty")
    if kind in _RESERVED_KIND_NAMES:
        raise ValueError(f"kind name {kind!r} is reserved inside the loops block")
    if kind[0].isdigit() or kind[0] in ".-":
        raise ValueError(
            f"kind name {kind!r} must start with a letter or underscore"
        )
    bad = set(kind) - set(_BARE_NAME_CHARS)
    if bad:
        raise ValueError(
            f"kind name {kind!r} contains characters KDL cannot represent "
            f"safely here: {sorted(bad)!r} (allowed: letters, digits, _ . -)"
        )


def _q(value: str, *, what: str) -> str:
    """Quote a string as a KDL string literal.

    Escapes backslash and double-quote; rejects control characters and
    newlines rather than escaping them (they cannot survive the line-based
    splice layer).
    """
    if any(ord(c) < 0x20 or ord(c) == 0x7F for c in value):
        raise ValueError(
            f"{what} {value!r} contains control characters or newlines, "
            "which are not representable in a single-line KDL value here"
        )
    return '"' + value.replace("\\", "\\\\").replace('"', '\\"') + '"'


def _num(value: float) -> str:
    """Emit a float as a KDL number, dropping a trailing .0 when integral."""
    if float(value).is_integer():
        return str(int(value))
    return repr(float(value))


# ---------------------------------------------------------------------------
# LoopDef -> KDL serializer
# ---------------------------------------------------------------------------


def _fold_op_kdl(target: str, op) -> str:
    q = _q
    t = _q(target, what="fold target") if set(target) - set(_BARE_NAME_CHARS) else target
    if isinstance(op, FoldCount):
        return f'{t} "count"'
    if isinstance(op, FoldLatest):
        return f'{t} "latest"'
    if isinstance(op, FoldBy):
        return f'{t} "by" {q(op.key_field, what="fold key_field")}'
    if isinstance(op, FoldSum):
        return f'{t} "sum" {q(op.field, what="fold field")}'
    if isinstance(op, FoldMax):
        return f'{t} "max" {q(op.field, what="fold field")}'
    if isinstance(op, FoldMin):
        return f'{t} "min" {q(op.field, what="fold field")}'
    if isinstance(op, FoldAvg):
        return f'{t} "avg" {q(op.field, what="fold field")}'
    if isinstance(op, FoldCollect):
        return f'{t} "collect" {int(op.max_items)}'
    if isinstance(op, FoldWindow):
        return f'{t} "window" {int(op.size)} {q(op.field, what="fold field")}'
    raise ValueError(f"Unknown fold op: {op!r}")


def _condition_kdl(cond: BoundaryCondition) -> str:
    value = (
        _num(cond.value)
        if isinstance(cond.value, (int, float))
        else _q(str(cond.value), what="condition value")
    )
    return (
        f'condition {_q(cond.target, what="condition target")} '
        f'{_q(cond.op, what="condition op")} {value}'
    )


def _boundary_kdl(boundary: Boundary, indent: str) -> list[str]:
    children: list[str] = []
    if isinstance(boundary, BoundaryWhen):
        head = f'boundary when={_q(boundary.kind, what="boundary kind")}'
        for k, v in boundary.match:
            if set(k) - set(_BARE_NAME_CHARS):
                raise ValueError(
                    f"boundary match field {k!r} is not a bare KDL identifier"
                )
            head += f' {k}={_q(v, what="boundary match value")}'
        children.extend(_condition_kdl(c) for c in boundary.conditions)
    elif isinstance(boundary, BoundaryAfter):
        head = f"boundary after={int(boundary.count)}"
    elif isinstance(boundary, BoundaryEvery):
        head = f"boundary every={int(boundary.count)}"
    else:
        raise ValueError(f"Unknown boundary: {boundary!r}")

    if boundary.run is not None:
        children.append(f'run {_q(boundary.run, what="boundary run command")}')

    if not children:
        return [head]
    lines = [head + " {"]
    lines.extend(indent + c for c in children)
    lines.append("}")
    return lines


def loop_def_to_kdl(kind: str, definition: LoopDef, indent: str = "  ") -> str:
    """Serialize a LoopDef as the KDL block ``<kind> { ... }``.

    The output re-parses (via the lang loader) to an equivalent LoopDef.
    Raises ValueError for names or values KDL cannot represent safely here,
    and for per-kind ``parse`` pipelines, which this serializer does not
    support.
    """
    _validate_kind_name(kind)
    if definition.parse:
        raise ValueError(
            "per-kind parse pipelines are not supported by loop_def_to_kdl; "
            "author the parse block by hand"
        )

    body: list[str] = []

    if definition.folds:
        body.append("fold {")
        for decl in definition.folds:
            body.append(indent + _fold_op_kdl(decl.target, decl.op))
        body.append("}")

    if definition.boundary is not None:
        body.extend(_boundary_kdl(definition.boundary, indent))

    if definition.search:
        body.append(
            "search "
            + " ".join(_q(f, what="search field") for f in definition.search)
        )

    if definition.preview_fields:
        body.append(
            "preview "
            + " ".join(_q(f, what="preview field") for f in definition.preview_fields)
        )

    for edge in definition.edges:
        body.append(
            f'edge {_q(edge.field, what="edge field")} '
            f'targets={_q(edge.target, what="edge target")}'
        )

    if definition.lifecycle is not None:
        lc = definition.lifecycle
        for v in lc.active:
            if "," in v or v != v.strip() or not v:
                raise ValueError(
                    f"lifecycle active value {v!r} cannot round-trip through "
                    "the comma-separated active= property"
                )
        active = ",".join(lc.active)
        body.append(
            f'lifecycle {_q(lc.field, what="lifecycle field")} '
            f'active={_q(active, what="lifecycle active set")}'
        )

    if not body:
        return f"{kind} {{ }}"
    lines = [f"{kind} {{"]
    lines.extend(indent + ln for ln in body)
    lines.append("}")
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Mutations
# ---------------------------------------------------------------------------


def _validated(text: str, context: str) -> str:
    """Parse + validate mutated vertex text; return it unchanged on success."""
    from .loader import parse_vertex
    from .validator import validate_vertex

    try:
        vf = parse_vertex(text)
        validate_vertex(vf)
    except Exception as exc:
        raise ValueError(
            f"{context} produced an invalid vertex: {exc}"
        ) from exc
    return text


def _kind_exists(text: str, kind: str) -> bool:
    from .loader import parse_vertex

    return kind in parse_vertex(text).loops


def add_vertex_kind(text: str, kind: str, definition: LoopDef) -> str:
    """Add a loop-kind definition to vertex text; returns the new text.

    Creates the ``loops`` block (appended at end of file) when absent.
    Refuses if the kind already exists. Note the one-way expand-on-insert
    limitation: a single-line ``loops { ... }`` block is expanded across
    lines by the insert.
    """
    _validate_kind_name(kind)
    if _kind_exists(text, kind):
        raise ValueError(f"kind {kind!r} already exists; use edit_vertex_kind")

    child = loop_def_to_kdl(kind, definition)
    try:
        kdl_find_block(text, ["loops"])
        has_loops = True
    except ValueError:
        has_loops = False
    if has_loops:
        result = kdl_insert_child(text, ["loops"], child)
    else:
        # No loops block — create one at end of file.
        indented = "\n".join(
            ("  " + ln) if ln.strip() else ln for ln in child.splitlines()
        )
        block = f"loops {{\n{indented}\n}}\n"
        if text and not text.endswith("\n"):
            text += "\n"
        result = text + block
    return _validated(result, f"add_vertex_kind({kind!r})")


def edit_vertex_kind(text: str, kind: str, definition: LoopDef) -> str:
    """Replace an existing kind's definition in place; returns the new text.

    Preserves the kind's position and all surrounding content. Not
    supported when the whole ``loops`` block is a single line (the
    documented expand-on-insert limitation is one-way).
    """
    _validate_kind_name(kind)
    try:
        start, end = kdl_find_block(text, ["loops", kind])
    except ValueError as exc:
        raise ValueError(
            f"kind {kind!r} not found in loops block (single-line loops "
            "blocks cannot be edited in place — expand across lines first): "
            f"{exc}"
        ) from exc

    lines = text.splitlines()
    kind_indent = lines[start][: len(lines[start]) - len(lines[start].lstrip())]
    child = loop_def_to_kdl(kind, definition)
    new_lines = [
        (kind_indent + ln) if ln.strip() else ln for ln in child.splitlines()
    ]
    lines[start : end + 1] = new_lines
    result = "\n".join(lines)
    if text.endswith("\n"):
        result += "\n"
    return _validated(result, f"edit_vertex_kind({kind!r})")


def remove_vertex_kind(text: str, kind: str) -> str:
    """Remove a kind's definition from vertex text; returns the new text.

    Not supported when the whole ``loops`` block is a single line. Refuses
    (via post-validation) when removal would leave an invalid vertex, e.g.
    removing the last kind of a vertex with no other sources.
    """
    _validate_kind_name(kind)
    try:
        result = kdl_remove_child(text, ["loops"], kind)
    except ValueError as exc:
        raise ValueError(
            f"kind {kind!r} not found in loops block (single-line loops "
            "blocks cannot be mutated in place — expand across lines first): "
            f"{exc}"
        ) from exc
    return _validated(result, f"remove_vertex_kind({kind!r})")
