"""`loops ls <vertex>` — unified declarations view + optional subcommand filters.

Phase 3 of plan:vertex-living-document. Aggregates the four declarative
surfaces (kinds / observers / combine / sources) into one consolidated
view. Subcommands narrow:

  loops ls <vertex>             unified
  loops ls <vertex> kind        only KINDS section
  loops ls <vertex> observer    only OBSERVERS section
  loops ls <vertex> combine     only COMBINE section
  loops ls <vertex> row [TPL]   only SOURCES section
"""

from __future__ import annotations

import sys
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from pathlib import Path


_FILTER_SUBCOMMANDS = frozenset({"kind", "observer", "combine", "row"})


def _print_ls_help(target: str | None = None) -> None:
    import argparse as _ap
    import sys as _sys

    if target is None:
        p = _ap.ArgumentParser(
            prog="loops ls",
            description="List all vertices, or declarations for one vertex.",
        )
        p.add_argument("vertex", nargs="?", help="Vertex name (omit for root listing)")
        p.add_argument(
            "subcommand", nargs="?",
            choices=["kind", "observer", "combine", "row"],
            help="kind / observer / combine / row (filter declarations)",
        )
    else:
        p = _ap.ArgumentParser(
            prog=f"loops ls {target}",
            description=f"Show declarations for vertex '{target}'.",
        )
        p.add_argument(
            "subcommand", nargs="?",
            choices=["kind", "observer", "combine", "row"],
            help="kind / observer / combine / row (filter; default: all)",
        )
    p.print_help(_sys.stdout)


def _run_ls(argv: list[str]) -> int:
    """Dispatch ``loops ls`` — root listing or per-vertex unified view.

    Forms:
      loops ls                     — list all discovered vertices (root)
      loops ls <vertex>            — unified declarations for one vertex
      loops ls <vertex> <filter>   — narrow to KINDS/OBSERVERS/COMBINE/POP
    """
    if argv and argv[0] in ("-h", "--help"):
        _print_ls_help()
        return 0

    if not argv or argv[0].startswith("-"):
        # No target — fall through to the existing root-listing handler.
        from loops.commands.population import _run_ls_root

        return _run_ls_root(argv)

    target = argv[0]
    rest = argv[1:]

    # Intercept --help at vertex level before sub-verb consumption.
    if rest and rest[0] in ("-h", "--help"):
        _print_ls_help(target)
        return 0

    filter_ = None
    if rest and rest[0] in _FILTER_SUBCOMMANDS:
        filter_ = rest[0]
        rest = rest[1:]

    # Render through painted's run_cli for zoom/width handling.
    from painted import run_cli

    from loops.lenses.declarations import declarations_view

    def fetch():
        return fetch_declarations(target, filter_=filter_, extra_argv=rest)

    def render(ctx, data):
        return declarations_view(data, ctx.zoom, ctx.width)

    return run_cli(
        rest,
        fetch=fetch,
        render=render,
        prog=f"loops ls {target}",
        description="List vertex declarations",
    )


def fetch_declarations(
    target: str,
    *,
    filter_: str | None = None,
    extra_argv: list[str] | None = None,
) -> dict[str, Any]:
    """Aggregate kinds + observers + combine + sources for the vertex."""
    from lang import parse_vertex_file
    from lang.population import (
        resolve_vertex,
    )
    from loops.commands.resolve import loops_home

    # Allow `loops ls reading/feeds` to qualify a template.
    if "/" in target and not target.startswith(("./", "/")):
        vertex_ref, qualifier = target.split("/", 1)
    else:
        vertex_ref, qualifier = target, None

    vertex_path = resolve_vertex(vertex_ref, loops_home())
    if not vertex_path.exists():
        return {
            "error": f"vertex not found: {vertex_path}",
            "vertex_name": vertex_ref,
            "filter": filter_,
        }

    try:
        vf = parse_vertex_file(vertex_path)
    except Exception as exc:  # noqa: BLE001
        return {
            "error": f"failed to parse {vertex_path.name}: {exc}",
            "vertex_name": vertex_ref,
            "filter": filter_,
        }

    kinds = _summarize_kinds(vf)
    observers = _summarize_observers(vf)
    combine = _summarize_combine(vf)
    sources = _summarize_populations(vf, vertex_path, qualifier)

    return {
        "vertex_name": vf.name,
        "vertex_path": str(vertex_path),
        "kinds": kinds,
        "observers": observers,
        "combine": combine,
        "sources": sources,
        "filter": filter_,
    }


def _summarize_kinds(vf) -> list[dict[str, str]]:
    """[(kind_name, fold_op_repr, target_field)] for each loop kind."""
    from lang.ast import (
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

    out: list[dict[str, str]] = []
    for kind_name, loop_def in (vf.loops or {}).items():
        if not loop_def.folds:
            out.append({"name": kind_name, "fold_op": "(no fold)", "target": ""})
            continue
        # Render the first fold (typical case is one fold per kind).
        fd = loop_def.folds[0]
        op = fd.op
        if isinstance(op, FoldBy):
            op_repr = f'by "{op.key_field}"'
        elif isinstance(op, FoldCollect):
            op_repr = f"collect {op.max_items}"
        elif isinstance(op, FoldCount):
            op_repr = "count"
        elif isinstance(op, FoldLatest):
            op_repr = "latest"
        elif isinstance(op, FoldMax):
            op_repr = f'max "{op.field}"'
        elif isinstance(op, FoldMin):
            op_repr = f'min "{op.field}"'
        elif isinstance(op, FoldSum):
            op_repr = f'sum "{op.field}"'
        elif isinstance(op, FoldAvg):
            op_repr = f'avg "{op.field}"'
        elif isinstance(op, FoldWindow):
            op_repr = f'window {op.size} "{op.field}"'
        else:
            op_repr = type(op).__name__
        out.append({"name": kind_name, "fold_op": op_repr, "target": fd.target})
    return out


def _summarize_observers(vf) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for o in vf.observers or ():
        entry: dict[str, Any] = {"name": o.name}
        if o.identity:
            entry["identity"] = o.identity
        if o.grant:
            entry["grants"] = sorted(o.grant.potential)
        out.append(entry)
    return out


def _summarize_combine(vf) -> list[dict[str, str]]:
    out: list[dict[str, str]] = []
    for e in vf.combine or ():
        entry: dict[str, str] = {"path": e.name}
        if e.alias:
            entry["alias"] = e.alias
        out.append(entry)
    return out


def _summarize_populations(
    vf, vertex_path: Path, qualifier: str | None
) -> list[dict[str, Any]]:
    """For each file-backed template population, return its header + rows."""
    from lang.ast import FromFile, TemplateSource
    from lang.population import list_file_read, template_name

    out: list[dict[str, Any]] = []
    for src in vf.sources or ():
        if not isinstance(src, TemplateSource):
            continue
        if not isinstance(src.from_, FromFile):
            continue
        tname = template_name(src)
        if qualifier is not None and tname != qualifier:
            continue
        list_path = src.from_.path
        if not list_path.is_absolute():
            list_path = (vertex_path.parent / list_path).resolve()
        if list_path.exists():
            header, rows = list_file_read(list_path)
        else:
            header, rows = [], []
        out.append({
            "template": tname,
            "list_path": str(list_path),
            "header": header,
            "rows": [
                {h: r.values.get(h, "") for h in header}
                for r in rows
            ],
        })
    return out


def _err(msg: str) -> None:
    from painted import Block, show
    from painted.palette import current_palette

    show(Block.text(f"Error: {msg}", current_palette().error), file=sys.stderr)
