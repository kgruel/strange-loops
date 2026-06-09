"""`loops ls <vertex>` — unified declarations view, narrowed by flag or positional.

Phase 3 of plan:vertex-living-document, extended to converge with read's
grammar (fix/ls-flag-grammar, 2026-05-17). Aggregates the four declarative
surfaces (kinds / observers / combine / sources) into one consolidated
view. Narrowing is available in two equivalent shapes:

  Flag form (canonical, composes, matches read):
    loops ls <vertex> --kind                 only KINDS section
    loops ls <vertex> --kind decision        narrow KINDS to one entry
    loops ls <vertex> --kind --observer      KINDS + OBSERVERS sections
    loops ls <vertex> --observer kyle        narrow OBSERVERS to one entry
    loops ls <vertex> --row [TEMPLATE]       narrow SOURCES (template sources)

  Positional form (back-compat alias for the bare single-section flag):
    loops ls <vertex> kind                   equivalent to --kind
    loops ls <vertex> observer               equivalent to --observer
    loops ls <vertex> row [TEMPLATE]         equivalent to --row

Mixing the two forms is an error — the helpful message points at the flag
form as canonical. The principle is the same one that governs `read`:
filters narrow a unified view and should be flags; positionals identify a
target the verb operates on. The positional form predates this rule and
stays for muscle memory and shell-friendly terseness.
"""

from __future__ import annotations

import argparse
import sys
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from pathlib import Path


_FILTER_SUBCOMMANDS = frozenset({"kind", "observer", "combine", "row"})
# Order preserved for both --help rendering and stable filter-list output.
_SECTION_FLAGS = ("kind", "observer", "combine", "row")


def _print_ls_help(target: str | None = None) -> None:
    if target is None:
        p = argparse.ArgumentParser(
            prog="loops ls",
            description=(
                "List all vertices, or declarations for one vertex.\n\n"
                "Section narrowing (flag form, composable):\n"
                "  --kind [NAME]         show KINDS section (or one named entry)\n"
                "  --observer [NAME]     show OBSERVERS section (or one named entry)\n"
                "  --combine [PATH]      show COMBINE section (or one named entry)\n"
                "  --row [TEMPLATE]      show SOURCES section (or one template)\n\n"
                "Positional alias (back-compat, single section, no narrowing):\n"
                "  loops ls <vertex> kind|observer|combine|row\n\n"
                "Mixing both forms is an error."
            ),
            formatter_class=argparse.RawDescriptionHelpFormatter,
        )
        p.add_argument("vertex", nargs="?", help="Vertex name (omit for root listing)")
    else:
        p = argparse.ArgumentParser(
            prog=f"loops ls {target}",
            description=(
                f"Show declarations for vertex '{target}'.\n\n"
                "Section narrowing (flag form, composable):\n"
                "  --kind [NAME]         show KINDS section (or one named entry)\n"
                "  --observer [NAME]     show OBSERVERS section (or one named entry)\n"
                "  --combine [PATH]      show COMBINE section (or one named entry)\n"
                "  --row [TEMPLATE]      show SOURCES section (or one template)\n\n"
                "Positional alias (back-compat):\n"
                f"  loops ls {target} kind|observer|combine|row"
            ),
            formatter_class=argparse.RawDescriptionHelpFormatter,
        )
    p.print_help(sys.stdout)


def _peel_section_flags(
    rest: list[str],
) -> tuple[list[str], dict[str, str], list[str]]:
    """Extract --kind/--observer/--combine/--row from rest.

    Each flag uses ``nargs='?'``: bare form selects the section, with a value
    narrows to one named entry. argparse correctly treats a following ``--*``
    token as the next flag (verified empirically — see PLAN.md §A).

    Returns ``(filters, narrows, leftover_argv)``:
      filters — section keys present (e.g. ['kind', 'observer'])
      narrows — section → name when given a value (e.g. {'kind': 'decision'})
      leftover_argv — args not consumed (passed through to run_cli)
    """
    p = argparse.ArgumentParser(add_help=False)
    for verb in _SECTION_FLAGS:
        p.add_argument(f"--{verb}", nargs="?", const=True, default=None)
    known, leftover = p.parse_known_args(rest)

    filters: list[str] = []
    narrows: dict[str, str] = {}
    for verb in _SECTION_FLAGS:
        val = getattr(known, verb)
        if val is None:
            continue
        filters.append(verb)
        if val is not True:
            narrows[verb] = val
    return filters, narrows, leftover


