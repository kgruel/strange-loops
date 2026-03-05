"""Observer identity — who you are, workspace root, emit validation."""

from __future__ import annotations

import os
from pathlib import Path


def _loops_home() -> Path:
    """Resolve the loops config directory (delegates to main.loops_home)."""
    from loops.main import loops_home

    return loops_home()


def find_workspace_root(start: Path | None = None) -> Path | None:
    """Find .vertex workspace root walking up from start (default: cwd).

    1. .loops/.vertex in start or ancestor dirs
    2. ~/.config/loops/.vertex (global)
    Returns None if not found.
    """
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
    # Legacy fallback
    legacy = home / "root.vertex"
    if legacy.exists():
        return legacy
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
    for filename in (".vertex", "root.vertex"):
        global_path = home / filename
        if global_path.exists():
            observers = _read_observers(global_path)
            if len(observers) == 1:
                return observers[0].name
            break

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


def validate_emit(vertex_path: Path, observer: str, kind: str) -> str | None:
    """Validate observer + kind against vertex declaration chain.

    Returns error message if rejected, None if allowed.
    Checks:
    1. Observer is declared in the vertex itself, .vertex chain, or
       combine/discover source vertices (cascade)
    2. Kind is in observer's grant.potential (if grant is declared)
    """
    if not observer:
        return None  # No observer to validate

    # Check the vertex file itself first
    vertex_observers = _read_observers(vertex_path)

    # Collect observers from project-level .vertex
    project_observers: tuple = ()
    project_root = vertex_path.parent
    for d in [project_root, *project_root.parents]:
        candidate = d / ".loops" / ".vertex"
        if candidate.exists() and candidate.resolve() != vertex_path.resolve():
            project_observers = _read_observers(candidate)
            break

    # Collect observers from global .vertex
    home = _loops_home()
    global_observers: tuple = ()
    for filename in (".vertex", "root.vertex"):
        global_path = home / filename
        if global_path.exists() and global_path.resolve() != vertex_path.resolve():
            global_observers = _read_observers(global_path)
            break

    # Collect observers from combine/discover source vertices (cascade)
    combine_observers = _collect_combine_observers(vertex_path)

    all_observers = (
        list(vertex_observers)
        + list(project_observers)
        + list(global_observers)
        + combine_observers
    )

    # No observers declared anywhere -> no validation (open system)
    if not all_observers:
        return None

    # Find the observer declaration
    decl = None
    for obs in all_observers:
        if obs.name == observer:
            decl = obs
            break

    if decl is None:
        names = sorted({o.name for o in all_observers})
        return f"Observer {observer!r} not declared. Known: {', '.join(names)}"

    # Check grant.potential if declared
    if decl.grant is not None and kind not in decl.grant.potential:
        allowed = sorted(decl.grant.potential)
        return f"Observer {observer!r} cannot emit kind {kind!r}. Allowed: {', '.join(allowed)}"

    return None


def resolve_local_vertex(start: Path | None = None) -> Path:
    """Find a vertex file via workspace root walk-up or session fallback.

    Resolution order:
    1. Local vertex in cwd (*.vertex)
    2. LOOPS_HOME/session/session.vertex

    Raises FileNotFoundError if neither found.
    """
    from loops.main import _find_local_vertex

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
