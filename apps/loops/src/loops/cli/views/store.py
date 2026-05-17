"""cli.views.store — store-inspection view.

Operation IR refactor paused — this surface remains an entry-point shim
delegating to the legacy ``loops.commands._run_store`` orchestrator.
Conversion to the full Operation IR shape (see ``cli/views/fold.py``)
is deferred until a touch-point justifies the work.
"""
from __future__ import annotations

from ..context import CliContext


def run(argv: list[str], ctx: CliContext) -> int:
    """Delegate to ``loops.main._run_store`` with ctx-shaped kwargs.

    ``_run_store`` doesn't accept observer (store is observer-agnostic),
    so we only thread vertex_path.
    """
    from loops.commands.store import _run_store

    return _run_store(argv, vertex_path=ctx.vertex_path)
