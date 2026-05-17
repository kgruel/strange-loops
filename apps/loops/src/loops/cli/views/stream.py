"""cli.views.stream — event-stream view.

Step 5 lands the entry-point shape (``run(argv, ctx) -> int``) and
threads the resolved CliContext into the legacy ``_run_stream``
orchestrator. The argparse → Operation → dispatch full refactor is
deferred — stream is a smaller surface than fold and the legacy
``run_cli`` path keeps the goldens stable while step 7 reviews fold.
The interim shape still satisfies the boundary discipline: no painted
import lives in this module, and the dispatcher only sees the
CliContext-shaped entry point.
"""
from __future__ import annotations

from ..context import CliContext


def run(argv: list[str], ctx: CliContext) -> int:
    """Delegate to ``loops.main._run_stream`` with ctx-shaped kwargs."""
    from loops.main import _run_stream

    return _run_stream(argv, vertex_path=ctx.vertex_path, observer=ctx.observer)
