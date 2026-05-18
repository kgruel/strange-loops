"""cli.views.emit — the emit verb pilot.

First view to land on the new ``argparse → Operation → dispatch`` shape.
Action-style: ``render_lens=None`` — no rendering, ``cmd_emit`` produces
its own receipt and returns an exit code that dispatch surfaces.

Inputs (after observer is peeled off by ``cli.app``):

  loops emit [vertex] <kind> [KEY=VALUE ...] [--dry-run] [--strict] [-q]

When dispatch handed us a resolved ``vertex_path`` (vertex-first form),
we skip the positional ``vertex`` argument and rely on ``ctx.vertex_path``.

Design anchor: decision/design/cli-refactor-option-2-siftd-shape;
decision/operation-ir-adoption.
"""
from __future__ import annotations

import argparse

from loops.commands.emit import cmd_emit

from ..context import CliContext
from ..dispatch import dispatch
from ..operation import Operation


def run(argv: list[str], ctx: CliContext) -> int:
    """Parse argv, build an Operation, dispatch.

    ``cmd_emit`` is bound as ``op.fn``; dispatch's action branch invokes
    it and surfaces its int return as the process exit code.
    """
    parser = argparse.ArgumentParser(prog="loops emit")
    if ctx.vertex_path is None:
        parser.add_argument(
            "vertex",
            nargs="?",
            default=None,
            help="Vertex name or .vertex path (auto-resolves local vertex)",
        )
    parser.add_argument("kind", help="Fact kind")
    parser.add_argument(
        "parts",
        nargs="*",
        help="KEY=VALUE pairs and optional trailing message text",
    )
    parser.add_argument(
        "--observer",
        default=None,
        help="Observer string (defaults to .vertex declaration / $LOOPS_OBSERVER)",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Print the fact JSON without storing",
    )
    parser.add_argument(
        "--strict",
        action="store_true",
        help=(
            "Refuse on validation failures (unknown kind, missing fold-key, "
            "unresolved ref). Overridden by vertex 'strict true' declaration."
        ),
    )
    parser.add_argument(
        "-q",
        "--quiet",
        action="store_true",
        help="Suppress the 'stored:' success receipt (WARN/ERROR still print).",
    )
    try:
        args = parser.parse_args(argv)
    except SystemExit as exc:
        return int(exc.code) if exc.code is not None else 1

    # When dispatch resolved the vertex, neutralise the positional so
    # cmd_emit's vertex-resolution branch is bypassed.
    if ctx.vertex_path is not None:
        args.vertex = None

    # Observer: command-level --observer wins; otherwise inherit the
    # observer ``cli.app`` peeled at dispatch time.
    if args.observer is None:
        args.observer = ctx.observer

    op = Operation(
        verb="emit",
        fn=cmd_emit,
        params={
            "args": args,
            "vertex_path": ctx.vertex_path,
            "reporter": ctx.reporter,
        },
        render_lens=None,
        vertex_path=ctx.vertex_path,
        observer=ctx.observer,
    )
    return dispatch(op, reporter=ctx.reporter)
