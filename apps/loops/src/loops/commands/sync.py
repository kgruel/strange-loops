"""Sync and aggregate commands — cadence-gated source execution."""
from __future__ import annotations

import argparse
import sys
from pathlib import Path
from typing import TYPE_CHECKING

from loops.errors import LoopsError

if TYPE_CHECKING:
    from loops.cli.output import Reporter


def _reporter(reporter: "Reporter | None") -> "Reporter":
    """Resolve a Reporter — caller-supplied or the module default."""
    if reporter is None:
        from loops.cli.output import default_reporter
        return default_reporter()
    return reporter


def _resolve_combine_vertex_paths(vertex_path: Path) -> list[Path]:
    """Resolve an aggregation vertex's combine entries to child vertex paths.

    Mirrors engine.vertex_reader._resolve_combine_stores but returns vertex
    paths instead of store paths — we need VertexPrograms, not databases.
    """
    from lang import parse_vertex_file, resolve_vertex
    from loops.commands.resolve import loops_home

    ast = parse_vertex_file(vertex_path)
    if not ast.combine:
        return []

    home = loops_home()
    child_paths: list[Path] = []
    for entry in ast.combine:
        vpath = resolve_vertex(entry.name, home)
        if not vpath.is_absolute():
            vpath = (vertex_path.parent / vpath).resolve()
        if vpath.exists():
            child_paths.append(vpath)
    return child_paths


def _execute_boundary_run(
    command: str,
    tick_name: str,
    vertex_path: Path,
    *,
    reporter: "Reporter | None" = None,
) -> None:
    """Execute a boundary run clause — fire and forget.

    Engine produces ticks with run metadata. This function executes
    the command as a subprocess, inheriting the vertex directory as cwd.
    The command runs asynchronously — sync continues without waiting.

    Errors are logged to stderr but don't fail the sync.
    """
    import subprocess

    rep = _reporter(reporter)
    cwd = vertex_path.parent
    rep.err(f"  boundary {tick_name} → run: {command}")
    try:
        subprocess.Popen(
            command,
            shell=True,
            cwd=str(cwd),
            start_new_session=True,  # detach from parent process group
        )
    except OSError as e:
        rep.err(f"  [ERROR] boundary run failed: {e}")


def _run_sync_aggregate(
    child_paths: list[Path],
    *,
    vars: dict[str, str] | None,
    force: bool,
    parent_name: str,
    rest: list[str],
    reporter: "Reporter | None" = None,
) -> int:
    """Sync each combine child independently and aggregate results."""
    from painted import run_cli, show, Block
    from painted.palette import current_palette
    from engine import load_vertex_program

    rep = _reporter(reporter)
    label = "force" if force else "cadence-gated"
    show(
        Block.text(
            f"Syncing {parent_name}: {len(child_paths)} children ({label})",
            current_palette().muted,
        ),
        file=sys.stderr,
    )

    def log_error(fact):
        payload = dict(fact.payload) if hasattr(fact.payload, "items") else fact.payload
        rep.err(f"[ERROR] {fact.observer}: {payload}")

    def fetch():
        all_ran: list[str] = []
        all_skipped: list[dict] = []
        all_errors: list[dict] = []
        all_ticks: list[dict] = []
        all_fact_counts: dict[str, int] = {}
        children: list[dict] = []

        for child_path in child_paths:
            from loops.commands.signing import tick_signer_for
            child_program = load_vertex_program(
                child_path, vars=vars, run_dispatcher=_execute_boundary_run,
                tick_signer=tick_signer_for(child_path),
            )
            if not child_program.sources:
                continue
            # Boundary run clauses dispatched inside program.sync().
            result = child_program.sync(on_error=log_error, force=force)

            all_ran.extend(result.ran)
            all_skipped.extend(
                {"kind": s.kind, "last_run_ts": s.last_run_ts, "cadence_interval": s.cadence_interval}
                for s in result.skipped
            )
            for kind, count in result.fact_counts.items():
                all_fact_counts[kind] = all_fact_counts.get(kind, 0) + count
            all_errors.extend(
                {
                    "kind": e.kind,
                    "observer": e.observer,
                    "payload": dict(e.payload) if hasattr(e.payload, "items") else e.payload,
                }
                for e in result.errors
            )
            all_ticks.extend(
                {
                    "name": tick.name,
                    "ts": tick.ts,
                    "payload": tick.payload,
                    "origin": getattr(tick, "origin", ""),
                    **({"run": tick.run} if tick.run else {}),
                }
                for tick in result.ticks
            )
            children.append({
                "name": child_program.name,
                "ran": result.ran,
                "skipped": [
                    {"kind": s.kind, "last_run_ts": s.last_run_ts, "cadence_interval": s.cadence_interval}
                    for s in result.skipped
                ],
                "fact_counts": result.fact_counts,
            })

        return {
            "ran": all_ran,
            "skipped": all_skipped,
            "fact_counts": all_fact_counts,
            "errors": all_errors,
            "ticks": all_ticks,
            "children": children,
        }

    def render(ctx, data):
        from loops.lenses.sync import sync_view
        return sync_view(data, ctx.zoom, ctx.width)

    return run_cli(
        rest,
        fetch=fetch,
        render=render,
        prog="loops sync",
        description=f"Sync vertex {parent_name} (aggregation)",
    )


