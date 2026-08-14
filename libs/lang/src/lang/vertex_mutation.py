"""Public vertex-kind mutation API over the generic KDL splice layer.

Text-level add/edit/remove of loop-kind definitions in `.vertex` files,
plus a LoopDef-to-KDL serializer whose supported domain is the declarative
kind surface: ``fold``, ``boundary``, ``search``, ``preview``, ``edge``,
and ``lifecycle``. Per-kind ``parse`` pipelines are OUTSIDE that domain by
contract — serializing a ``LoopDef`` with a parse pipeline raises
``ValueError`` (a documented refusal, not a round-trip gap; zero corpus
usage, scope-the-claim). Built on
``population.kdl_insert_child`` / ``kdl_remove_child`` — comments,
whitespace, and ordering of unrelated content are preserved.

Guarantees:
- Every mutation parses and validates the result before returning, and the
  PARSER is the safety oracle: the pre-mutation and post-mutation parses
  are compared and only the exact requested delta is admissible — sibling
  kinds and non-kind content must be definition-equal or the mutation
  raises and the original text stands (SOL-R2-01 arbiter ruling:
  construction over detection; the lexical splice layer is best-effort
  transformation only and carries no safety claim).
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
from .population import (
    kdl_find_block,
    kdl_insert_child,
    kdl_remove_child,
    kdl_split_top_level_nodes,
)

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
_BARE_NAME_CHARS = frozenset(
    "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789_.-"
)

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
    bad = set(kind) - _BARE_NAME_CHARS
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
    t = _q(target, what="fold target") if set(target) - _BARE_NAME_CHARS else target
    if isinstance(op, FoldCount):
        return f'{t} "count"'
    if isinstance(op, FoldLatest):
        return f'{t} "latest"'
    if isinstance(op, FoldBy):
        return f'{t} "by" {_q(op.key_field, what="fold key_field")}'
    if isinstance(op, FoldSum):
        return f'{t} "sum" {_q(op.field, what="fold field")}'
    if isinstance(op, FoldMax):
        return f'{t} "max" {_q(op.field, what="fold field")}'
    if isinstance(op, FoldMin):
        return f'{t} "min" {_q(op.field, what="fold field")}'
    if isinstance(op, FoldAvg):
        return f'{t} "avg" {_q(op.field, what="fold field")}'
    if isinstance(op, FoldCollect):
        return f'{t} "collect" {int(op.max_items)}'
    if isinstance(op, FoldWindow):
        return f'{t} "window" {int(op.size)} {_q(op.field, what="fold field")}'
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
            if set(k) - _BARE_NAME_CHARS:
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

    Supported domain (the declarative kind surface): ``fold``, ``boundary``,
    ``search``, ``preview``, ``edge``, and ``lifecycle``. Within that
    domain, the output re-parses (via the lang loader) to an equivalent
    LoopDef.

    Per-kind ``parse`` pipelines are OUTSIDE the supported domain by
    contract: passing a LoopDef with a parse pipeline raises ValueError.
    This is a documented refusal, not a round-trip gap — no full-LoopDef
    round-trip is claimed. Also raises ValueError for names or values KDL
    cannot represent safely here.
    """
    _validate_kind_name(kind)
    if definition.parse:
        raise ValueError(
            "loop_def_to_kdl serializes the declarative kind surface only "
            "(fold/boundary/search/preview/edge/lifecycle); per-kind parse "
            "pipelines are outside its supported domain by contract — "
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


def _parse_vertex_or_raise(text: str, context: str):
    """Parse vertex text, wrapping parser errors as a clear ValueError."""
    from .loader import parse_vertex

    try:
        return parse_vertex(text)
    except Exception as exc:
        raise ValueError(
            f"{context}: input is not a parseable vertex: {exc}"
        ) from exc


def _loops_block_child_names(text: str) -> list[str]:
    """First tokens of every depth-0 child node in the ``loops`` block.

    Raw-text multiplicity view — the one thing the parser oracle cannot see
    (duplicate kind nodes collapse last-wins in the parse). Line-based and
    brace-counted like the splice layer; comment tokens are skipped. Empty
    when there is no ``loops`` block.
    """
    try:
        start, end = kdl_find_block(text, ["loops"])
    except ValueError:
        return []
    lines = text.splitlines()
    names: list[str] = []

    def _collect_line_nodes(segment: str) -> None:
        for node in kdl_split_top_level_nodes(segment):
            tok = node.split(None, 1)[0].split("{", 1)[0]
            if tok and not tok.startswith("/"):
                names.append(tok)

    if start == end:
        line = lines[start]
        _collect_line_nodes(line[line.index("{") + 1 : line.rindex("}")])
        return names

    i = start + 1
    while i < end:
        stripped = lines[i].strip()
        if not stripped or stripped.startswith("//"):
            i += 1
            continue
        opens = stripped.count("{") - stripped.count("}")
        if opens > 0:
            tok = stripped.split(None, 1)[0].split("{", 1)[0]
            if tok and not tok.startswith("/"):
                names.append(tok)
            depth = opens
            i += 1
            while i < end and depth > 0:
                depth += lines[i].count("{") - lines[i].count("}")
                i += 1
            continue
        _collect_line_nodes(stripped)
        i += 1
    return names


def _assert_unique_kind_nodes(text: str, context: str) -> None:
    """Refuse duplicate loop-kind nodes in the INPUT (SOL-R3-01 part a).

    The parser collapses duplicate kind names last-wins, so the parser
    oracle is structurally blind to them: a splice that loses one physical
    duplicate parses definition-equal. Duplicates in the input are
    pathological — a pre-condition refusal on the raw text, not a safety
    detector; the parser oracle remains the post-condition authority.
    """
    from collections import Counter

    counted = Counter(
        n for n in _loops_block_child_names(text)
        if n not in _RESERVED_KIND_NAMES
    )
    dupes = sorted(n for n, c in counted.items() if c > 1)
    if dupes:
        raise ValueError(
            f"{context}: duplicate loop-kind declaration(s) {dupes} in the "
            "loops block — the parser resolves duplicates last-wins, so a "
            "text mutation over them cannot be verified; deduplicate the "
            "vertex by hand first"
        )


def _has_comment_outside_strings(s: str) -> bool:
    """Quote-aware scan for KDL comment openers (``//``, ``/*``, ``/-``)."""
    in_str = esc = False
    for i, ch in enumerate(s):
        if in_str:
            if esc:
                esc = False
            elif ch == "\\":
                esc = True
            elif ch == '"':
                in_str = False
        elif ch == '"':
            in_str = True
        elif ch == "/" and i + 1 < len(s) and s[i + 1] in "/*-":
            return True
    return False


def _verified(
    before,
    result: str,
    context: str,
    *,
    added: str | None = None,
    edited: str | None = None,
    removed: str | None = None,
    definition=None,
) -> str:
    """Parse + validate mutated text AND assert the exact expected delta.

    The PARSER is the safety oracle (arbiter ruling, SOL-R2-01): the
    line/lexeme-based splice layer is best-effort transformation only, so
    every mutation re-parses the result and compares it against the
    pre-mutation parse. The only admissible delta is the requested one —
    add: original kind set plus the new kind, every original definition
    equal; edit: same kind set, only the target changed; remove: set minus
    the target, every other definition equal. Non-loop content (sources,
    routes, store, …) must be untouched in all three. Any mismatch raises
    ValueError naming the preserved-content violation, and the caller's
    original text is never replaced. This makes silent sibling loss
    inexpressible regardless of lexical evasion class (raw strings,
    escaped quotes, comments).
    """
    from .validator import validate_vertex

    try:
        after = _parse_vertex_or_raise(result, context)
        validate_vertex(after)
    except Exception as exc:
        raise ValueError(
            f"{context} produced an invalid vertex: {exc}"
        ) from exc

    before_kinds = set(before.loops)
    expected = set(before_kinds)
    if added is not None:
        expected.add(added)
    if removed is not None:
        expected.discard(removed)
    after_kinds = set(after.loops)
    if after_kinds != expected:
        lost = sorted(expected - after_kinds)
        gained = sorted(after_kinds - expected)
        raise ValueError(
            f"{context} violated content preservation: resulting kind set "
            f"differs from the expected delta (lost: {lost}, unexpected: "
            f"{gained}) — refusing; the original text is unchanged. If the "
            "kind shares its physical line with siblings, split each kind "
            "onto its own line first"
        )
    target = added if added is not None else edited
    if target is not None and definition is not None:
        if after.loops.get(target) != definition:
            raise ValueError(
                f"{context} violated content preservation: kind {target!r} "
                "parses back different from the requested definition — "
                "refusing; the original text is unchanged"
            )
    mutated = {added, edited, removed} - {None}
    for k in before_kinds - mutated:
        if before.loops[k] != after.loops[k]:
            raise ValueError(
                f"{context} violated content preservation: sibling kind "
                f"{k!r} was altered by the text splice — refusing; the "
                "original text is unchanged"
            )
    # Non-kind vertex content (store, sources, routes, …) must be untouched.
    # VertexFile fields are exposed via __match_args__ (the frozen-AST shim).
    for f in type(before).__match_args__:
        if f == "loops":
            continue
        if getattr(before, f) != getattr(after, f):
            raise ValueError(
                f"{context} violated content preservation: non-kind vertex "
                f"content changed (field {f!r}) — refusing; the original "
                "text is unchanged"
            )
    return result


def add_vertex_kind(text: str, kind: str, definition: LoopDef) -> str:
    """Add a loop-kind definition to vertex text; returns the new text.

    Creates the ``loops`` block (appended at end of file) when absent.
    Refuses if the kind already exists. Note the one-way expand-on-insert
    limitation: a single-line ``loops { ... }`` block is expanded across
    lines by the insert.
    """
    _validate_kind_name(kind)
    before = _parse_vertex_or_raise(text, f"add_vertex_kind({kind!r})")
    _assert_unique_kind_nodes(text, f"add_vertex_kind({kind!r})")
    if kind in before.loops:
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
    return _verified(
        before, result, f"add_vertex_kind({kind!r})",
        added=kind, definition=definition,
    )


def edit_vertex_kind(text: str, kind: str, definition: LoopDef) -> str:
    """Replace an existing kind's definition in place; returns the new text.

    Preserves the kind's position and all surrounding content. Not
    supported when the whole ``loops`` block is a single line (the
    documented expand-on-insert limitation is one-way).
    """
    _validate_kind_name(kind)
    before = _parse_vertex_or_raise(text, f"edit_vertex_kind({kind!r})")
    _assert_unique_kind_nodes(text, f"edit_vertex_kind({kind!r})")
    try:
        start, end = kdl_find_block(text, ["loops", kind])
    except ValueError as exc:
        raise ValueError(
            f"kind {kind!r} not found in loops block (single-line loops "
            "blocks cannot be edited in place — expand across lines first): "
            f"{exc}"
        ) from exc

    lines = text.splitlines()
    # Trailing-trivia honesty (SOL-R3-01 part c): the splice regenerates the
    # whole block, so it can carry through exactly ONE piece of trivia — the
    # suffix after the block's final close (`} // note`). Anything comment-
    # shaped INSIDE the replaced span would be silently dropped by the
    # regeneration; _verified claims preservation, so that is a refusal.
    end_line = lines[end]
    close_idx = end_line.rindex("}")
    suffix = end_line[close_idx + 1 :].rstrip()
    interior = "\n".join([*lines[start:end], end_line[: close_idx + 1]])
    if _has_comment_outside_strings(interior):
        raise ValueError(
            f"edit_vertex_kind({kind!r}): the {kind!r} block carries a "
            "comment the regenerated definition cannot preserve — move the "
            "comment outside the block (or edit the file by hand) and retry"
        )
    kind_indent = lines[start][: len(lines[start]) - len(lines[start].lstrip())]
    child = loop_def_to_kdl(kind, definition)
    new_lines = [
        (kind_indent + ln) if ln.strip() else ln for ln in child.splitlines()
    ]
    if suffix:
        sep = "" if suffix.startswith((" ", "\t")) else " "
        new_lines[-1] += sep + suffix
    lines[start : end + 1] = new_lines
    result = "\n".join(lines)
    if text.endswith("\n"):
        result += "\n"
    return _verified(
        before, result, f"edit_vertex_kind({kind!r})",
        edited=kind, definition=definition,
    )


def remove_vertex_kind(text: str, kind: str) -> str:
    """Remove a kind's definition from vertex text; returns the new text.

    Not supported when the whole ``loops`` block is a single line. Refuses
    (via post-validation) when removal would leave an invalid vertex, e.g.
    removing the last kind of a vertex with no other sources.
    """
    _validate_kind_name(kind)
    before = _parse_vertex_or_raise(text, f"remove_vertex_kind({kind!r})")
    _assert_unique_kind_nodes(text, f"remove_vertex_kind({kind!r})")
    try:
        result = kdl_remove_child(text, ["loops"], kind)
    except ValueError as exc:
        raise ValueError(
            f"kind {kind!r} not found in loops block (single-line loops "
            "blocks cannot be mutated in place — expand across lines first): "
            f"{exc}"
        ) from exc
    return _verified(
        before, result, f"remove_vertex_kind({kind!r})", removed=kind
    )
