"""Population management CLI commands."""

from __future__ import annotations

import argparse
import sys
from datetime import datetime, timezone
from pathlib import Path


def parse_target(target: str) -> tuple[str, str | None]:
    """Split target into (vertex_ref, template_qualifier).

    'reading'       -> ('reading', None)
    'economy/fred'  -> ('economy', 'fred')
    './my.vertex'   -> ('./my.vertex', None)
    'feeds.vertex'  -> ('feeds.vertex', None)
    '/tmp/t.vertex' -> ('/tmp/t.vertex', None)
    """
    if (
        target.endswith(".vertex")
        or target.startswith("./")
        or target.startswith("/")
    ):
        return target, None
    if "/" in target:
        vertex, template = target.split("/", 1)
        return vertex, template
    return target, None


def _load(target: str):
    """Load target for pop facts.

    Returns (vertex, template, list_path, header, store_path, vertex_path, is_multi).
    Raises ValueError on resolution errors.
    """
    from lang import parse_vertex_file
    from lang.ast import FromFile, TemplateSource
    from lang.population import list_file_header, resolve_template, resolve_vertex
    from loops.commands.resolve import loops_home, _resolve_vertex_store_path

    vertex_ref, qualifier = parse_target(target)
    vertex_path = resolve_vertex(vertex_ref, loops_home())

    if not vertex_path.exists():
        raise ValueError(f"{vertex_path} not found")

    vertex = parse_vertex_file(vertex_path)
    template = resolve_template(vertex, qualifier)

    is_multi = (
        len(
            [
                s
                for s in (vertex.sources or ())
                if isinstance(s, TemplateSource)
            ]
        )
        > 1
    )

    if not isinstance(template.from_, FromFile):
        raise ValueError(
            "Template population must be file-backed (missing 'from file \"...\"')"
        )

    list_path = template.from_.path
    if not list_path.is_absolute():
        list_path = (vertex_path.parent / list_path).resolve()

    header = list_file_header(list_path)
    store_path = _resolve_vertex_store_path(vertex_path.resolve())
    if store_path is None:
        raise ValueError("Vertex has no store configured")

    return vertex, template, list_path, header, store_path, vertex_path, is_multi


def _observer() -> str:
    from loops.commands.identity import resolve_observer

    return resolve_observer()


def _append_fact(store_path: Path, kind: str, payload: dict, observer: str) -> None:
    from atoms import Fact
    from engine import SqliteStore

    ts = datetime.now(timezone.utc).timestamp()
    fact = Fact(kind=kind, ts=ts, payload=payload, observer=observer, origin="")

    store_path.parent.mkdir(parents=True, exist_ok=True)
    with SqliteStore(
        path=store_path,
        serialize=Fact.to_dict,
        deserialize=Fact.from_dict,
    ) as store:
        store.append(fact)


def _maybe_bootstrap_from_list(
    *,
    store_path: Path,
    list_path: Path,
    template_name: str | None,
    include_unscoped: bool,
    observer: str,
) -> None:
    """If the store has no pop facts yet, seed it from the existing .list file."""
    from lang.population import list_file_read
    from loops.pop_store import POP_ADD_KIND, pop_store_has_facts

    if not list_path.exists():
        return

    if pop_store_has_facts(
        store_path, template=template_name, include_unscoped=include_unscoped
    ):
        return

    header, rows = list_file_read(list_path)
    if not header or not rows:
        return

    for row in rows:
        payload: dict[str, str] = {"key": row.key}
        if template_name is not None:
            payload["template"] = template_name
        for field in header[1:]:
            payload[field] = row.values.get(field, "")
        _append_fact(store_path, POP_ADD_KIND, payload, observer)


def fetch_ls(target: str) -> dict:
    """Fetch population data for ls command. Returns {header, rows}."""
    try:
        _vertex, template, list_path, header, store_path, _vpath, is_multi = (
            _load(target)
        )
    except (ValueError, Exception) as e:
        raise ValueError(str(e))

    from lang.population import list_file_read
    from loops.pop_store import pop_fold_rows, pop_read_facts

    template_name = template.template.stem if is_multi else None
    include_unscoped = not is_multi

    if not header:
        return {"header": [], "rows": []}

    facts = pop_read_facts(store_path)
    rows = pop_fold_rows(
        facts,
        header,
        template=template_name,
        include_unscoped=include_unscoped,
    )

    if not rows and list_path.exists() and not facts:
        # Before first pop fact, show the current .list as a migration-friendly view.
        _hdr, _rows = list_file_read(list_path)
        if _hdr:
            header, rows = _hdr, _rows

    return {
        "header": header,
        "rows": [
            {h: row.values.get(h, "") for h in header}
            if hasattr(row, "values") else row
            for row in rows
        ],
    }


