"""Observer identity — who you are, workspace root, emit validation."""

from __future__ import annotations

import os
from dataclasses import dataclass
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from pathlib import Path


@dataclass(frozen=True)
class ObserverCheck:
    """Pure classification of an observer+kind emit against the vertex chain.

    No printing, no exit code — the caller decides how to act on each status:

    * ``"ok"``         — emit permitted (observer declared & granted, or the
      vertex declares no observers / no observer was supplied — an open system).
    * ``"undeclared"`` — observers ARE declared somewhere in the chain but this
      observer is not among them. FORGIVABLE: the default emit path WARNs and
      stores (the Row carries the observer regardless); strict refuses.
    * ``"forbidden"``  — the observer IS declared but its ``grant.potential``
      excludes this kind. ALWAYS a hard refusal — a declared capability
      boundary, not a missing declaration.
    """

    status: str               # "ok" | "undeclared" | "forbidden"
    message: str | None        # human-facing reason (None when "ok")
    known: tuple[str, ...]     # declared observer names (for hints / snippets)


def _loops_home() -> Path:
    """Resolve the loops config directory."""
    from loops.commands.resolve import loops_home

    return loops_home()


def find_workspace_root(start: Path | None = None) -> Path | None:
    """Find .vertex workspace root walking up from start (default: cwd).

    1. .loops/.vertex in start or ancestor dirs
    2. ~/.config/loops/.vertex (global)
    Returns None if not found.
    """
    from pathlib import Path
    current = (start or Path.cwd()).resolve()
    # Walk up from start
    for d in [current, *current.parents]:
        candidate = d / ".loops" / ".vertex"
        if candidate.exists():
            return candidate
    # Global fallback
    home = _loops_home()
    global_root = home / ".vertex"
    if global_root.exists():
        return global_root
    return None


def _read_observers(vertex_path: Path) -> tuple:
    """Parse a .vertex file and return its observers tuple (or empty)."""
    from lang import parse_vertex_file

    try:
        ast = parse_vertex_file(vertex_path)
        return ast.observers or ()
    except Exception:
        return ()


def resolve_observer(explicit: str | None = None, start: Path | None = None) -> str:
    """Resolve observer identity.

    Priority chain:
    1. explicit (from --observer flag)
    2. LOOPS_OBSERVER env var
    3. Project .vertex observers block (walking up from start)
    4. Global .vertex observers block
    Returns "" if nothing resolves.
    """
    # 1. Explicit flag
    if explicit is not None:
        return explicit

    # 2. Env var
    env = os.environ.get("LOOPS_OBSERVER")
    if env is not None:
        return env

    # 3. Project-level .vertex (walk up)
    from pathlib import Path
    current = (start or Path.cwd()).resolve()
    for d in [current, *current.parents]:
        candidate = d / ".loops" / ".vertex"
        if candidate.exists():
            observers = _read_observers(candidate)
            if len(observers) == 1:
                return observers[0].name
            if observers:
                # Multiple observers declared, can't auto-pick
                return ""
            break  # found .vertex but no observers — fall through to global

    # 4. Global .vertex
    home = _loops_home()
    global_path = home / ".vertex"
    if global_path.exists():
        observers = _read_observers(global_path)
        if len(observers) == 1:
            return observers[0].name

    return ""


def _collect_combine_observers(vertex_path: Path) -> list:
    """Collect observer declarations from combine/discover source vertices.

    For aggregation vertices, follows the combine chain to source vertices
    and collects their observer declarations. Same pattern as combine
    auto-inherit for fold specs — the aggregation vertex accepts the
    same observers as its sources.
    """
    from lang import parse_vertex_file, resolve_vertex

    try:
        ast = parse_vertex_file(vertex_path)
    except Exception:
        return []

    observers: list = []
    home = _loops_home()

    if ast.combine is not None:
        for entry in ast.combine:
            vpath = resolve_vertex(entry.name, home)
            if not vpath.is_absolute():
                vpath = (vertex_path.parent / vpath).resolve()
            if vpath.exists():
                observers.extend(_read_observers(vpath))
                # Also check the source vertex's workspace root
                for d in [vpath.parent, *vpath.parent.parents]:
                    candidate = d / ".loops" / ".vertex"
                    if candidate.exists() and candidate.resolve() != vpath.resolve():
                        observers.extend(_read_observers(candidate))
                        break

    elif ast.discover is not None:
        base_dir = vertex_path.parent
        for match in sorted(base_dir.glob(ast.discover)):
            if match.suffix != ".vertex" or match.resolve() == vertex_path.resolve():
                continue
            observers.extend(_read_observers(match))

    return observers


