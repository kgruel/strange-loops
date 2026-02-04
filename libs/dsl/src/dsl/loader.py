"""KDL-based loader for .loop and .vertex files.

Parses KDL text via ckdl, maps nodes to AST dataclasses.
"""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING

import ckdl

from .ast import (
    BoundaryAfter,
    BoundaryEvery,
    BoundaryWhen,
    Coerce,
    Duration,
    FoldAvg,
    FoldBy,
    FoldCollect,
    FoldCount,
    FoldDecl,
    FoldLatest,
    FoldMax,
    FoldMin,
    FoldSum,
    FoldWindow,
    LoopDef,
    LoopFile,
    LStrip,
    Pick,
    Replace,
    RStrip,
    Select,
    Skip,
    SourceParams,
    Split,
    Strip,
    TemplateSource,
    Transform,
    Trigger,
    VertexFile,
)
from .errors import Location, ParseError

if TYPE_CHECKING:
    from typing import Literal

    from .ast import Boundary, FoldOp, ParseStep, SourceEntry, TransformOp


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _error(msg: str, path: Path | None = None) -> ParseError:
    return ParseError(msg, Location(path, 1))


def _require_arg(node: ckdl.Node, index: int, label: str, path: Path | None = None) -> str:
    """Get a required string argument from a node."""
    if index >= len(node.args):
        raise _error(f"{node.name}: missing required {label}", path)
    val = node.args[index]
    if not isinstance(val, str):
        return str(val)
    return val


def _node_map(nodes: list[ckdl.Node]) -> dict[str, ckdl.Node]:
    """Build name→node dict. For nodes that appear once (top-level keys)."""
    result: dict[str, ckdl.Node] = {}
    for node in nodes:
        result[node.name] = node
    return result


# ---------------------------------------------------------------------------
# Parse step loaders
# ---------------------------------------------------------------------------


def _load_skip(node: ckdl.Node, path: Path | None) -> Skip:
    return Skip(pattern=_require_arg(node, 0, "pattern", path))


def _load_split(node: ckdl.Node, path: Path | None) -> Split:
    delimiter = node.args[0] if node.args else None
    return Split(delimiter=delimiter)


def _load_pick(node: ckdl.Node, path: Path | None) -> Pick:
    indices = tuple(int(a) for a in node.args)
    names = None
    for child in node.children:
        if child.name == "names":
            names = tuple(str(a) for a in child.args)
            if len(names) != len(indices):
                raise _error(f"pick: {len(indices)} indices but {len(names)} names", path)
    return Pick(indices=indices, names=names)


def _load_select(node: ckdl.Node, path: Path | None) -> Select:
    if not node.args:
        raise _error("select requires at least one field name", path)
    return Select(fields=tuple(str(a) for a in node.args))


def _load_transform_op(node: ckdl.Node, path: Path | None) -> TransformOp:
    name = node.name
    if name == "strip":
        return Strip(chars=_require_arg(node, 0, "chars", path))
    if name == "lstrip":
        return LStrip(chars=_require_arg(node, 0, "chars", path))
    if name == "rstrip":
        return RStrip(chars=_require_arg(node, 0, "chars", path))
    if name == "replace":
        return Replace(
            old=_require_arg(node, 0, "old string", path),
            new=_require_arg(node, 1, "new string", path),
        )
    if name == "coerce":
        type_str = _require_arg(node, 0, "type", path)
        if type_str not in ("int", "float", "bool", "str"):
            raise _error(f"coerce: invalid type {type_str!r}", path)
        return Coerce(type=type_str)  # type: ignore[arg-type]
    raise _error(f"Unknown transform operation: {name}", path)


def _load_transform(node: ckdl.Node, path: Path | None) -> Transform:
    field = _require_arg(node, 0, "field name", path)
    ops = tuple(_load_transform_op(child, path) for child in node.children)
    if not ops:
        raise _error(f"transform {field!r}: no operations", path)
    return Transform(field=field, operations=ops)


_PARSE_STEP_LOADERS = {
    "skip": _load_skip,
    "split": _load_split,
    "pick": _load_pick,
    "select": _load_select,
    "transform": _load_transform,
}


def _load_parse_block(node: ckdl.Node, path: Path | None) -> tuple[ParseStep, ...]:
    steps: list[ParseStep] = []
    for child in node.children:
        loader = _PARSE_STEP_LOADERS.get(child.name)
        if loader is None:
            raise _error(f"Unknown parse step: {child.name}", path)
        steps.append(loader(child, path))
    return tuple(steps)


# ---------------------------------------------------------------------------
# Fold / boundary loaders
# ---------------------------------------------------------------------------


