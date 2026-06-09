"""`loops add <vertex> <subcommand>` — vertex declaration mutations.

Phase 2 of plan:vertex-living-document. The CLI becomes the management surface
for vertex declarations via the kdl_splice library introduced in Phase 1.

Subcommands:
  kind      add a loop kind with a fold op
  observer  add an observer (optional identity + grant)
  combine   add an aggregation entry
  row       add a row to a template population (delegates to legacy pop.cmd_add)

Bare-positional form (``loops add <vertex> <K> <V> ...``) is preserved as a
back-compat alias for ``row`` and will be retired in Phase 3.

When the target vertex has a ``change`` loop kind defined, each declaration
emits a ``change`` fact with the mutation details. Vertices without a
``change`` kind stay quiet.
"""

from __future__ import annotations

import argparse
import sys
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from pathlib import Path


_SUBCOMMANDS = frozenset({"kind", "observer", "combine", "row"})


def _run_add(argv: list[str]) -> int:
    """Dispatch ``loops add <vertex> <subcommand-or-positional> ...``.

    If argv[1] is a known subcommand, route to the subcommand handler.
    Otherwise, treat argv[1..] as legacy population-row positionals.
    """
    if not argv:
        _err("loops add: missing vertex target")
        return 2
    if argv[0] in ("-h", "--help"):
        _print_add_help()
        return 0

    target = argv[0]
    rest = argv[1:]

    if rest and rest[0] in _SUBCOMMANDS:
        sub = rest[0]
        sub_argv = rest[1:]
        if sub == "kind":
            return _add_kind(target, sub_argv)
        if sub == "observer":
            return _add_observer(target, sub_argv)
        if sub == "combine":
            return _add_combine(target, sub_argv)
        if sub == "row":
            return _legacy_row(target, sub_argv)

    # Intercept --help before bare-positional fallthrough reaches vertex resolution.
    if rest and rest[0] in ("-h", "--help"):
        _print_add_help()
        return 0

    # Back-compat: bare positionals == implicit `row` subcommand.
    return _legacy_row(target, rest)


def _print_add_help() -> None:
    import sys
    p = argparse.ArgumentParser(
        prog="loops add",
        description="Add a declaration to a vertex file, or a row to a template population.",
    )
    p.add_argument("vertex", help="Vertex name")
    p.add_argument(
        "subcommand", nargs="?",
        choices=["kind", "observer", "combine", "row"],
        help="kind / observer / combine / row (default: row)",
    )
    p.print_help(sys.stdout)


# ---------------------------------------------------------------------------
# Subcommand: kind
# ---------------------------------------------------------------------------


def _add_kind(target: str, argv: list[str]) -> int:
    """``loops add <vertex> kind <NAME> <fold-op>``."""
    p = argparse.ArgumentParser(prog="loops add <vertex> kind", add_help=True)
    p.add_argument("name", help="Loop kind name (e.g. decision, thread)")
    p.add_argument("--target", default="items", help="Fold target field (default: items)")
    # Mutually-exclusive fold-op flags. Required: exactly one.
    op = p.add_mutually_exclusive_group(required=True)
    op.add_argument("--by", metavar="FIELD", help="FoldBy: upsert per fact keyed on FIELD")
    op.add_argument(
        "--collect", type=int, nargs="?", const=20, metavar="N",
        help="FoldCollect: keep last N (default 20)",
    )
    op.add_argument("--count", action="store_true", help="FoldCount: increment counter")
    op.add_argument("--latest", action="store_true", help="FoldLatest: most recent")
    op.add_argument("--max", metavar="FIELD", help="FoldMax: track max of FIELD")
    op.add_argument("--min", metavar="FIELD", help="FoldMin: track min of FIELD")
    op.add_argument("--sum", metavar="FIELD", help="FoldSum: sum of FIELD")
    op.add_argument("--avg", metavar="FIELD", help="FoldAvg: average of FIELD")
    op.add_argument(
        "--window", nargs=2, metavar=("FIELD", "SIZE"),
        help="FoldWindow: rolling buffer of FIELD with size SIZE",
    )

    try:
        args = p.parse_args(argv)
    except SystemExit as e:
        return int(e.code) if e.code is not None else 1

    op_text, op_payload = _format_fold_op(args)
    child_text = f'{args.name} {{ fold {{ {args.target} {op_text} }} }}'

    vertex_path = _resolve_or_fail(target)
    if vertex_path is None:
        return 1

    rc = _splice_into(
        vertex_path=vertex_path,
        parent=["loops"],
        ensure_parent_kdl=None,  # parser requires `loops {}` already exists
        child_text=child_text,
        duplicate_check=("kind", args.name),
        change_payload={
            "op": "add",
            "target": "kind",
            "name": args.name,
            **op_payload,
            "fold_target": args.target,
        },
    )
    if rc == 0:
        _ok(f"added kind {args.name!r} ({op_text.strip()}) to {_display_path(vertex_path)}")
    return rc