def cmd_add(args: argparse.Namespace) -> int:
    """Emit pop.add and materialize .list from folded state."""
    from painted import show, Block
    from painted.palette import current_palette

    p = current_palette()

    try:
        _vertex, template, list_path, header, store_path, _vpath, is_multi = (
            _load(args.target)
        )
    except (ValueError, Exception) as e:
        show(Block.text(f"Error: {e}", p.error), file=sys.stderr)
        return 1

    values_list = list(args.values)
    if not header:
        show(Block.text("Error: no .list header found", p.error), file=sys.stderr)
        return 1

    # Last column gets remainder
    if len(values_list) > len(header):
        head = values_list[: len(header) - 1]
        tail = " ".join(values_list[len(header) - 1 :])
        values_list = head + [tail]

    if len(values_list) != len(header):
        show(Block.text(
            f"Error: expected {len(header)} values ({', '.join(header)}), "
            f"got {len(values_list)}",
            p.error,
        ), file=sys.stderr)
        return 1

    key = values_list[0]
    payload: dict[str, str] = {"key": key}
    if is_multi:
        payload["template"] = template.template.stem
    for field, value in zip(header[1:], values_list[1:]):
        payload[field] = value

    observer = _observer()
    template_name = template.template.stem if is_multi else None
    include_unscoped = not is_multi

    _maybe_bootstrap_from_list(
        store_path=store_path,
        list_path=list_path,
        template_name=template_name,
        include_unscoped=include_unscoped,
        observer=observer,
    )

    from loops.pop_store import POP_ADD_KIND, pop_materialize_list

    _append_fact(store_path, POP_ADD_KIND, payload, observer)
    pop_materialize_list(
        store_path=store_path,
        list_path=list_path,
        header=header,
        template=template_name,
        include_unscoped=include_unscoped,
    )

    show(Block.text(f"Emitted pop.add {key}", p.success), file=sys.stdout)
    return 0


def cmd_rm(args: argparse.Namespace) -> int:
    """Emit pop.rm and materialize .list from folded state."""
    from painted import show, Block
    from painted.palette import current_palette

    p = current_palette()

    try:
        _vertex, template, list_path, header, store_path, _vpath, is_multi = (
            _load(args.target)
        )
    except (ValueError, Exception) as e:
        show(Block.text(f"Error: {e}", p.error), file=sys.stderr)
        return 1

    key = args.key
    if not header:
        show(Block.text("Error: no .list header found", p.error), file=sys.stderr)
        return 1

    observer = _observer()
    template_name = template.template.stem if is_multi else None
    include_unscoped = not is_multi

    _maybe_bootstrap_from_list(
        store_path=store_path,
        list_path=list_path,
        template_name=template_name,
        include_unscoped=include_unscoped,
        observer=observer,
    )

    from loops.pop_store import POP_RM_KIND, pop_materialize_list

    payload: dict[str, str] = {"key": key}
    if is_multi:
        payload["template"] = template.template.stem

    _append_fact(store_path, POP_RM_KIND, payload, observer)
    pop_materialize_list(
        store_path=store_path,
        list_path=list_path,
        header=header,
        template=template_name,
        include_unscoped=include_unscoped,
    )

    show(Block.text(f"Emitted pop.rm {key}", p.success), file=sys.stdout)
    return 0


def cmd_export(args: argparse.Namespace) -> int:
    """Materialize .list from folded pop facts."""
    from painted import show, Block
    from painted.palette import current_palette

    p = current_palette()

    try:
        _vertex, template, list_path, header, store_path, _vpath, is_multi = (
            _load(args.target)
        )
    except (ValueError, Exception) as e:
        show(Block.text(f"Error: {e}", p.error), file=sys.stderr)
        return 1

    if not header:
        show(Block.text("Error: no .list header found", p.error), file=sys.stderr)
        return 1

    observer = _observer()
    template_name = template.template.stem if is_multi else None
    include_unscoped = not is_multi

    _maybe_bootstrap_from_list(
        store_path=store_path,
        list_path=list_path,
        template_name=template_name,
        include_unscoped=include_unscoped,
        observer=observer,
    )

    from loops.pop_store import pop_materialize_list

    pop_materialize_list(
        store_path=store_path,
        list_path=list_path,
        header=header,
        template=template_name,
        include_unscoped=include_unscoped,
    )

    show(Block.text(f"Materialized {list_path}", p.success), file=sys.stdout)
    return 0
