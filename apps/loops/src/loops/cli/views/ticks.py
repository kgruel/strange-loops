"""cli.views.ticks — tick history and drill-down view.

Operation IR refactor paused — this surface remains an entry-point shim
delegating to the legacy ``loops.commands._run_ticks`` orchestrator.
Conversion to the full Operation IR shape (see ``cli/views/fold.py``)
is deferred until a touch-point justifies the work.
"""
from __future__ import annotations

from ..context import CliContext


def run(argv: list[str], ctx: CliContext) -> int:
    """Delegate to ``loops.main._run_ticks`` with ctx-shaped kwargs."""
    from loops.commands.ticks import _run_ticks

    return _run_ticks(argv, vertex_path=ctx.vertex_path, observer=ctx.observer)
