"""cli.views.emit — the emit verb pilot.

First view to land on the new ``argparse → Operation → dispatch`` shape.
Action-style: ``render_lens=None`` — no rendering, ``cmd_emit`` produces
its own receipt and returns an exit code that dispatch surfaces.

Inputs (after observer is peeled off by ``cli.app``):

  loops emit [vertex] <kind> [KEY=VALUE ...] \
      [--dry-run] [--strict] [-q] [-v] [--json] [--declare-observer]

A single ``tokens`` bucket (``parse_intermixed_args``) + ``_classify_emit_positionals``
do the ``[vertex] kind parts`` split — KEY=VALUE is never mistaken for the vertex
or kind (the old greedy-positional bug). The parser + classifier are shared with
the legacy ``_run_emit`` via ``_build_emit_parser`` so the grammar lives once.

When dispatch handed us a resolved ``vertex_path`` (vertex-first form), the
classifier runs with ``has_vertex_path=True`` and the first bareword is the kind.

Design anchor: decision/design/cli-refactor-option-2-siftd-shape;
decision/operation-ir-adoption.
"""
from __future__ import annotations

from loops.commands.emit import cmd_emit, _build_emit_parser, _classify_emit_positionals

from ..invocation import Invocation
from ..dispatch import dispatch
from ..operation import Operation


def run(argv: list[str], ctx: Invocation) -> int:
    """Parse argv, classify positionals, build an Operation, dispatch.

    ``cmd_emit`` is bound as ``op.fn``; dispatch's action branch invokes
    it and surfaces its int return as the process exit code.
    """
    parser = _build_emit_parser(prog="loops emit")
    try:
        args = parser.parse_intermixed_args(argv)
    except SystemExit as exc:
        return int(exc.code) if exc.code is not None else 2

    vertex, kind, parts = _classify_emit_positionals(
        list(args.tokens), has_vertex_path=ctx.vertex_path is not None,
    )
    # When dispatch resolved the vertex, the classifier yields vertex=None and
    # cmd_emit relies on ctx.vertex_path.
    args.vertex = vertex
    args.kind = kind
    args.parts = parts

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