def _run_sync(
    argv: list[str],
    *,
    vertex_path: Path | None = None,
    reporter: "Reporter | None" = None,
) -> int:
    """Sync verb — cadence-gated source execution.

    ``loops sync [vertex] [--force] [--var KEY=VALUE]``

    Default: evaluate cadence predicates, run stale sources.
    --force: run all sources unconditionally.
    """
    from painted import run_cli, show, Block
    from painted.palette import current_palette
    from engine import load_vertex_program
    from loops.commands.resolve import _resolve_named_vertex
    from loops.commands.resolve import _parse_vars, _resolve_vertex_path

    rep = _reporter(reporter)

    # Intercept --help before vertex resolution (pre-parser uses parse_known_args
    # so argparse would not catch --help itself).
    if "-h" in argv or "--help" in argv:
        import sys as _sys
        _help = argparse.ArgumentParser(prog="loops sync")
        if vertex_path is None:
            _help.add_argument("vertex", nargs="?", help="Vertex name or path")
        _help.add_argument("--force", "-f", action="store_true", help="Run all sources unconditionally")
        _help.add_argument("--var", action="append", metavar="KEY=VALUE", help="Variable override")
        _help.print_help(_sys.stdout)
        return 0

    pre = argparse.ArgumentParser(add_help=False)
    if vertex_path is None:
        pre.add_argument("vertex", nargs="?", default=None)
    pre.add_argument("--force", "-f", action="store_true", default=False)
    pre.add_argument("--var", action="append", default=[])
    known, rest = pre.parse_known_args(argv)

    # Resolve vertex path — accepts name or file path
    if vertex_path is None:
        vname = getattr(known, "vertex", None)
        if vname is not None:
            # File path: direct .vertex file
            vpath = Path(vname)
            if vname.endswith(".vertex") or vpath.suffix == ".vertex":
                vertex_path = vpath.resolve()
            else:
                try:
                    vertex_path = _resolve_named_vertex(vname)
                except LoopsError as e:
                    rep.err(str(e))
                    return 1
        else:
            vertex_path = _resolve_vertex_path(None)
            if vertex_path is None:
                return 1

    if not vertex_path.exists():
        rep.err(f"Error: {vertex_path} does not exist")
        return 1

    try:
        vars = _parse_vars(known.var)
    except ValueError as e:
        rep.err(str(e))
        return 1

    from loops.commands.signing import tick_signer_for
    program = load_vertex_program(
        vertex_path, vars=vars or None, run_dispatcher=_execute_boundary_run,
        tick_signer=tick_signer_for(vertex_path),
    )

    # Aggregation vertex: no own sources but has combine children — sync each child
    if not program.sources:
        child_paths = _resolve_combine_vertex_paths(vertex_path)
        if child_paths:
            return _run_sync_aggregate(
                child_paths, vars=vars or None, force=known.force,
                parent_name=program.name, rest=rest, reporter=rep,
            )
        # Sourceless vertex with a store: still sync to evaluate boundaries.
        # Vertices like orchestration have no sources but boundaries with
        # run clauses that fire on externally-emitted facts.
        if not program.has_store:
            rep.err("No sources configured")
            return 1

    force = known.force

    def log_error(fact):
        payload = dict(fact.payload) if hasattr(fact.payload, "items") else fact.payload
        rep.err(f"[ERROR] {fact.observer}: {payload}")

    label = "force" if force else "cadence-gated"
    show(
        Block.text(
            f"Syncing {program.name}: {len(program.sources)} sources ({label})",
            current_palette().muted,
        ),
        file=sys.stderr,
    )

    def fetch():
        # Boundary run clauses dispatched inside program.sync().
        result = program.sync(on_error=log_error, force=force)

        return {
            "ran": result.ran,
            "skipped": [
                {"kind": s.kind, "last_run_ts": s.last_run_ts, "cadence_interval": s.cadence_interval}
                for s in result.skipped
            ],
            "fact_counts": result.fact_counts,
            "errors": [
                {
                    "kind": e.kind,
                    "observer": e.observer,
                    "payload": dict(e.payload) if hasattr(e.payload, "items") else e.payload,
                }
                for e in result.errors
            ],
            "ticks": [
                {
                    "name": tick.name,
                    "ts": tick.ts,
                    "payload": tick.payload,
                    "origin": getattr(tick, "origin", ""),
                    **({"run": tick.run} if tick.run else {}),
                }
                for tick in result.ticks
            ],
        }

    def render(ctx, data):
        from loops.lenses.sync import sync_view

        return sync_view(data, ctx.zoom, ctx.width)

    return run_cli(
        rest,
        fetch=fetch,
        render=render,
        prog="loops sync",
        description=f"Sync vertex {program.name}",
    )
