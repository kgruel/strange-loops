"""Operation — normalized intent IR for CLI invocations.

Mirrors siftd's ``Operation`` pattern (siftd/api/dispatch.py): a single
immutable dataclass that captures *what should happen* without committing
to *how it should be rendered*. Each view (cli/views/*.py) parses argv into
an Operation; ``cli.dispatch.dispatch(op, reporter=…)`` executes it.

The discriminator is ``render_lens``:
  - ``None`` → action shape: fn() runs, result (if any) goes to reporter.show
  - ``"fold" | "stream" | "trace" | …`` → display shape: fn() returns data,
    lens renders it, reporter prints the block

This decouples input context (CLI / HTTP / programmatic) from execution
and from output context (terminal / JSON / HTML). Same Operation, different
parse paths, different reporters.

Design anchor: decision/operation-ir-adoption (2026-03-24);
decision/design/cli-refactor-option-2-siftd-shape (2026-05-17).
"""
from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING, Any, Literal

if TYPE_CHECKING:
    # painted.Fidelity carried by reference only. TYPE_CHECKING keeps
    # cli/operation.py free of runtime painted imports — the single-
    # boundary discipline applies to RUNTIME imports.
    from painted import Fidelity


Mode = Literal["static", "live", "interactive"]


@dataclass(frozen=True)
class Operation:
    """Normalized intent for a CLI invocation.

    Fields:
        verb: short verb name — "read" / "emit" / "sync" / "close" / "cite" / …
        fn: the callable that does the work (commands.fetch.fetch_fold,
            commands.emit.cmd_emit, …). ``fn(**params)`` is called by
            ``dispatch``.
        params: kwargs for fn.
        render_lens: name of the lens to render fn's return value through.
            ``None`` means action shape (no rendering — fn does its own
            side-effects and returns either ``None`` or a string/Block to
            ``reporter.show``).
        fidelity: painted.Fidelity for display ops; may be ``None`` for
            actions.
        render_context: extra kwargs forwarded to the lens (e.g. ``diff=True``
            for cumulative-delta rendering).
        vertex_path: resolved vertex path; carried alongside params for
            convenience (many ``fn``s need it as their first positional).
        observer: who is invoking — for receipt attribution and store
            scoping.
        mode: output mode — static (one-shot), live (InPlaceRenderer
            stream), interactive (TUI handoff).
        stream_fn: async generator producing successive data snapshots for
            live mode. None for static.
        interactive_handler: callable that takes over for INTERACTIVE mode
            (e.g. autoresearch TUI). Returns the exit code.
    """

    verb: str
    fn: Callable[..., Any]
    params: dict[str, Any] = field(default_factory=dict)
    render_lens: str | None = None
    fidelity: Fidelity | None = None
    render_context: dict[str, Any] = field(default_factory=dict)
    vertex_path: Path | None = None
    observer: str | None = None
    mode: Mode = "static"
    stream_fn: Callable[..., Any] | None = None
    interactive_handler: Callable[[], int] | None = None

    @property
    def is_action(self) -> bool:
        """True if this is an action (no rendering); False for display ops."""
        return self.render_lens is None
