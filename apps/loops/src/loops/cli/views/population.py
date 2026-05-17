"""cli.views.population — template population ops (ls / add / rm / export).

Step 5 entry-point shims for the population verbs reached either as
top-level commands (``loops add``) or via vertex-first dispatch
(``loops <vertex> add``). The vertex-first router in ``cli.app``
embeds the vertex name into argv before calling these.

These four ops don't have rendering complexity worth the full
Operation IR refactor — they parse argv, mutate state, print a
receipt. The shims keep them on the (argv, ctx) -> int shape so
they can swap to a full IR migration later without touching the
registry.
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
