"""`loops rm <vertex> <subcommand>` — vertex declaration removals.

Phase 3 of plan:vertex-living-document. Symmetric inverse of `loops add`:
removes a declared entity from a vertex file via the kdl_splice library
(Phase 1) and the same refuses-and-preserves invariant (Phase 2):
post-splice text MUST parse, or the file is left byte-identical.

Subcommands:
  kind      remove a loop kind block from loops { ... }
  observer  remove an observer entry from observers { ... }
  combine   remove a combine entry (matched by positional path)
  row       remove a row from a template population's .list file

Bare-positional form (``loops rm <vertex> <KEY>``) is preserved as a
back-compat alias for ``row`` and will be retired alongside the rest of
the rss-era surface.

When the target vertex has a ``change`` loop kind defined, each removal
emits a ``change`` fact with ``op="rm"`` and the target/name details —
symmetric with the add-side audit trail.
"""

from __future__ import annotations

import argparse
import sys
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from pathlib import Path


_SUBCOMMANDS = frozenset({"kind", "observer", "combine", "row"})


def _run_rm(argv: list[str]) -> int:
    """Dispatch ``loops rm <vertex> <subcommand-or-positional> ...``.

    If argv[1] is a known subcommand, route. Otherwise treat argv[1] as a
    population-row key (back-compat).
    """
    if not argv:
        _err("loops rm: missing vertex target")
        return 2

    target = argv[0]
    rest = argv[1:]

    if rest and rest[0] in _SUBCOMMANDS:
        sub = rest[0]
        sub_argv = rest[1:]
        if sub == "kind":
            return _rm_kind(target, sub_argv)
        if sub == "observer":
            return _rm_observer(target, sub_argv)
        if sub == "combine":
            return _rm_combine(target, sub_argv)
        if sub == "row":
            return _rm_row(target, sub_argv)

    # Back-compat: bare positional == implicit `row` subcommand.
    return _rm_row(target, rest)


# ---------------------------------------------------------------------------
# Subcommand: kind
# ---------------------------------------------------------------------------


def _rm_kind(target: str, argv: list[str]) -> int:
    p = argparse.ArgumentParser(prog="loops rm <vertex> kind", add_help=True)
    p.add_argument("name", help="Loop kind name to remove")
    try:
        args = p.parse_args(argv)
    except SystemExit as e:
        return int(e.code) if e.code is not None else 1

    vertex_path = _resolve_or_fail(target)
    if vertex_path is None:
        return 1

    rc = _splice_remove(
        vertex_path=vertex_path,
        parent=["loops"],
        child_name=args.name,
        child_key=None,
        key_field=None,
        not_found_desc=f"kind {args.name!r}",
        change_payload={"op": "rm", "target": "kind", "name": args.name},
    )
    if rc == 0:
        _ok(f"removed kind {args.name!r} from {vertex_path.name}")
    return rc


# ---------------------------------------------------------------------------
# Subcommand: observer
# ---------------------------------------------------------------------------


def _rm_observer(target: str, argv: list[str]) -> int:
    p = argparse.ArgumentParser(prog="loops rm <vertex> observer", add_help=True)
    p.add_argument("name", help="Observer name to remove")
    try:
        args = p.parse_args(argv)
    except SystemExit as e:
        return int(e.code) if e.code is not None else 1

    vertex_path = _resolve_or_fail(target)
    if vertex_path is None:
        return 1

    rc = _splice_remove(
        vertex_path=vertex_path,
        parent=["observers"],
        child_name=args.name,
        child_key=None,
        key_field=None,
        not_found_desc=f"observer {args.name!r}",
        change_payload={"op": "rm", "target": "observer", "name": args.name},
    )
    if rc == 0:
        _ok(f"removed observer {args.name!r} from {vertex_path.name}")
    return rc


# ---------------------------------------------------------------------------
# Subcommand: combine
# ---------------------------------------------------------------------------