def _format_fold_op(args: argparse.Namespace) -> tuple[str, dict[str, str]]:
    """Render the fold-op tail KDL + payload metadata."""
    if args.by:
        return f'"by" "{args.by}"', {"fold_op": "by", "fold_arg": args.by}
    if args.collect is not None:
        return f'"collect" {args.collect}', {"fold_op": "collect", "fold_arg": str(args.collect)}
    if args.count:
        return '"count"', {"fold_op": "count"}
    if args.latest:
        return '"latest"', {"fold_op": "latest"}
    if args.max:
        return f'"max" "{args.max}"', {"fold_op": "max", "fold_arg": args.max}
    if args.min:
        return f'"min" "{args.min}"', {"fold_op": "min", "fold_arg": args.min}
    if args.sum:
        return f'"sum" "{args.sum}"', {"fold_op": "sum", "fold_arg": args.sum}
    if args.avg:
        return f'"avg" "{args.avg}"', {"fold_op": "avg", "fold_arg": args.avg}
    if args.window:
        field, size = args.window
        # KDL fold-op grammar: window <size:int> <field:str>
        return f'"window" {size} "{field}"', {"fold_op": "window", "fold_arg": field, "fold_size": size}
    # Unreachable — argparse enforces required.
    raise AssertionError("no fold op provided")


# ---------------------------------------------------------------------------
# Subcommand: observer
# ---------------------------------------------------------------------------


def _add_observer(target: str, argv: list[str]) -> int:
    """``loops add <vertex> observer <NAME> [--identity X] [--grant K1,K2,...]``."""
    p = argparse.ArgumentParser(prog="loops add <vertex> observer", add_help=True)
    p.add_argument("name", help="Observer name")
    p.add_argument("--identity", help="Vertex name backing this observer's identity store")
    p.add_argument(
        "--grant", default="",
        help="Comma-separated kinds this observer is allowed to emit",
    )
    try:
        args = p.parse_args(argv)
    except SystemExit as e:
        return int(e.code) if e.code is not None else 1

    grants = [k.strip() for k in args.grant.split(",") if k.strip()] if args.grant else []

    # Render the observer KDL block.
    if not args.identity and not grants:
        child_text = f"{args.name} {{ }}"
    else:
        body_lines = []
        if args.identity:
            body_lines.append(f'  identity "{args.identity}"')
        if grants:
            kinds = " ".join(f'"{k}"' for k in grants)
            body_lines.append("  grant {")
            body_lines.append(f"    potential {kinds}")
            body_lines.append("  }")
        child_text = f"{args.name} {{\n" + "\n".join(body_lines) + "\n}"

    vertex_path = _resolve_or_fail(target)
    if vertex_path is None:
        return 1

    rc = _splice_into(
        vertex_path=vertex_path,
        parent=["observers"],
        ensure_parent_kdl="observers {\n}\n",
        child_text=child_text,
        duplicate_check=("observer", args.name),
        change_payload={
            "op": "add",
            "target": "observer",
            "name": args.name,
            **({"identity": args.identity} if args.identity else {}),
            **({"grants": ",".join(grants)} if grants else {}),
        },
    )
    if rc == 0:
        bits = [args.name]
        if args.identity:
            bits.append(f"identity={args.identity}")
        if grants:
            bits.append(f"grant={','.join(grants)}")
        _ok(f"added observer {' '.join(bits)} to {_display_path(vertex_path)}")
    return rc