def _collect_all_observers(vertex_path: Path) -> list:
    """Collect every observer declared in the vertex's resolution chain.

    Cascade order: the vertex file itself, the nearest project-level
    ``.loops/.vertex``, the global ``.vertex``, then combine/discover source
    vertices. Returns the flat list (with duplicates — callers dedup names).
    """
    vertex_observers = _read_observers(vertex_path)

    project_observers: tuple = ()
    project_root = vertex_path.parent
    for d in [project_root, *project_root.parents]:
        candidate = d / ".loops" / ".vertex"
        if candidate.exists() and candidate.resolve() != vertex_path.resolve():
            project_observers = _read_observers(candidate)
            break

    home = _loops_home()
    global_observers: tuple = ()
    global_path = home / ".vertex"
    if global_path.exists() and global_path.resolve() != vertex_path.resolve():
        global_observers = _read_observers(global_path)

    combine_observers = _collect_combine_observers(vertex_path)

    return (
        list(vertex_observers)
        + list(project_observers)
        + list(global_observers)
        + combine_observers
    )


def check_emit(vertex_path: Path, observer: str, kind: str) -> ObserverCheck:
    """Classify an observer+kind emit against the vertex declaration chain.

    Pure — no printing, no exit. The caller maps ``ObserverCheck.status`` to an
    action: ``"ok"`` proceeds, ``"undeclared"`` is forgivable (WARN+store in the
    default emit path; refuse under strict), ``"forbidden"`` is a hard refusal.

    Checks, in order:
    1. Observer is declared in the vertex itself, the .vertex chain, or
       combine/discover source vertices (cascade).
    2. Kind is in the observer's ``grant.potential`` (if a grant is declared).
    """
    if not observer:
        return ObserverCheck("ok", None, ())

    all_observers = _collect_all_observers(vertex_path)

    # No observers declared anywhere -> open system, nothing to validate.
    if not all_observers:
        return ObserverCheck("ok", None, ())

    known = tuple(sorted({o.name for o in all_observers}))

    # Find the observer declaration (supports namespaced observers).
    from engine.observer import observer_matches

    decl = None
    for obs in all_observers:
        if observer_matches(obs.name, observer):
            decl = obs
            break

    if decl is None:
        return ObserverCheck(
            "undeclared",
            f"Observer {observer!r} not declared. Known: {', '.join(known)}",
            known,
        )

    # Declared but capability-gated: a grant that excludes this kind is a hard
    # boundary, not a missing declaration — never forgiven.
    if decl.grant is not None and kind not in decl.grant.potential:
        allowed = sorted(decl.grant.potential)
        return ObserverCheck(
            "forbidden",
            f"Observer {observer!r} cannot emit kind {kind!r}. "
            f"Allowed: {', '.join(allowed)}",
            known,
        )

    return ObserverCheck("ok", None, known)


def validate_emit(vertex_path: Path, observer: str, kind: str) -> str | None:
    """Validate observer + kind against the vertex declaration chain.

    Thin wrapper over :func:`check_emit` that REFUSES on both ``undeclared`` and
    ``forbidden`` — the legacy refuse-on-any-failure contract. ``_run_close`` and
    direct callers keep this strict behavior; only ``cmd_emit``'s main path
    rewires to :func:`check_emit` to forgive undeclared observers (S6).

    Returns the error message if rejected, None if allowed.
    """
    check = check_emit(vertex_path, observer, kind)
    if check.status == "ok":
        return None
    return check.message


def resolve_local_vertex(start: Path | None = None) -> Path:
    """Find a vertex file via workspace root walk-up or session fallback.

    Resolution order:
    1. Local vertex in cwd (*.vertex)
    2. LOOPS_HOME/session/session.vertex

    Raises FileNotFoundError if neither found.
    """
    from loops.commands.resolve import _find_local_vertex

    # 1. Local vertex in cwd
    local = _find_local_vertex()
    if local is not None:
        return local

    # 2. LOOPS_HOME session fallback
    session_vertex = _loops_home() / "session" / "session.vertex"
    if session_vertex.exists():
        return session_vertex

    raise FileNotFoundError(
        "No vertex found. Run 'loops init --template session' or 'loops emit <kind> ...' first."
    )
