"""cli.views.cite — cite verb.

Dissolves into emit with kind=cite. The view's job is to parse the
``loops cite [vertex] REF1 REF2 ... [--context NAME] [-m MSG] [--dry-run]``
shape and translate it into the emit view's argv (``cite ref=R1
ref=R2 ... [--flags]``), then delegate.

The vertex slot is the intended verb-first grammar
(``sl <cmd> <vertex-if-required>``) — parity with emit. Classification
peels ``refs[0]`` as the vertex ONLY when it actually resolves as one
(``_resolve_vertex_for_dispatch``); emit's bare-``"/"`` heuristic is
deliberately NOT copied because a legacy slash-form ref
(``thread/arc-name``) is a legal cite positional. Resolution is the
discriminating check: a ``kind:key`` address never resolves as a vertex.

Refs are emitted as ``ref=R`` KEY=VALUE tokens, which the shared emit
grammar (a single ``tokens`` bucket + ``_classify_emit_positionals``)
keeps strictly as payload — never the vertex or kind. When no vertex is
named, the local vertex is resolved here exactly as emit's no-vertex
path does (ambiguity refusal, then ``_find_local_vertex`` — .loops/
aware) so no ref is ever absorbed into a positional slot.

Vertex-first form (``sl project cite REF1 REF2``) is unchanged — that
path sets ctx.vertex_path before calling this view, and no peel runs.

Design rationale: ``design/cite-as-attention-signal``,
``design/cite-as-partial-information-primitive``,
``friction:cite-verb-first-lacks-vertex-slot`` (S4).
"""
from __future__ import annotations

import argparse

from ..cite_args import add_cite_args
from ..invocation import Invocation
from . import emit as emit_view


def run(argv: list[str], ctx: Invocation) -> int:
    """Parse cite-shape args, translate to emit-shape, delegate."""
    parser = argparse.ArgumentParser(prog="loops cite")
    add_cite_args(parser)
    try:
        args = parser.parse_args(argv)
    except SystemExit as exc:
        return int(exc.code) if exc.code is not None else 2

    # Resolve vertex when not provided by vertex-first dispatch.
    # Never prepend a vertex name to emit_argv — the resolved ctx carries it.
    emit_ctx = ctx
    if ctx.vertex_path is None:
        from loops.commands.resolve import (
            _find_local_vertex,
            _resolve_vertex_for_dispatch,
            _vertex_name,
            ambiguous_local_vertex_refusal,
        )

        # Vertex slot: peel refs[0] iff it resolves as a vertex. Runs BEFORE
        # the ambiguity refusal — an explicitly named vertex needs no local
        # tie-break.
        named = _resolve_vertex_for_dispatch(args.refs[0])
        if named is not None:
            if len(args.refs) < 2:
                ctx.reporter.err(
                    f"cite: vertex '{args.refs[0]}' named but no refs given — "
                    "cite requires at least one ref\n"
                    "  usage: sl cite <vertex> REF ..."
                )
                return 2
            args.refs = args.refs[1:]
            chosen = named
        else:
            refusal = ambiguous_local_vertex_refusal("cite", "sl cite <vertex> REF ...")
            if refusal is not None:
                ctx.reporter.err(refusal)
                return 2

            local = _find_local_vertex()
            if local is None:
                ctx.reporter.err(
                    "cite: no vertex specified and no local vertex found\n"
                    "  hint: use `sl cite <vertex> REF ...` or run from a vertex directory"
                )
                return 1
            chosen = local.resolve()
        emit_ctx = Invocation(
            reporter=ctx.reporter,
            vertex_path=chosen,
            vertex_name=_vertex_name(chosen),
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