def _run_ls(argv: list[str]) -> int:
    """Dispatch ``loops ls`` — root listing or per-vertex unified view.

    Forms (see module docstring for the full grammar):
      loops ls                          — list all discovered vertices (root)
      loops ls <vertex>                 — unified declarations for one vertex
      loops ls <vertex> --kind [NAME]   — flag form (canonical, composable)
      loops ls <vertex> kind            — positional alias (back-compat)
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

    # Positional sub-verb (legacy form): a bare token that names a section.
    positional_filter: str | None = None
    if rest and rest[0] in _FILTER_SUBCOMMANDS:
        positional_filter = rest[0]
        rest = rest[1:]

    flag_filters, flag_narrows, rest = _peel_section_flags(rest)

    if positional_filter and (flag_filters or flag_narrows):
        _err(
            "ls: don't mix the positional form with --kind/--observer/--combine/--row.\n"
            "  flag form is canonical:    sl ls <vertex> --kind [NAME]\n"
            "  positional is back-compat: sl ls <vertex> kind"
        )
        return 2

    if positional_filter is not None:
        filters: list[str] | None = [positional_filter]
        narrows: dict[str, str] = {}
    else:
        filters = flag_filters or None  # None = all sections visible
        narrows = flag_narrows

    # Render through painted's run_cli for zoom/width handling.
    from painted import run_cli

    from loops.lenses.declarations import declarations_view

    def fetch():
        return fetch_declarations(
            target, filters=filters, narrows=narrows, extra_argv=rest,
        )

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
    filters: list[str] | None = None,
    narrows: dict[str, str] | None = None,
    extra_argv: list[str] | None = None,  # noqa: ARG001 — reserved for future read-style flags
) -> dict[str, Any]:
    """Aggregate kinds + observers + combine + sources for the vertex.

    Narrowing inputs accept two equivalent shapes:
      * legacy single-section: ``filter_="kind"`` (kept for callers that
        predate the flag-grammar convergence)
      * multi-section + name: ``filters=["kind", "observer"]``,
        ``narrows={"kind": "decision"}``

    The returned dict exposes both ``filter`` (legacy, single) and
    ``filters``/``narrows`` (new) so lens code can transition incrementally.
    """
    from lang import parse_vertex_file
    from lang.population import (
        resolve_vertex,
    )
    from loops.commands.resolve import _resolve_vertex_for_dispatch, loops_home

    # Normalise narrowing inputs — legacy filter_ wins when it's the only one set.
    if filters is None and filter_ is not None:
        filters = [filter_]
    narrows = narrows or {}
    # Back-fill legacy `filter` from `filters` when only the new shape is given.
    legacy_filter = filter_ if filter_ is not None else (
        filters[0] if filters and len(filters) == 1 else None
    )

    # Allow `loops ls reading/feeds` to qualify a template.
    if "/" in target and not target.startswith(("./", "/")):
        vertex_ref, qualifier = target.split("/", 1)
    else:
        vertex_ref, qualifier = target, None

    # Local-first — same resolution the verbs use (thread:global-local-walk-broken).
    vertex_path = _resolve_vertex_for_dispatch(vertex_ref)
    if vertex_path is None:
        missing = resolve_vertex(vertex_ref, loops_home())
        return {
            "error": f"vertex not found: {missing}",
            "vertex_name": vertex_ref,
            "filter": legacy_filter,
            "filters": filters,
            "narrows": narrows,
        }

    try:
        vf = parse_vertex_file(vertex_path)
    except Exception as exc:  # noqa: BLE001
        return {
            "error": f"failed to parse {vertex_path.name}: {exc}",
            "vertex_name": vertex_ref,
            "filter": legacy_filter,
            "filters": filters,
            "narrows": narrows,
        }

    kinds = _summarize_kinds(vf)
    observers = _summarize_observers(vf)
    combine = _summarize_combine(vf)
    sources = _summarize_sources(vf, vertex_path, qualifier)

    return {
        "vertex_name": vf.name,
        "vertex_path": str(vertex_path),
        "kinds": kinds,
        "observers": observers,
        "combine": combine,
        "sources": sources,
        "filter": legacy_filter,
        "filters": filters,
        "narrows": narrows,
    }


def _summarize_kinds(vf) -> list[dict[str, Any]]:
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

    out: list[dict[str, Any]] = []
    for kind_name, loop_def in (vf.loops or {}).items():
        if not loop_def.folds:
            out.append({"name": kind_name, "fold_op": "(no fold)", "target": "", "preview_fields": ()})
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
        out.append({"name": kind_name, "fold_op": op_repr, "target": fd.target, "preview_fields": loop_def.preview_fields})
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


def _summarize_sources(
    vf, vertex_path: Path, qualifier: str | None
) -> list[dict[str, Any]]:
    """For each file-backed template source, return its header + rows."""
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
