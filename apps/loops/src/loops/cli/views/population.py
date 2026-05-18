"""cli.views.population — vertex add/ls/rm/export ops.

Operation IR refactor paused — these surfaces remain entry-point shims
delegating to ``loops.commands._run_*`` orchestrators (which import
painted directly for receipt rendering). Conversion to the full
Operation IR shape (see ``cli/views/fold.py``) is deferred until a
touch-point justifies the work.

As of Phase 2 (plan:vertex-living-document), ``run_add`` routes through
``loops.commands.add`` which dispatches on the first non-target arg:
``kind`` / ``observer`` / ``combine`` mutate the .vertex file directly via
the kdl_splice library; ``row`` (and bare-positional back-compat) delegates
to the legacy template-population path. ``run_ls``/``run_rm``/``run_export``
still target template populations only — they will move to the same
subcommand-dispatch shape in Phase 3.

The shims are reachable via two paths:
  * top-level commands (``loops add``) — through ``registry.COMMANDS``;
  * vertex-first dispatch (``loops <vertex> add``) — through
    ``registry.POPULATION_OPS``; the vertex-first router in ``cli.app``
    embeds the vertex name into argv before calling these.

Both paths land on the same ``(argv, ctx) -> int`` contract, so a future
IR conversion can be local to this module.
"""
from __future__ import annotations

from ..context import CliContext


def run_ls(argv: list[str], _ctx: CliContext) -> int:
    """List entries in a template population. Vertex-first form only."""
    from loops.commands.population import _run_ls

    return _run_ls(argv)


def run_ls_root(argv: list[str], _ctx: CliContext) -> int:
    """List all discovered vertices — top-level ``loops ls``."""
    from loops.commands.population import _run_ls_root

    return _run_ls_root(argv)


def run_add(argv: list[str], _ctx: CliContext) -> int:
    """Add an entry to a template population."""
    from loops.commands.population import _run_add

    return _run_add(argv)


def run_rm(argv: list[str], _ctx: CliContext) -> int:
    """Remove an entry from a template population."""
    from loops.commands.population import _run_rm

    return _run_rm(argv)


def run_export(argv: list[str], _ctx: CliContext) -> int:
    """Materialise a template population to a ``.list`` file."""
    from loops.commands.population import _run_export

    return _run_export(argv)
