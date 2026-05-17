"""cli.app — top-level entry point for the loops CLI.

Owns the three-tier dispatch logic that used to live in
``loops.main.main`` + ``_dispatch_verb_first`` + ``_dispatch_observer`` +
``_dispatch_command``. Routing only — the actual ``_run_*`` work still
happens in ``loops.main`` (or the migrating ``cli/views/*``) and is looked
up through ``cli.registry``.

Dispatch tiers:

  1. Verbs (``loops <verb> [vertex] …``) — ``registry.VERBS``
  2. Commands (``loops <command> …``) — ``registry.COMMANDS``
  3. Vertex shorthand (``loops <vertex> …``) — implicit read or a
     vertex-first op from ``registry.VERTEX_OPS``

The fast-path ``_try_fast_read`` short-circuit and the ``argparse``
lazy-import optimisation remain in ``loops.main`` for step 2 — they
move (or retire) in step 6. ``loops.main.main`` becomes a thin
delegator to ``cli.app.main`` once those pieces have been disentangled
from the in-module global tricks.

Design anchor: decision/design/cli-refactor-option-2-siftd-shape.
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

from .context import CliContext
from .output import default_reporter
from .registry import COMMANDS, POPULATION_OPS, VERBS


def _peel_observer(rest: list[str]) -> tuple[str | None, list[str]]:
    """Strip ``--observer X`` from rest and return (resolved_observer, rest').

    Mirrors the pre-parse the legacy ``_dispatch_verb_first`` and
    ``_dispatch_observer`` performed inline — keeps observer resolution
    out of individual view parsers. Resolution itself defers to
    ``commands.resolve._resolve_observer_flag`` to preserve the env →
    .vertex chain.
    """
    parser = argparse.ArgumentParser(add_help=False)
    parser.add_argument("--observer", default=None)
    known, rest_after = parser.parse_known_args(rest)
    from loops.commands.resolve import _resolve_observer_flag

    return _resolve_observer_flag(known.observer), rest_after


def _vertex_first(
    vertex_name: str, vertex_path: Path, rest: list[str]
) -> int:
    """Dispatch ``loops <vertex> [op] [args]`` — vertex resolved upfront.

    Replicates legacy ``_dispatch_observer``: default (no subcommand) is
    an implicit read; named ops route through ``VERBS`` or the
    population helpers; population ops reconstruct the qualified-vertex
    argv shape the legacy commands expect.
    """
    observer, rest = _peel_observer(rest)
    ctx = CliContext(
        reporter=default_reporter(),
        vertex_path=vertex_path,
        vertex_name=vertex_name,
        observer=observer,
    )

    # Default: no subcommand or flags only → implicit read (fold).
    if not rest or rest[0].startswith("-"):
        return VERBS["read"](rest, ctx)

    op = rest[0]
    args = rest[1:]

    if op in VERBS:
        return VERBS[op](args, ctx)

    # Population ops embed the (possibly qualified) vertex name into argv.
    # `loops <vertex> ls [qualifier] [flags]` → `loops ls vertex/qualifier flags`.
    if op == "ls":
        qualifier = None
        flags: list[str] = []
        for arg in args:
            if qualifier is None and not arg.startswith("-"):
                qualifier = arg
            else:
                flags.append(arg)
        target = f"{vertex_name}/{qualifier}" if qualifier else vertex_name
        return POPULATION_OPS["ls"]([target, *flags], ctx)

    if op in POPULATION_OPS:
        return POPULATION_OPS[op]([vertex_name, *args], ctx)

    ctx.reporter.err(f"Unknown operation: {op}")
    return 1


def _verb_first(verb: str, rest: list[str]) -> int:
    """Dispatch ``loops <verb> [vertex] [args]`` — verb known, vertex inside argv.

    Observer is peeled from ``rest`` here; vertex resolution stays inside
    each view (the legacy ``_run_*`` functions resolve it from the first
    positional / local-vertex fallback themselves).
    """
    observer, rest = _peel_observer(rest)
    ctx = CliContext(
        reporter=default_reporter(),
        vertex_path=None,
        observer=observer,
    )
    return VERBS[verb](rest, ctx)


def _command(cmd: str, argv: list[str]) -> int:
    """Dispatch a top-level dev/setup command via ``registry.COMMANDS``.

    The legacy ``_dispatch_command`` wrapped commands in painted's
    ``run_app`` for help rendering. We bypass that here — individual
    commands carry their own help via their internal argparse parsers.
    For unknown commands we surface the same painted-rendered help
    surface as the root help via ``loops.main._render_main_help``.
    """
    ctx = CliContext(reporter=default_reporter())
    if cmd not in COMMANDS:
        ctx.reporter.err(f"Unknown command: {cmd}")
        return 1
    return COMMANDS[cmd](argv, ctx)


def main(argv: list[str] | None = None) -> int:
    """Top-level CLI entry point.

    Behaviour is identical to the legacy ``loops.main.main`` — verb-first,
    then command, then vertex-first dispatch. The fast-path
    ``_try_fast_read`` short-circuit and the ``argparse`` lazy injection
    still live in ``loops.main.main``; this function is invoked *after*
    those are dealt with.
    """
    if argv is None:
        argv = sys.argv[1:]

    # No args / top-level help — defer to the legacy help renderer; it
    # owns the painted HelpData composition that step 6 will retire.
    if not argv or argv[0] in ("-h", "--help"):
        from loops.main import _render_main_help

        return _render_main_help(argv)

    # Tier 1: known verbs
    if argv[0] in VERBS:
        return _verb_first(argv[0], argv[1:])

    # Tier 2: dev / setup commands
    if argv[0] in COMMANDS:
        return _command(argv[0], argv[1:])

    # Tier 3: try as vertex name → vertex-first dispatch
    vertex_name = argv[0]
    from loops.commands.resolve import _resolve_vertex_for_dispatch

    vertex_path = _resolve_vertex_for_dispatch(vertex_name)
    if vertex_path is not None:
        return _vertex_first(vertex_name, vertex_path, argv[1:])

    # Path-like arg with no resolved vertex → hint the right invocation.
    if (
        vertex_name.endswith(".vertex")
        or vertex_name.startswith("./")
        or vertex_name.startswith("/")
    ):
        default_reporter().err(
            f"File arguments go with a command: loops sync {vertex_name}"
        )
        return 1

    default_reporter().err(f"Unknown command: {vertex_name}")
    return 1


__all__ = ["main"]
