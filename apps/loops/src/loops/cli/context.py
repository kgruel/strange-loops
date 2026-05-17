"""CliContext — per-invocation context object threaded through views.

Carries the resolved vertex (``vertex_path`` + ``vertex_name``), the
resolved observer, the Reporter, terminal-mode hints, and the LOOPS_HOME
root. Constructed once in ``cli.app.main`` and passed to whichever view
runs.

Mirrors siftd's per-invocation context pattern. The dataclass is mutable
on construction (fields are computed late) but should be treated as
immutable from a view's perspective.

Design anchor: decision/design/cli-refactor-option-2-siftd-shape.
"""
from __future__ import annotations

import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .output import Reporter


def _default_reporter() -> "Reporter":
    """Lazy import to avoid pulling painted at module-import time."""
    from .output import PaintedReporter
    return PaintedReporter()


def _default_isatty() -> bool:
    return hasattr(sys.stdout, "isatty") and sys.stdout.isatty()


@dataclass
class CliContext:
    """Per-invocation CLI context.

    Fields:
        reporter: output sink — production PaintedReporter or test
            BufferReporter. Always set; defaults to a fresh PaintedReporter.
        vertex_path: resolved vertex file path; ``None`` when no vertex
            was supplied (root help, dev commands, etc.).
        vertex_name: short name as the user wrote it ("project",
            "comms/native"). ``None`` when no vertex was supplied.
        observer: resolved observer identity for the call. ``None``
            preserves the legacy "let the command resolve it" semantics.
        loops_home: resolved LOOPS_HOME root for the call. ``None`` defers
            to ``loops.commands.resolve.loops_home()`` at use time.
        isatty: whether stdout is a TTY at the time of construction —
            used by views to decide static vs live default.
    """

    reporter: "Reporter" = field(default_factory=_default_reporter)
    vertex_path: Path | None = None
    vertex_name: str | None = None
    observer: str | None = None
    loops_home: Path | None = None
    isatty: bool = field(default_factory=_default_isatty)