_FOLD_OP_SPECS: dict[str, tuple[type, list[tuple[str, type]]]] = {
    "inc":     (FoldCount,   []),
    "latest":  (FoldLatest,  []),
    "by":      (FoldBy,      [("key_field", str)]),
    "sum":     (FoldSum,     [("field", str)]),
    "max":     (FoldMax,     [("field", str)]),
    "min":     (FoldMin,     [("field", str)]),
    "avg":     (FoldAvg,     [("field", str)]),
    "collect": (FoldCollect, [("max_items", int)]),
    "window":  (FoldWindow,  [("size", int), ("field", str)]),
}


def _load_fold_op(node: ckdl.Node, path: Path | None) -> tuple[str, FoldOp]:
    """Load a fold declaration node. Node name is the target field, args define the op."""
    target = node.name
    if not node.args:
        raise _error(f"fold target {target!r}: missing operation", path)

    op_name = str(node.args[0])
    spec = _FOLD_OP_SPECS.get(op_name)
    if spec is None:
        raise _error(f"Unknown fold operation: {op_name}", path)

    cls, arg_spec = spec
    kwargs: dict[str, object] = {}
    for i, (param_name, param_type) in enumerate(arg_spec, start=1):
        if i >= len(node.args):
            raise _error(f"fold {target}: '{op_name}' requires {param_name}", path)
        kwargs[param_name] = param_type(node.args[i])
    return target, cls(**kwargs)


def _load_fold_block(node: ckdl.Node, path: Path | None) -> tuple[FoldDecl, ...]:
    decls: list[FoldDecl] = []
    for child in node.children:
        target, op = _load_fold_op(child, path)
        decls.append(FoldDecl(target=target, op=op))
    return tuple(decls)


def _load_boundary(node: ckdl.Node, path: Path | None) -> Boundary:
    props = node.properties
    if "when" in props:
        return BoundaryWhen(kind=str(props["when"]))
    if "after" in props:
        return BoundaryAfter(count=int(props["after"]))
    if "every" in props:
        return BoundaryEvery(count=int(props["every"]))
    raise _error("boundary requires when=, after=, or every= property", path)


# ---------------------------------------------------------------------------
# Loop definition loaders
# ---------------------------------------------------------------------------


def _load_loop_def(node: ckdl.Node, path: Path | None) -> LoopDef:
    """Load a loop definition (fold + boundary) from a node's children."""
    folds: tuple[FoldDecl, ...] = ()
    boundary: Boundary | None = None

    for child in node.children:
        if child.name == "fold":
            folds = _load_fold_block(child, path)
        elif child.name == "boundary":
            boundary = _load_boundary(child, path)
        else:
            raise _error(f"Unknown loop field: {child.name}", path)

    return LoopDef(folds=folds, boundary=boundary)


# ---------------------------------------------------------------------------
# Source loaders (for .vertex files)
# ---------------------------------------------------------------------------


def _load_template_source(node: ckdl.Node, path: Path | None) -> TemplateSource:
    template_path = Path(_require_arg(node, 0, "template path", path))
    params: list[SourceParams] = []
    loop_def: LoopDef | None = None

    for child in node.children:
        if child.name == "with":
            # Each 'with' node's properties are one parameter row
            params.append(SourceParams(values={k: str(v) for k, v in child.properties.items()}))
        elif child.name == "loop":
            loop_def = _load_loop_def(child, path)
        else:
            raise _error(f"Unknown template block: {child.name}", path)

    if not params:
        raise _error("Template source requires at least one 'with' node", path)

    return TemplateSource(template=template_path, params=tuple(params), loop=loop_def)


def _load_sources_block(node: ckdl.Node, path: Path | None) -> tuple[SourceEntry, ...]:
    sources: list[SourceEntry] = []
    for child in node.children:
        if child.name == "path":
            sources.append(Path(_require_arg(child, 0, "path", path)))
        elif child.name == "template":
            sources.append(_load_template_source(child, path))
        else:
            raise _error(f"Unknown source type: {child.name}", path)
    return tuple(sources)


# ---------------------------------------------------------------------------
# Top-level loaders
# ---------------------------------------------------------------------------


