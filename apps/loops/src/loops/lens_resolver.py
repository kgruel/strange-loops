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

Lenses MAY also export a module-level ``fetch(vertex_path, **kwargs)`` callable.
When present, the CLI uses it instead of the default command fetch — the lens
declares its complete input contract, not just rendering. Simple lenses omit
``fetch`` and consume the default shape (FoldState for fold_view). See
``resolve_lens_fetch``.

Optional context kwargs (vertex_name, etc.) are passed when available.
Lenses that want them add *, vertex_name=None to their signature.
Lenses that don't care ignore them — call_lens handles the fallback.
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

    # Path-style name: explicit path, no fallback to built-in
    if name.startswith((".", "/")):
        path = _find_lens_module_path(name, vertex_dir=vertex_dir)
        if path is None:
            return None
        mod = _load_lens_module(path)
        return _extract_view(mod, candidates) if mod is not None else None

    # Name-style: search the path hierarchy, then fall back to built-in
    path = _find_lens_module_path(name, vertex_dir=vertex_dir)
    if path is not None:
        mod = _load_lens_module(path)
        if mod is not None:
            fn = _extract_view(mod, candidates)
            if fn is not None:
                return fn

    # Fall back to built-in lenses in this package
    return _load_builtin(name, candidates)


def resolve_lens_fetch(
    name: str,
    *,
    vertex_dir: Path | None = None,
) -> Callable | None:
    """Resolve a lens name to its optional ``fetch`` callable.

    Companion to ``resolve_lens``. When a lens module exports a module-level
    ``fetch(vertex_path, **kwargs)`` function, the CLI uses it instead of the
    default command fetch. This lets a lens declare its complete input
    contract, enabling composition lenses (fold + ticks, fold + refs-graph)
    without new top-level commands.

    Returns None when the lens doesn't declare a fetch — the caller should
    fall back to its default fetch.

    Args:
        name: Lens name or path (same semantics as ``resolve_lens``)
        vertex_dir: Directory containing the vertex file (for relative resolution)

    Returns:
        The ``fetch`` callable, or None if not declared.
    """
    # Path-style: explicit path, no fallback to built-in
    if name.startswith((".", "/")):
        path = _find_lens_module_path(name, vertex_dir=vertex_dir)
        if path is None:
            return None
        mod = _load_lens_module(path)
        return getattr(mod, "fetch", None) if mod is not None else None

    # Name-style: search path hierarchy, then fall back to built-in
    path = _find_lens_module_path(name, vertex_dir=vertex_dir)
    if path is not None:
        mod = _load_lens_module(path)
        if mod is not None:
            fn = getattr(mod, "fetch", None)
            if fn is not None:
                return fn

    # Built-in fallback
    try:
        mod = importlib.import_module(f"loops.lenses.{name}")
    except (ImportError, ModuleNotFoundError):
        return None
    return getattr(mod, "fetch", None)


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
    elif view == "stream_view":
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


def _find_lens_module_path(name: str, *, vertex_dir: Path | None) -> Path | None:
    """Find the file path for a lens name. None if not resolvable to a file.

    Path-style names (starting with '.' or '/') resolve relative to
    ``vertex_dir``. Name-style searches the standard lens hierarchy.
    """
    if name.startswith((".", "/")):
        if vertex_dir is not None:
            target = (vertex_dir / name).resolve()
        else:
            target = Path(name).resolve()
        return target if target.is_file() else None

    for search_dir in _build_search_path(vertex_dir):
        candidate = search_dir / f"{name}.py"
        if candidate.is_file():
            return candidate
    return None


def _load_lens_module(path: Path):
    """Dynamically import a Python file. Returns the module, or None on failure."""
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

    return mod


def _load_builtin(name: str, candidates: tuple[str, ...]) -> LensRenderFn | None:
    """Try loading from the built-in lenses package."""
    try:
        mod = importlib.import_module(f"loops.lenses.{name}")
    except (ImportError, ModuleNotFoundError):
        return None
    return _extract_view(mod, candidates)


def call_lens(fn: LensRenderFn, data, zoom, width, **kwargs) -> "Block":
    """Call a lens render function, passing optional context kwargs if accepted.

    Existing lenses: fold_view(data, zoom, width) — kwargs silently dropped.
    New lenses: fold_view(data, zoom, width, *, vertex_name=None) — kwargs passed.
    """
    try:
        return fn(data, zoom, width, **kwargs)
    except TypeError:
        return fn(data, zoom, width)
