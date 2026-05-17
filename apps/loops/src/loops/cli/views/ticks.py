"""cli.views.ticks — tick history and drill-down view.

Step 5 entry-point shim. The argparse → Operation → dispatch full
refactor is deferred; see cli/views/stream.py for the rationale.
"""
from __future__ import annotations

from ..context import CliContext


def run(argv: list[str], ctx: CliContext) -> int:
    """Delegate to ``loops.main._run_ticks`` with ctx-shaped kwargs."""
    from loops.main import _run_ticks

    return _run_ticks(argv, vertex_path=ctx.vertex_path, observer=ctx.observer)
