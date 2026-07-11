"""cli.views.orient — stable session-start summary."""
from __future__ import annotations

import argparse

from ..invocation import Invocation


def run(argv: list[str], ctx: Invocation) -> int:
    """Render the session-start orient block for a vertex."""
    parser = argparse.ArgumentParser(prog="loops orient")
    if ctx.vertex_path is None:
        parser.add_argument(
            "vertex",
            nargs="?",
            default=None,
            help="Vertex name or .vertex path (defaults to local vertex)",
        )
    try:
        args = parser.parse_args(argv)
    except SystemExit as exc:
        return int(exc.code) if exc.code is not None else 2

    vertex_path = ctx.vertex_path
    if vertex_path is None:
        from loops.commands.identity import resolve_local_vertex
        from loops.commands.resolve import (
            _resolve_named_vertex,
            _resolve_vertex_for_dispatch,
        )

        vertex_ref = getattr(args, "vertex", None)
        if vertex_ref is not None:
            vertex_path = _resolve_vertex_for_dispatch(vertex_ref)
            if vertex_path is None:
                try:
                    vertex_path = _resolve_named_vertex(vertex_ref)
                except Exception:
                    ctx.reporter.err(f"orient: no vertex named '{vertex_ref}' found")
                    return 1
        else:
            try:
                vertex_path = resolve_local_vertex()
            except FileNotFoundError:
                ctx.reporter.err(
                    "orient: no vertex specified and no local vertex found\n"
                    "  hint: use `sl orient <vertex>` or run from a vertex directory"
                )
                return 1

    from loops.commands.orient import build_orient_summary, render_orient

    text = render_orient(build_orient_summary(vertex_path))
    ctx.reporter.show(text)
    return 0
