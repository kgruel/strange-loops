"""Operation — normalized intent IR for CLI invocations.

Mirrors siftd's ``Operation`` pattern (siftd/api/dispatch.py): a single
immutable dataclass that captures *what should happen* without committing
to *how it should be rendered*. Each view (cli/views/*.py) parses argv into
an Operation; ``cli.dispatch.dispatch(op, reporter=…)`` executes it.

The discriminator is ``render_lens``:
  - ``None`` → action shape: fn() runs, result (if any) goes to reporter.show
  - ``"fold" | "stream" | "ticks" | …`` → display shape: fn() returns data,
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
    # painted.Fidelity / Format carried by reference only. TYPE_CHECKING keeps
    # cli/operation.py free of runtime painted imports — the single-
    # boundary discipline applies to RUNTIME imports.
    from painted import Fidelity
    from painted.cli import Format


Mode = Literal["static", "live", "interactive"]


@dataclass(frozen=True)
class SurfaceSpec:
    """Declarative read-grammar transform spec — assembled by the fold view
    from flags, applied by dispatch AFTER ``project()`` (and before either
    encoder), so plain and ``--json`` carry the same transformed rows.

    Carried on a dedicated Operation field rather than ``render_context`` so the
    transform parameters never leak into the lens's kwargs. Each field maps to
    one flag; dispatch applies them in a fixed canonical order
    (filter → select → budget → count). ``queried_key``/``full`` flow into
    ``project()`` itself (granularity); the rest are Surface→Surface transforms.
    """

    queried_key: str | None = None   # --key (single) → project() granularity
    full: bool = False               # --full → project(full=True)
    key_or: tuple[str, ...] = ()     # comma-OR --key (len>1) → filter(key_or=)
    # field=value predicates (eq + comma-OR), as (field, allowed-values) pairs
    where: tuple[tuple[str, tuple[str, ...]], ...] = ()
    observer: str | None = None      # observer= bareword row filter
    fields: tuple[str, ...] | None = None  # --fields → select()
    limit: int | None = None         # --limit → budget(limit=)
    last: int | None = None          # --last → budget(last=)
    count_by: str | None = None      # --count --by FIELD → count(by=)
    do_count: bool = False           # --count → count()


@dataclass(frozen=True)
class Operation:
    """Normalized intent for a CLI invocation.

    Fields:
        verb: short verb name — "read" / "emit" / "sync" / "close" / "cite" / …
        fn: the callable that does the work (commands.fetch.fetch_fold,
            commands.emit.cmd_emit, …). ``fn(**params)`` is called by
            ``dispatch``.
        params: kwargs for fn.
        render_lens: name of the BASE lens to render fn's return value
            through ("fold", "stream", "ticks", …). Determines the
            function name dispatch looks up inside the lens module
            (``fold_view`` / ``stream_view`` / …). ``None`` means action
            shape (no rendering — fn does its own side-effects and
            returns either ``None``, an exit code, or a string/Block to
            ``reporter.show``).
        lens_override: optional user-supplied lens module name (the
            ``--lens NAME`` flag). When set, dispatch resolves
            ``NAME.<render_lens>_view`` through the lens search chain
            (vertex-local → project → user → built-in). ``render_lens``
            stays the canonical view-function name regardless of the
            override.
        fidelity: painted.Fidelity for display ops; may be ``None`` for
            actions.
        format: painted.Format (JSON / PLAIN / ANSI / AUTO) parsed from
            ``--json`` / ``--plain``. dispatch forks on JSON to encode the
            Surface via ``to_dict`` instead of the text lens. ``None`` when
            the view doesn't carry a format (legacy shims).
        render_context: extra kwargs forwarded to the lens (e.g. lens-specific
            render hints). Kept distinct from ``surface_spec`` so transform
            parameters never leak into the lens's kwargs.
        surface_spec: the read-grammar transform spec (``SurfaceSpec``) applied
            by dispatch over the projected Surface — filter/select/budget/count
            + granularity (queried_key/full). ``None`` for non-Surface ops.
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
    lens_override: str | None = None
    fidelity: Fidelity | None = None
    format: "Format | None" = None
    surface_spec: "SurfaceSpec | None" = None
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