# ---------------------------------------------------------------------------
# Subcommand: combine
# ---------------------------------------------------------------------------


def _add_combine(target: str, argv: list[str]) -> int:
    """``loops add <vertex> combine <PATH-OR-NAME> [--as ALIAS]``."""
    p = argparse.ArgumentParser(prog="loops add <vertex> combine", add_help=True)
    p.add_argument("path", help="Path or vertex name to combine into this vertex")
    p.add_argument("--as", dest="alias", help="Optional alias for slash-qualified reads")
    try:
        args = p.parse_args(argv)
    except SystemExit as e:
        return int(e.code) if e.code is not None else 1

    if args.alias:
        child_text = f'vertex "{args.path}" as="{args.alias}"'
    else:
        child_text = f'vertex "{args.path}"'

    vertex_path = _resolve_or_fail(target)
    if vertex_path is None:
        return 1

    rc = _splice_into(
        vertex_path=vertex_path,
        parent=["combine"],
        ensure_parent_kdl="combine {\n}\n",
        child_text=child_text,
        duplicate_check=("combine", args.path),
        change_payload={
            "op": "add",
            "target": "combine",
            "path": args.path,
            **({"alias": args.alias} if args.alias else {}),
        },
    )
    if rc == 0:
        bits = [args.path]
        if args.alias:
            bits.append(f"as={args.alias}")
        _ok(f"added combine {' '.join(bits)} to {_display_path(vertex_path)}")
    return rc


# ---------------------------------------------------------------------------
# Legacy row delegation
# ---------------------------------------------------------------------------


def _legacy_row(target: str, argv: list[str]) -> int:
    """Add a row to a template population's .list file (direct write).

    Phase 3 dissolves the rss-era pop-fact indirection: the .list file is
    canonical, no facts emitted. Reachable as `loops add <vertex> row K V`
    or via bare-positional back-compat `loops add <vertex> K V`.
    """
    if argv and argv[0] in ("-h", "--help"):
        _print_add_help()
        return 0
    if not argv:
        _err("loops add: missing values for row")
        return 2

    from lang import parse_vertex_file
    from lang.ast import FromFile, TemplateSource
    from lang.population import (
        PopulationRow,
        list_file_add,
        list_file_header,
        resolve_template,
    )
    from loops.commands.resolve import _resolve_target_or_fail

    if "/" in target and not target.startswith(("./", "/")):
        vertex_ref, qualifier = target.split("/", 1)
    else:
        vertex_ref, qualifier = target, None

    vertex_path = _resolve_target_or_fail(vertex_ref)
    if vertex_path is None:
        return 1

    try:
        vf = parse_vertex_file(vertex_path)
    except Exception as exc:  # noqa: BLE001
        _err(f"failed to parse {_display_path(vertex_path)}: {exc}")
        return 1

    try:
        template = resolve_template(vf, qualifier)
    except ValueError as exc:
        _err(str(exc))
        return 1

    if not isinstance(template, TemplateSource) or not isinstance(
        template.from_, FromFile
    ):
        _err(
            f"template in {_display_path(vertex_path)} is not file-backed "
            "(no 'from file \"...\"')"
        )
        return 1

    list_path = template.from_.path
    if not list_path.is_absolute():
        list_path = (vertex_path.parent / list_path).resolve()

    header = list_file_header(list_path)
    if not header:
        _err(f"no .list header at {list_path}")
        return 1

    values = list(argv)
    # Last column gets the remainder (allows spaces in last value).
    if len(values) > len(header):
        head = values[: len(header) - 1]
        tail = " ".join(values[len(header) - 1 :])
        values = head + [tail]
    if len(values) != len(header):
        _err(
            f"expected {len(header)} values ({', '.join(header)}), "
            f"got {len(values)}"
        )
        return 1

    row = PopulationRow(
        key=values[0],
        values=dict(zip(header, values)),
    )
    list_file_add(list_path, header, row)
    _ok(f"added row {values[0]!r} to {_display_path(list_path)}")
    return 0


# ---------------------------------------------------------------------------
# Splice driver
# ---------------------------------------------------------------------------


