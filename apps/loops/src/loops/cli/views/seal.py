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
from pathlib import Path

from ..context import CliContext
from . import emit as emit_view


def _store_in_signed_era(vertex_path: Path) -> bool:
    """True when the store behind *vertex_path* already carries signed ticks.

    The signed era is the state — not a declaration — where regressing to an
    unsigned tick breaks chain era-monotonicity (``verify`` reports CHAIN
    BROKEN). Drives the seal era-guard below
    (decision:design/tick-signing-era-is-a-floor). A missing store / absent
    signature column means "not yet in the era" → False.
    """
    import sqlite3

    from loops.commands.store import resolve_store_path

    try:
        db = resolve_store_path(vertex_path)
    except (ValueError, FileNotFoundError):
        return False
    if not db.exists():
        return False
    conn = sqlite3.connect(str(db))
    try:
        cols = {r[1] for r in conn.execute("PRAGMA table_info(ticks)")}
        # Both columns are referenced by the predicate below; on a partially
        # migrated/legacy ticks table either may be absent (bare connection,
        # no _ensure_chain_columns) — guard both or the query raises
        # OperationalError, which this except does not catch.
        if "signature" not in cols or "window_hash" not in cols:
            return False
        # Match verify_chain's era boundary exactly: a *chained* signed tick
        # (window_hash NOT NULL), not a legacy pre-chain signed row — so the
        # friendly verb pre-check refuses precisely what the engine floor and
        # verify_chain would, no over-refusal divergence.
        row = conn.execute(
            "SELECT EXISTS(SELECT 1 FROM ticks "
            "WHERE signature IS NOT NULL AND window_hash IS NOT NULL)"
        ).fetchone()
        return bool(row and row[0])
    finally:
        conn.close()


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
    if writable is None:
        ctx.reporter.err(
            "seal: no writable vertex with a store found — an aggregator "
            "with no constituent store cannot mint a tick"
        )
        return 1
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

    # Era-guard (decision:design/tick-signing-era-is-a-floor): once a store has
    # signed ticks, a seal that cannot sign would mint an UNSIGNED tick and
    # break chain era-monotonicity (verify -> CHAIN BROKEN). Match reanchor's
    # refusal — a hard stop, not a silent downgrade to unauthenticated (SSH:
    # missing key denies, it does not fall back). A never-signed (pre-era)
    # store sealing unsigned is legitimate and proceeds. --dry-run mints
    # nothing, so it is exempt. (Scoped to the seal verb — and so also the
    # SessionEnd hook, which seals through here; promoting the guard into the
    # engine mint to cover emit-triggered boundaries is thread:
    # seal-era-boundary-guard.)
    from loops.commands.signing import tick_signer_for

    if (
        not args.dry_run
        and tick_signer_for(writable) is None
        and _store_in_signed_era(writable)
    ):
        ctx.reporter.err(
            "seal: store is in the signed era but no signing key found — "
            "refusing to mint an unsigned tick (it would break chain "
            "era-monotonicity).\n"
            "  the window's facts are stored; run seal again once the key is "
            "available to close the accumulated window."
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
