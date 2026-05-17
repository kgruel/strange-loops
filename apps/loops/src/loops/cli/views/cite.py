"""cli.views.cite — cite verb.

Dissolves into emit with kind=cite. The view's job is to parse the
``loops cite [vertex] REF1 REF2 ... [--context NAME] [-m MSG] [--dry-run]``
shape and translate it into the emit view's argv (``[vertex?] cite
ref=R1 ref=R2 ... [--flags]``), then delegate.

Design rationale: ``design/cite-as-attention-signal``,
``design/cite-as-partial-information-primitive``.
"""
from __future__ import annotations

import argparse

from ..context import CliContext
from . import emit as emit_view


def run(argv: list[str], ctx: CliContext) -> int:
    """Parse cite-shape args, translate to emit-shape, delegate."""
    parser = argparse.ArgumentParser(prog="loops cite", add_help=False)
    if ctx.vertex_path is None:
        parser.add_argument("vertex", nargs="?", default=None)
    parser.add_argument(
        "refs", nargs="+",
        help="kind/key refs or bare ULIDs — the attention targets",
    )
    parser.add_argument(
        "--context", default=None,
        help="Optional thread or task name to tag the citation",
    )
    parser.add_argument(
        "-m", "--message", default=None,
        help="Optional in-the-moment context for the citation",
    )
    parser.add_argument(
        "--dry-run", action="store_true",
        help="Print the fact JSON without storing",
    )
    try:
        args = parser.parse_args(argv)
    except SystemExit as exc:
        return int(exc.code or 2)

    emit_argv: list[str] = []
    if ctx.vertex_path is None:
        vname = getattr(args, "vertex", None)
        if vname:
            emit_argv.append(vname)
    emit_argv.append("cite")
    for r in args.refs:
        emit_argv.append(f"ref={r}")
    if args.context:
        emit_argv.append(f"context={args.context}")
    if args.message:
        emit_argv.append(f"message={args.message}")
    if args.dry_run:
        emit_argv.append("--dry-run")

    return emit_view.run(emit_argv, ctx)