def _rm_combine(target: str, argv: list[str]) -> int:
    p = argparse.ArgumentParser(prog="loops rm <vertex> combine", add_help=True)
    p.add_argument("path", help="Combine entry path to remove")
    try:
        args = p.parse_args(argv)
    except SystemExit as e:
        return int(e.code) if e.code is not None else 1

    vertex_path = _resolve_or_fail(target)
    if vertex_path is None:
        return 1

    rc = _splice_remove(
        vertex_path=vertex_path,
        parent=["combine"],
        child_name="vertex",
        child_key=args.path,
        key_field=None,  # positional first-quoted-arg match
        not_found_desc=f"combine entry {args.path!r}",
        change_payload={"op": "rm", "target": "combine", "path": args.path},
    )
    if rc == 0:
        _ok(f"removed combine {args.path!r} from {vertex_path.name}")
    return rc


# ---------------------------------------------------------------------------
# Subcommand: row (direct .list file removal — no facts)
# ---------------------------------------------------------------------------


def _rm_row(target: str, argv: list[str]) -> int:
    """Remove a row from a template population's .list file.

    Direct file mutation via lang.population.list_file_rm — no facts emitted,
    no fold materialization. Phase 3 dissolves the rss-era pop-fact surface;
    the .list file IS the canonical source.
    """
    if not argv:
        _err("loops rm: missing key for row")
        return 2
    p = argparse.ArgumentParser(prog="loops rm <vertex> row", add_help=True)
    p.add_argument("key", help="Row key (first column) to remove")
    try:
        args = p.parse_args(argv)
    except SystemExit as e:
        return int(e.code) if e.code is not None else 1

    list_path = _resolve_population_list(target)
    if list_path is None:
        return 1

    from lang.population import list_file_rm
    removed = list_file_rm(list_path, args.key)
    if not removed:
        _err(f"no row matching key {args.key!r} in {list_path.name}")
        return 1
    _ok(f"removed row {args.key!r} from {list_path.name}")
    return 0


# ---------------------------------------------------------------------------
# Splice remove driver
# ---------------------------------------------------------------------------


def _splice_remove(
    *,
    vertex_path: Path,
    parent: list[str],
    child_name: str,
    child_key: str | None,
    key_field: str | None,
    not_found_desc: str,
    change_payload: dict[str, str],
) -> int:
    """Remove child from parent block. Validate before write. Emit change-fact."""
    from lang.population import kdl_find_block, kdl_remove_child

    text = vertex_path.read_text()

    # Parent must exist for removal to be meaningful.
    try:
        kdl_find_block(text, parent)
    except ValueError:
        _err(f"no {'.'.join(parent)} block in {vertex_path.name}")
        return 1

    try:
        new_text = kdl_remove_child(
            text, parent, child_name, child_key, key_field=key_field
        )
    except ValueError:
        _err(f"{not_found_desc} not found in {vertex_path.name}")
        return 1

    # Symmetric inverse of add's auto-create: if removing this child empties
    # an optional parent block (observers, combine), drop the block too.
    # The validator rejects empty observers blocks; combine vertices need at
    # least one entry. Without this, rm of the last child would always fail
    # the refuses-and-preserves invariant.
    new_text = _strip_empty_optional_parent(new_text, parent)

    # Validate by re-parsing before writing — never leave a vertex unparseable.
    try:
        from lang import parse_vertex
        parse_vertex(new_text)
    except Exception as exc:  # noqa: BLE001 — surface any parse failure
        _err(f"refused to write: result would not parse ({exc})")
        return 1

    vertex_path.write_text(new_text)

    # Optional change-fact emission (symmetric with add).
    _maybe_emit_change(vertex_path, change_payload)
    return 0


_OPTIONAL_PARENTS = frozenset({("observers",), ("combine",)})


