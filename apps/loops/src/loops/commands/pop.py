"""Population management CLI commands."""

from __future__ import annotations

import argparse
import sys
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
    """Load vertex, template, and population from target string.

    Returns (vertex, template, population, vertex_path).
    Raises ValueError on resolution errors.
    """
    from lang import parse_vertex_file
    from lang.population import read_population, resolve_template, resolve_vertex
    from loops.main import loops_home

    vertex_ref, qualifier = parse_target(target)
    vertex_path = resolve_vertex(vertex_ref, loops_home())

    if not vertex_path.exists():
        raise ValueError(f"{vertex_path} not found")

    vertex = parse_vertex_file(vertex_path)
    template = resolve_template(vertex, qualifier)
    base_dir = vertex_path.parent
    population = read_population(vertex, template, base_dir)

    return vertex, template, population, vertex_path


def cmd_ls(args: argparse.Namespace) -> int:
    """List population rows."""
    try:
        _vertex, _template, pop, _vpath = _load(args.target)
    except (ValueError, Exception) as e:
        print(f"Error: {e}", file=sys.stderr)
        return 1

    if not pop.header:
        print(f"No population for template '{pop.template_name}'")
        return 0

    print("\t".join(pop.header))
    for row in pop.rows:
        print("\t".join(row.values.get(h, "") for h in pop.header))

    return 0


def cmd_add(args: argparse.Namespace) -> int:
    """Add a row to the population."""
    try:
        _vertex, template, pop, vpath = _load(args.target)
    except (ValueError, Exception) as e:
        print(f"Error: {e}", file=sys.stderr)
        return 1

    if not pop.header:
        print(
            "Error: no header — add a row manually or create a .list file first",
            file=sys.stderr,
        )
        return 1

    values_list = list(args.values)
    header = pop.header

    # Last column gets remainder
    if len(values_list) > len(header):
        head = values_list[: len(header) - 1]
        tail = " ".join(values_list[len(header) - 1 :])
        values_list = head + [tail]

    if len(values_list) != len(header):
        print(
            f"Error: expected {len(header)} values ({', '.join(header)}), "
            f"got {len(values_list)}",
            file=sys.stderr,
        )
        return 1

    values = dict(zip(header, values_list))
    key = values_list[0]

    # Duplicate check
    for row in pop.rows:
        if row.key == key:
            print(f"'{key}' already exists", file=sys.stderr)
            return 1

    from lang.population import PopulationRow, kdl_insert_with_row, list_file_add

    new_row = PopulationRow(key=key, values=values)

    if pop.storage in ("file", "both") and pop.file_path:
        list_file_add(pop.file_path, header, new_row)
    else:
        # Inline: modify KDL
        text = vpath.read_text()
        text = kdl_insert_with_row(text, str(template.template), values)
        vpath.write_text(text)

    print(f"Added {key}")
    return 0


def cmd_rm(args: argparse.Namespace) -> int:
    """Remove a row from the population."""
    try:
        _vertex, template, pop, vpath = _load(args.target)
    except (ValueError, Exception) as e:
        print(f"Error: {e}", file=sys.stderr)
        return 1

    key = args.key
    removed = False

    from lang.population import kdl_remove_with_row, list_file_rm

    # Check file first, then inline
    if pop.file_path and pop.file_path.exists():
        removed = list_file_rm(pop.file_path, key)

    if not removed and pop.storage in ("inline", "both"):
        try:
            key_field = pop.header[0] if pop.header else "kind"
            text = vpath.read_text()
            text = kdl_remove_with_row(
                text, str(template.template), key_field, key
            )
            vpath.write_text(text)
            removed = True
        except ValueError:
            pass

    if not removed:
        print(f"'{key}' not found", file=sys.stderr)
        return 1

    print(f"Removed {key}")
    return 0


def cmd_export(args: argparse.Namespace) -> int:
    """Export inline with rows to a .list file."""
    try:
        _vertex, template, pop, vpath = _load(args.target)
    except (ValueError, Exception) as e:
        print(f"Error: {e}", file=sys.stderr)
        return 1

    if pop.storage == "file":
        print("Already using .list file", file=sys.stderr)
        return 1

    from lang.population import export_to_file, list_file_write

    base_dir = vpath.parent
    if args.output:
        list_path = Path(args.output)
        if not list_path.is_absolute():
            list_path = base_dir / list_path
    else:
        list_path = base_dir / f"{pop.template_name}.list"

    # Compute relative path for KDL reference
    try:
        rel = list_path.relative_to(base_dir)
        from_ref = f"./{rel}"
    except ValueError:
        from_ref = str(list_path)

    # Write .list file
    list_file_write(list_path, pop.header, pop.rows)

    # Modify vertex KDL
    text = vpath.read_text()
    text = export_to_file(text, str(template.template), from_ref)
    vpath.write_text(text)

    print(f"Exported to {list_path}")
    return 0


def cmd_import(args: argparse.Namespace) -> int:
    """Import .list file rows to inline with."""
    try:
        _vertex, template, pop, vpath = _load(args.target)
    except (ValueError, Exception) as e:
        print(f"Error: {e}", file=sys.stderr)
        return 1

    if pop.storage == "inline":
        print("Already inline", file=sys.stderr)
        return 1

    from lang.population import import_from_file

    text = vpath.read_text()
    text = import_from_file(text, str(template.template), pop.rows)
    vpath.write_text(text)

    print(f"Imported {len(pop.rows)} rows inline")
    return 0


def cmd_merge(args: argparse.Namespace) -> int:
    """Merge external .list file into population."""
    try:
        _vertex, template, pop, vpath = _load(args.target)
    except (ValueError, Exception) as e:
        print(f"Error: {e}", file=sys.stderr)
        return 1

    from lang.population import (
        PopulationRow,
        kdl_insert_with_row,
        list_file_add,
        list_file_read,
    )

    merge_path = Path(args.file)
    if not merge_path.exists():
        print(f"Error: {merge_path} not found", file=sys.stderr)
        return 1

    _, merge_rows = list_file_read(merge_path)
    existing_keys = {r.key for r in pop.rows}

    added = 0
    for row in merge_rows:
        if row.key in existing_keys:
            continue

        if pop.storage in ("file", "both") and pop.file_path:
            list_file_add(pop.file_path, pop.header, row)
        else:
            text = vpath.read_text()
            text = kdl_insert_with_row(
                text, str(template.template), row.values
            )
            vpath.write_text(text)

        existing_keys.add(row.key)
        added += 1

    skipped = len(merge_rows) - added
    print(f"Merged {added} new rows ({skipped} duplicates skipped)")
    return 0
