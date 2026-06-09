"""cli.views.seal — the seal verb.

A seal is a deliberately drawn attestation boundary: the observer
driver from architecture/boundaries-as-driven-conditions, dissolved
into the fact stream. ``sl seal`` emits a ``seal`` fact; the vertex's
declared ``boundary when="seal"`` fires; the tick that mints (signed,
chained, witness-order window) is the attestation. The seal fact —
the reason — is the LAST fact inside the window it seals: the
attestation covers its own justification.

Session close is an instance of seal, not the other way around (the
SessionEnd hook emits its session bookkeeping fact, then seals).
Post-backfill attestation is a seal. A rebirth/migration receipt
closes with a seal. One act, several drivers.

Must-fire semantics: unlike emit, seal REFUSES when the resolved
writable vertex declares no ``boundary when="seal"`` — a seal that
cannot mint a tick is not a seal. When the declaration carries match
properties, they are folded into the emitted payload so the boundary
always fires. Fold-state ``condition`` gates are respected (the seal
defers to them); the receipt shows whether a tick minted.

Design anchors: thread/manual-tick-emission,
decision/architecture/boundaries-as-driven-conditions,
decision/design/chain-witness-order.
"""
from __future__ import annotations

import argparse

from ..context import CliContext
from . import emit as emit_view


def run(argv: list[str], ctx: CliContext) -> int:
    """Parse seal-shape args, pre-check sealability, delegate to emit."""
    parser = argparse.ArgumentParser(prog="loops seal")
    if ctx.vertex_path is None:
        parser.add_argument(
            "vertex",
            nargs="?",
            default=None,
            help="Vertex name or .vertex path (auto-resolves local vertex)",
        )
    parser.add_argument(
        "-m", "--message", default=None,
        help="Why this boundary is being drawn — sealed inside its own window",
    )
    parser.add_argument(
        "--observer", default=None,
        help="Observer string (defaults to .vertex declaration / $LOOPS_OBSERVER)",
    )
    parser.add_argument(
        "--dry-run", action="store_true",
        help="Print the seal fact JSON without storing",
    )
    parser.add_argument(
        "-q", "--quiet", action="store_true",
        help="Suppress the 'stored:' receipt (tick line still prints)",
    )
    try:
        args = parser.parse_args(argv)
    except SystemExit as exc:
        return int(exc.code) if exc.code is not None else 2

    # Resolve the vertex: vertex-first dispatch wins, then the positional,
    # then the local vertex (same chain as cite).
    vertex_path = ctx.vertex_path
    if vertex_path is None:
        from loops.commands.resolve import (
            _find_local_vertex,
            _resolve_vertex_for_dispatch,
            _vertex_name,
        )

        name = getattr(args, "vertex", None)
        if name is not None:
            vertex_path = _resolve_vertex_for_dispatch(name)
            if vertex_path is None:
                ctx.reporter.err(f"seal: no vertex named '{name}' found")
                return 1
        else:
            vertex_path = _find_local_vertex()
            if vertex_path is None:
                ctx.reporter.err(
                    "seal: no vertex specified and no local vertex found\n"
                    "  hint: use `sl seal <vertex>` or run from a vertex directory"
                )
                return 1
            vertex_path = vertex_path.resolve()
        ctx = CliContext(
            reporter=ctx.reporter,
            vertex_path=vertex_path,
            vertex_name=_vertex_name(vertex_path),
            observer=ctx.observer,
            loops_home=ctx.loops_home,
            isatty=ctx.isatty,
        )

    # Must-fire pre-check: the WRITABLE vertex (aggregators delegate to
    # their instance) has to declare the seal boundary before we emit.
    from lang import parse_vertex_file
    from lang.ast import BoundaryWhen
    from loops.commands.resolve import _resolve_writable_vertex

    writable = _resolve_writable_vertex(vertex_path)
    try:
        ast = parse_vertex_file(writable)
    except Exception as e:
        ctx.reporter.err(f"seal: cannot parse vertex '{writable}': {e}")
        return 1
    boundary = ast.boundary
    if not (isinstance(boundary, BoundaryWhen) and boundary.kind == "seal"):
        ctx.reporter.err(
            f"seal: vertex '{ast.name}' declares no seal boundary\n"
            "  hint: add `boundary when=\"seal\"` to its loops block — "
            "a seal that cannot mint a tick is not a seal"
        )
        return 1

    emit_argv: list[str] = ["seal"]
    if args.message:
        emit_argv.append(f"message={args.message}")
    # Fold declared match properties into the payload so the boundary fires.
    for k, v in boundary.match:
        emit_argv.append(f"{k}={v}")
    if args.observer:
        emit_argv.extend(["--observer", args.observer])
    if args.dry_run:
        emit_argv.append("--dry-run")
    if args.quiet:
        emit_argv.append("-q")

    return emit_view.run(emit_argv, ctx)
