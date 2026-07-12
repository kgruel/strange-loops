"""cli.views.store — store-inspection view.

Operation IR refactor paused — this surface remains an entry-point shim
delegating to the legacy ``loops.commands._run_store`` orchestrator.
Conversion to the full Operation IR shape (see ``cli/views/fold.py``)
is deferred until a touch-point justifies the work.
"""
from __future__ import annotations

from ..invocation import Invocation


def run(argv: list[str], ctx: Invocation) -> int:
    """Delegate to ``loops.main._run_store`` with ctx-shaped kwargs.

    ``_run_store`` doesn't accept observer (store is observer-agnostic),
    so we only thread vertex_path.

    Operator-facing refusals along the store path — no store configured,
    ``reanchor`` requires a ``.vertex`` target, a missing signing key
    ("refusing partial re-anchor"), an absent ``.db`` — are raised as
    ``ValueError`` / ``FileNotFoundError`` carrying actionable messages.
    Render them as clean one-line errors here at the CLI boundary instead
    of letting them escape as raw tracebacks (which read as a crash, and
    made ``reanchor``'s no-key refusal look like a contradicting verdict).
    Other exception types still propagate as tracebacks — they signal a
    genuine bug, not an operator error. The systemic error-handling /
    exception-hierarchy convention is under review; see thread
    ``error-handling-and-exception-hierarchy``.
    """
    from loops.commands.store import _run_store

    try:
        # ``store absorb`` records a signed genesis under a recording observer;
        # the global ``--observer`` peel lands it on ``ctx.observer`` (the store
        # view is otherwise observer-agnostic), so thread it through for that
        # one subcommand. ``_run_store`` ignores it for every other verb.
        return _run_store(argv, vertex_path=ctx.vertex_path, observer=ctx.observer)
    except (ValueError, FileNotFoundError) as exc:
        ctx.reporter.err(str(exc))
        return 1
