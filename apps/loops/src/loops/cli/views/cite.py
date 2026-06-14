"""cli.views.cite — cite verb.

Dissolves into emit with kind=cite. The view's job is to parse the
``loops cite REF1 REF2 ... [--context NAME] [-m MSG] [--dry-run]``
shape and translate it into the emit view's argv (``cite ref=R1
ref=R2 ... [--flags]``), then delegate.

When ctx.vertex_path is None (verb-first dispatch), the local vertex
is resolved from the working directory. This avoids the argparse
greedy-positional bug: an optional ``vertex (nargs="?")`` preceding
``refs (nargs="+")`` causes argparse to absorb the first ref into the
vertex slot, silently dropping it from the payload.

Vertex-first form (``sl project cite REF1 REF2``) is unchanged — that
path sets ctx.vertex_path before calling this view.

Design rationale: ``design/cite-as-attention-signal``,
``design/cite-as-partial-information-primitive``.
"""
from __future__ import annotations

import argparse

from ..invocation import Invocation
from . import emit as emit_view


def run(argv: list[str], ctx: Invocation) -> int:
    """Parse cite-shape args, translate to emit-shape, delegate."""
    parser = argparse.ArgumentParser(prog="loops cite")
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
        return int(exc.code) if exc.code is not None else 2

    # Resolve vertex when not provided by vertex-first dispatch.
    # Never prepend a vertex name to emit_argv — the resolved ctx carries it.
    emit_ctx = ctx
    if ctx.vertex_path is None:
        from loops.commands.resolve import _find_local_vertex, _vertex_name

        local = _find_local_vertex()
        if local is None:
            ctx.reporter.err(
                "cite: no vertex specified and no local vertex found\n"
                "  hint: use `sl <vertex> cite ...` or run from a vertex directory"
            )
            return 1
        emit_ctx = Invocation(
            reporter=ctx.reporter,
            vertex_path=local.resolve(),
            vertex_name=_vertex_name(local),
            observer=ctx.observer,
            loops_home=ctx.loops_home,
            isatty=ctx.isatty,
        )

    emit_argv: list[str] = ["cite"]
    for r in args.refs:
        emit_argv.append(f"ref={r}")
    if args.context:
        emit_argv.append(f"context={args.context}")
    if args.message:
        emit_argv.append(f"message={args.message}")
    if args.dry_run:
        emit_argv.append("--dry-run")

    return emit_view.run(emit_argv, emit_ctx)
