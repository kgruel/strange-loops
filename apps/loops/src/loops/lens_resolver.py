"""Lens resolver — find and load custom lens render functions.

Resolution order (4-tier):
1. --lens CLI flag (handled by caller, not here)
2. Vertex lens{} declaration (this module resolves the name)
3. App module override (handled by caller)
4. Built-in default (handled by caller)

File search for a lens name (e.g., "prompt"):
1. vertex-local: <vertex_dir>/lenses/<name>.py
2. project-local: <cwd>/lenses/<name>.py
3. user-global: ~/.config/loops/lenses/<name>.py
4. built-in: loops.lenses.<name> (this package)

Names starting with '.' or '/' are treated as paths relative to the vertex file.

Lens contract: module must export fold_view(data, zoom, width) -> Block
and/or stream_view(data, zoom, width) -> Block.
"""

from __future__ import annotations

import importlib
import importlib.util
import sys
from pathlib import Path
from typing import TYPE_CHECKING, Callable

if TYPE_CHECKING:
    from painted import Block, Zoom


# Type alias for lens render functions
LensRenderFn = Callable  # (data, zoom: Zoom, width: int | None) -> Block


def resolve_lens(
    name: str,
    view: str,
    *,
    vertex_dir: Path | None = None,
) -> LensRenderFn | None:
    """Resolve a lens name to a render function.

    Args:
        name: Lens name (e.g., "prompt") or path (e.g., "./custom.py")
        view: Which view to extract — "fold_view" or "stream_view"
        vertex_dir: Directory containing the vertex file (for relative resolution)

    Returns:
        The render function, or None if not found.
    """
    candidates = _view_candidates(name, view)

    # Path-style name: resolve relative to vertex
    if name.startswith((".", "/")):
        if vertex_dir is not None:
            target = (vertex_dir / name).resolve()
        else:
            target = Path(name).resolve()
        if target.is_file():
            return _load_from_file(target, candidates)
        return None

    # Name-style: search the path hierarchy
    search_dirs = _build_search_path(vertex_dir)
    for search_dir in search_dirs:
        candidate = search_dir / f"{name}.py"
        if candidate.is_file():
            fn = _load_from_file(candidate, candidates)
            if fn is not None:
                return fn

    # Fall back to built-in lenses in this package
    return _load_builtin(name, candidates)


def _build_search_path(vertex_dir: Path | None) -> list[Path]:
    """Build ordered search path for lens files."""
    dirs: list[Path] = []

    # 1. Vertex-local: <vertex_dir>/lenses/
    if vertex_dir is not None:
        dirs.append(vertex_dir / "lenses")

    # 2. Project-local: <cwd>/lenses/
    cwd_lenses = Path.cwd() / "lenses"
    if cwd_lenses not in dirs:
        dirs.append(cwd_lenses)

    # 3. User-global: ~/.config/loops/lenses/
    user_lenses = Path.home() / ".config" / "loops" / "lenses"
    dirs.append(user_lenses)

    return dirs


def _view_candidates(name: str, view: str) -> tuple[str, ...]:
    """Build ordered candidate function names to try in a lens module.

    Standard names first (fold_view, stream_view), then lens-specific
    variants (e.g., prompt_view, stream_prompt_view).
    """
    candidates = [view]

    # Lens-specific variants: <name>_view for fold, stream_<name>_view for stream
    if view == "fold_view":
        candidates.append(f"{name}_view")
    elif view in ("stream_view", "log_view"):
        candidates.append(f"stream_{name}_view")
        candidates.append(f"{name}_view")

    return tuple(dict.fromkeys(candidates))  # dedupe, preserve order


def _extract_view(mod, candidates: tuple[str, ...]) -> LensRenderFn | None:
    """Try to find a view function from a module, trying candidates in order."""
    for name in candidates:
        fn = getattr(mod, name, None)
        if fn is not None:
            return fn
    return None


def _load_from_file(path: Path, candidates: tuple[str, ...]) -> LensRenderFn | None:
    """Dynamically import a Python file and extract the view function."""
    module_name = f"_loops_lens_{path.stem}_{id(path)}"

    spec = importlib.util.spec_from_file_location(module_name, path)
    if spec is None or spec.loader is None:
        return None

    mod = importlib.util.module_from_spec(spec)
    sys.modules[module_name] = mod
    try:
        spec.loader.exec_module(mod)
    except Exception:
        del sys.modules[module_name]
        return None

    return _extract_view(mod, candidates)


def _load_builtin(name: str, candidates: tuple[str, ...]) -> LensRenderFn | None:
    """Try loading from the built-in lenses package."""
    try:
        mod = importlib.import_module(f"loops.lenses.{name}")
    except (ImportError, ModuleNotFoundError):
        return None
    return _extract_view(mod, candidates)