def _splice_into(
    *,
    vertex_path: Path,
    parent: list[str],
    ensure_parent_kdl: str | None,
    child_text: str,
    duplicate_check: tuple[str, str],
    change_payload: dict[str, str],
) -> int:
    """Splice child_text into parent block of vertex_path, validate, write, emit.

    - ensure_parent_kdl: when set, auto-create the parent block at top level
      if it doesn't exist (used for optional sections like observers/combine).
    - duplicate_check: (kind, name) — if a child with this name already exists
      under the parent, refuse the mutation.
    - change_payload: emitted as a `change` fact when the vertex declares one.
    """
    from lang.population import kdl_find_block, kdl_insert_child

    text = vertex_path.read_text()

    # Ensure parent section exists.
    try:
        kdl_find_block(text, parent)
    except ValueError:
        if ensure_parent_kdl is None:
            _err(
                f"vertex {_display_path(vertex_path)} has no {'.'.join(parent)} block; "
                "cannot insert"
            )
            return 1
        # Append the parent section.
        if not text.endswith("\n"):
            text += "\n"
        text += "\n" + ensure_parent_kdl

    # Duplicate-check: refuse if a child with this name already exists.
    _kind, dup_name = duplicate_check
    if _child_exists(text, parent, dup_name):
        _err(
            f"{_kind} {dup_name!r} already exists in {_display_path(vertex_path)}; "
            f"use `loops rm` first or pick a different name"
        )
        return 1

    new_text = kdl_insert_child(text, parent, child_text)

    # Validate by re-parsing before writing — never leave a vertex unparseable.
    try:
        from lang import parse_vertex
        parse_vertex(new_text)
    except Exception as exc:  # noqa: BLE001 — surface any parse failure
        _err(f"refused to write: result would not parse ({exc})")
        return 1

    vertex_path.write_text(new_text)

    # Optional change-fact emission.
    _maybe_emit_change(vertex_path, change_payload)
    return 0


def _child_exists(text: str, parent: list[str], child_name: str) -> bool:
    """True if a child matching child_name exists under parent.

    Block children (e.g. `decision { ... }`, `kyle { }`): matched via
    kdl_find_block by first-token.

    Non-block line children (combine's `vertex "..."`): matched by scanning
    the parent block's lines for `vertex "child_name"` because kdl_find_block
    requires a `{` to identify a block.
    """
    from lang.population import kdl_find_block

    if parent == ["combine"]:
        # combine entries are single-line `vertex "<path>"` — line scan.
        try:
            start, end = kdl_find_block(text, parent)
        except ValueError:
            return False
        from pathlib import Path
        target = Path(child_name)
        lines = text.splitlines()
        import re
        for i in range(start + 1, end):
            stripped = lines[i].strip()
            if not stripped.startswith("vertex"):
                continue
            m = re.search(r'"([^"]+)"', stripped)
            if m and Path(m.group(1)) == target:
                return True
        return False

    try:
        kdl_find_block(text, [*parent, child_name])
        return True
    except ValueError:
        return False


def _maybe_emit_change(vertex_path: Path, payload: dict[str, str]) -> None:
    """Emit a `change` fact iff the vertex declares a change loop kind."""
    from lang import parse_vertex_file

    try:
        vf = parse_vertex_file(vertex_path)
    except Exception:  # noqa: BLE001 — diagnostics fine, don't fail the mutation
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
# Vertex resolution + output helpers
# ---------------------------------------------------------------------------


def _resolve_or_fail(target: str) -> Path | None:
    """Local-first resolution — same path the verbs use (read/emit/cite).

    Declaration commands must edit the file the verbs actually read;
    see thread:global-local-walk-broken for the incident this fixes.
    """
    from loops.commands.resolve import _resolve_target_or_fail

    return _resolve_target_or_fail(target)


def _display_path(path: Path) -> str:
    """Receipts print the full path written — never just the basename."""
    from loops.commands.resolve import _display_path as _dp

    return _dp(path)


def _ok(msg: str) -> None:
    from painted import Block, show
    from painted.palette import current_palette

    show(Block.text(msg, current_palette().success), file=sys.stdout)


def _err(msg: str) -> None:
    from painted import Block, show
    from painted.palette import current_palette

    show(Block.text(f"Error: {msg}", current_palette().error), file=sys.stderr)
