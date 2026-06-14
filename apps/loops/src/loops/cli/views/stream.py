"""cli.views.stream — event-stream view.

Operation IR refactor paused — this surface remains an entry-point shim
delegating to the legacy ``loops.commands._run_stream`` orchestrator.
Conversion to the full Operation IR shape (see ``cli/views/fold.py``)
is deferred until a touch-point justifies the work.

The shim still satisfies the (argv, ctx) -> int contract the registry
promises, so converting later is local to this module: no registry or
dispatch changes required.
"""
from __future__ import annotations

from ..invocation import Invocation


def run(argv: list[str], ctx: Invocation) -> int:
    """Delegate to ``loops.main._run_stream`` with ctx-shaped kwargs."""
    from loops.commands.stream import _run_stream

    return _run_stream(argv, vertex_path=ctx.vertex_path, observer=ctx.observer)
