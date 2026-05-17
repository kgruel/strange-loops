"""cli.views.store — store-inspection view.

Step 5 entry-point shim. Same shape as the other display views — the
heavy argparse → Operation → dispatch refactor is deferred; see
cli/views/stream.py for the rationale.
"""
from __future__ import annotations

from ..context import CliContext


def run(argv: list[str], ctx: CliContext) -> int:
    """Delegate to ``loops.main._run_store`` with ctx-shaped kwargs.

    ``_run_store`` doesn't accept observer (store is observer-agnostic),
    so we only thread vertex_path.
    """
    from loops.main import _run_store

    return _run_store(argv, vertex_path=ctx.vertex_path)