def _strip_empty_optional_parent(text: str, parent: list[str]) -> str:
    """If parent is an optional top-level block and is now empty, remove it.

    Optional blocks: observers, combine. The validator rejects an empty
    observers block ("requires at least one observer") and combine vertices
    must have at least one entry. We never want to leave the file in that
    state — symmetric with add's auto-create-when-missing.
    """
    if tuple(parent) not in _OPTIONAL_PARENTS:
        return text
    from lang.population import kdl_find_block

    try:
        start, end = kdl_find_block(text, parent)
    except ValueError:
        return text
    lines = text.splitlines()
    had_trailing = text.endswith("\n")
    # Check whether any non-blank, non-comment, non-brace line remains inside.
    has_child = False
    for i in range(start + 1, end):
        s = lines[i].strip()
        if not s:
            continue
        if s.startswith("//"):
            continue
        if s == "}":
            continue
        has_child = True
        break
    if has_child:
        return text
    # Remove the block lines [start..end] and any single leading blank line.
    cut_start = start
    if cut_start > 0 and lines[cut_start - 1].strip() == "":
        cut_start -= 1
    del lines[cut_start : end + 1]
    result = "\n".join(lines)
    if had_trailing and not result.endswith("\n"):
        result += "\n"
    return result


def _maybe_emit_change(vertex_path: Path, payload: dict[str, str]) -> None:
    """Emit a `change` fact iff the vertex declares a change loop kind."""
    from lang import parse_vertex_file

    try:
        vf = parse_vertex_file(vertex_path)
    except Exception:  # noqa: BLE001 — diagnostics only, don't fail the mutation
        return
    if "change" not in (vf.loops or {}):
        return

    from datetime import datetime, timezone
    from atoms import Fact
    from engine import SqliteStore
    from loops.commands.identity import resolve_observer
    from loops.commands.resolve import _resolve_vertex_store_path

    store_path = _resolve_vertex_store_path(vertex_path.resolve())
    if store_path is None:
        return

    observer = resolve_observer()
    fact = Fact(
        kind="change",
        observer=observer,
        ts=datetime.now(timezone.utc).timestamp(),
        payload=payload,
        origin="",
    )
    store_path.parent.mkdir(parents=True, exist_ok=True)
    with SqliteStore(
        path=store_path,
        serialize=Fact.to_dict,
        deserialize=Fact.from_dict,
    ) as store:
        store.append(fact)


# ---------------------------------------------------------------------------
# Resolution helpers
# ---------------------------------------------------------------------------


def _resolve_or_fail(target: str) -> Path | None:
    from lang.population import resolve_vertex
    from loops.commands.resolve import loops_home

    vertex_path = resolve_vertex(target, loops_home())
    if not vertex_path.exists():
        _err(f"vertex not found: {vertex_path}")
        return None
    return vertex_path


def _resolve_population_list(target: str) -> Path | None:
    """Resolve a vertex/template target to its .list file path.

    The vertex must be parseable and have a file-backed template population.
    """
    from lang import parse_vertex_file
    from lang.ast import FromFile, TemplateSource
    from lang.population import resolve_template, resolve_vertex
    from loops.commands.resolve import loops_home

    # Support qualified targets like "reading/feeds" for multi-template vertices.
    if "/" in target and not target.startswith(("./", "/")):
        vertex_ref, qualifier = target.split("/", 1)
    else:
        vertex_ref, qualifier = target, None

    vertex_path = resolve_vertex(vertex_ref, loops_home())
    if not vertex_path.exists():
        _err(f"vertex not found: {vertex_path}")
        return None

    try:
        vertex = parse_vertex_file(vertex_path)
    except Exception as exc:  # noqa: BLE001
        _err(f"failed to parse {vertex_path.name}: {exc}")
        return None

    try:
        template = resolve_template(vertex, qualifier)
    except ValueError as exc:
        _err(str(exc))
        return None

    if not isinstance(template, TemplateSource) or not isinstance(
        template.from_, FromFile
    ):
        _err(
            f"template in {vertex_path.name} is not file-backed "
            "(no 'from file \"...\"')"
        )
        return None

    list_path = template.from_.path
    if not list_path.is_absolute():
        list_path = (vertex_path.parent / list_path).resolve()
    if not list_path.exists():
        _err(f".list file does not exist: {list_path}")
        return None
    return list_path


def _ok(msg: str) -> None:
    from painted import Block, show
    from painted.palette import current_palette

    show(Block.text(msg, current_palette().success), file=sys.stdout)


def _err(msg: str) -> None:
    from painted import Block, show
    from painted.palette import current_palette

    show(Block.text(f"Error: {msg}", current_palette().error), file=sys.stderr)