def _load_loop_file(doc: ckdl.Document, path: Path | None) -> LoopFile:
    source: str | None = None
    kind: str | None = None
    observer: str | None = None
    every: Duration | None = None
    on: Trigger | None = None
    format_: Literal["lines", "json", "ndjson", "blob"] = "lines"
    timeout = Duration(60000)
    env: dict[str, str] | None = None
    parse_steps: tuple[ParseStep, ...] = ()

    for node in doc.nodes:
        name = node.name
        if name == "source":
            source = _require_arg(node, 0, "command", path)
        elif name == "kind":
            kind = _require_arg(node, 0, "kind string", path)
        elif name == "observer":
            observer = _require_arg(node, 0, "observer string", path)
        elif name == "every":
            every = Duration.parse(_require_arg(node, 0, "duration", path))
        elif name == "on":
            kinds = [str(a) for a in node.args]
            if not kinds:
                raise _error("on: requires at least one trigger kind", path)
            if len(kinds) == 1:
                on = Trigger.single(kinds[0])
            else:
                on = Trigger.multi(kinds)
        elif name == "format":
            fmt_value = _require_arg(node, 0, "format string", path)
            if fmt_value not in ("lines", "json", "ndjson", "blob"):
                raise _error(
                    f"format must be 'lines', 'json', 'ndjson', or 'blob', got {fmt_value!r}",
                    path,
                )
            format_ = fmt_value  # type: ignore[assignment]
        elif name == "timeout":
            timeout = Duration.parse(_require_arg(node, 0, "duration", path))
        elif name == "parse":
            parse_steps = _load_parse_block(node, path)
        elif name == "env":
            env = {k: str(v) for k, v in node.properties.items()}
        else:
            raise _error(f"Unknown config key: {name}", path)

    # Validate required fields
    if kind is None:
        raise _error("Missing required field: kind", path)
    if observer is None:
        raise _error("Missing required field: observer", path)
    if source is None and every is None:
        raise _error("Missing required field: source (or use every: for pure timer loop)", path)

    return LoopFile(
        kind=kind,
        observer=observer,
        source=source,
        every=every,
        on=on,
        format=format_,
        timeout=timeout,
        env=env,
        parse=parse_steps,
        path=path,
    )


def _load_vertex_file(doc: ckdl.Document, path: Path | None) -> VertexFile:
    name: str | None = None
    store: Path | None = None
    discover: str | None = None
    sources: tuple[SourceEntry, ...] | None = None
    vertices: tuple[Path, ...] | None = None
    loops: dict[str, LoopDef] = {}
    routes: dict[str, str] | None = None
    emit: str | None = None

    for node in doc.nodes:
        key = node.name
        if key == "name":
            name = _require_arg(node, 0, "name string", path)
        elif key == "store":
            store = Path(_require_arg(node, 0, "path", path))
        elif key == "discover":
            discover = _require_arg(node, 0, "glob pattern", path)
        elif key == "emit":
            emit = _require_arg(node, 0, "emit string", path)
        elif key == "sources":
            sources = _load_sources_block(node, path)
        elif key == "vertices":
            vertices = tuple(Path(str(a)) for a in node.args)
        elif key == "loops":
            for child in node.children:
                loops[child.name] = _load_loop_def(child, path)
        elif key == "routes":
            routes = {}
            for child in node.children:
                # Each child node: name is the kind, first arg is the loop target
                route_target = _require_arg(child, 0, "route target", path)
                routes[child.name] = route_target
        else:
            raise _error(f"Unknown config key: {key}", path)

    # Validate required fields
    if name is None:
        raise _error("Missing required field: name", path)

    has_template_loop_specs = sources and any(
        isinstance(s, TemplateSource) and s.loop is not None for s in sources
    )
    if not loops and not has_template_loop_specs:
        raise _error("Missing required field: loops", path)

    return VertexFile(
        name=name,
        loops=loops,
        store=store,
        discover=discover,
        sources=sources,
        vertices=vertices,
        routes=routes,
        emit=emit,
        path=path,
    )


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def parse_loop(text: str, path: Path | None = None) -> LoopFile:
    """Parse a .loop file from KDL text."""
    try:
        doc = ckdl.parse(text)
    except ckdl.ParseError as e:
        raise ParseError(str(e), Location(path, 1)) from e
    return _load_loop_file(doc, path)


def parse_vertex(text: str, path: Path | None = None) -> VertexFile:
    """Parse a .vertex file from KDL text."""
    try:
        doc = ckdl.parse(text)
    except ckdl.ParseError as e:
        raise ParseError(str(e), Location(path, 1)) from e
    return _load_vertex_file(doc, path)


def parse_loop_file(path: Path) -> LoopFile:
    """Parse a .loop file from path."""
    text = path.read_text()
    return parse_loop(text, path)


def parse_vertex_file(path: Path) -> VertexFile:
    """Parse a .vertex file from path."""
    text = path.read_text()
    return parse_vertex(text, path)
