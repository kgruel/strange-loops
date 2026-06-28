"""Lens resolution — CLI-layer utilities for selecting and loading view functions."""
from __future__ import annotations

import sys
from pathlib import Path


def _get_vertex_lens_decl(vertex_path: Path):
    """Extract LensDecl from a vertex file, if present."""
    try:
        from lang import parse_vertex_file
        vf = parse_vertex_file(vertex_path)
        return vf.lens
    except Exception:
        return None


def _exit_lens_not_found(
    name: str,
    view_name: str,
    vertex_dir: Path | None,
    *,
    source: str,
) -> None:
    """Print a helpful error and ``sys.exit(2)`` for an unresolvable lens request.

    Lists the file-search tiers tried so the user can drop the lens in the
    right place or fix the typo. The view_name appears in the message because
    a lens module CAN exist but lack the requested view (e.g. fold_view
    present, stream_view missing) — same surface error, distinct cause, and
    the user inspects the named module to tell them apart.
    """
    from ..lens_resolver import _build_search_path

    lines = [
        f"Lens '{name}' (requested via {source}) not found, "
        f"or found but missing {view_name}().",
        "Searched:",
    ]
    for d in _build_search_path(vertex_dir):
        lines.append(f"  {d}/{name}.py")
    lines.append(f"  built-in: loops.lenses.{name}")
    print("\n".join(lines), file=sys.stderr)
    sys.exit(2)


def _effective_lens_name(
    lens_flag: str | None,
    vertex_path: Path | None,
    view_name: str,
) -> str | None:
    """Return the effective lens name for a command — flag or vertex decl.

    Used by fetch resolution so a lens-declared ``fetch`` overrides the
    default command fetch, regardless of whether the lens was requested
    via --lens or via the vertex's lens{} block.
    """
    if lens_flag is not None:
        return lens_flag
    if vertex_path is None:
        return None
    vertex_lens = _get_vertex_lens_decl(vertex_path)
    if vertex_lens is None:
        return None
    if view_name == "fold_view" and vertex_lens.fold:
        return vertex_lens.fold
    if view_name == "stream_view" and vertex_lens.stream:
        return vertex_lens.stream
    return None


def _resolve_render_fn(
    lens_flag: str | None,
    vertex_path: Path | None,
    view_name: str,
):
    """Resolve render function via 3-tier chain.

    Resolution order:
    1. --lens CLI flag (resolved via lens_resolver)
    2. Vertex lens{} declaration (resolved via lens_resolver)
    3. Built-in default

    Explicit lens requests fail loudly. When ``--lens NAME`` or a vertex
    ``lens { fold "NAME" }`` declaration cannot be resolved in any tier
    (vertex-local, cwd, user-global, built-in), this prints a helpful error
    listing the search path and calls ``sys.exit(2)``. Silent fallback to a
    different view would hide measurement misalignment — same failure shape
    as alcove's recency-counter-vs-emitted-kind bug. The user explicitly
    asked for a lens by name; they get either that lens or a clear failure.

    Implicit fallbacks (no ``lens_flag``, no vertex decl) still return the
    built-in default — that path is the normal "no lens requested" case.
    """
    from ..lens_resolver import resolve_lens

    vertex_dir = vertex_path.parent if vertex_path is not None else None

    # Tier 1: --lens flag — explicit request, fail loudly if unresolvable
    if lens_flag is not None:
        fn = resolve_lens(lens_flag, view_name, vertex_dir=vertex_dir)
        if fn is not None:
            return fn
        _exit_lens_not_found(lens_flag, view_name, vertex_dir, source="--lens flag")

    # Tier 2: vertex lens{} declaration — explicit decl, fail loudly if unresolvable
    if vertex_path is not None:
        vertex_lens = _get_vertex_lens_decl(vertex_path)
        if vertex_lens is not None:
            if view_name == "fold_view" and vertex_lens.fold:
                fn = resolve_lens(vertex_lens.fold, view_name, vertex_dir=vertex_dir)
                if fn is not None:
                    return fn
                _exit_lens_not_found(
                    vertex_lens.fold, view_name, vertex_dir,
                    source=f"vertex lens decl in {vertex_path.name}",
                )
            elif view_name == "stream_view" and vertex_lens.stream:
                fn = resolve_lens(vertex_lens.stream, view_name, vertex_dir=vertex_dir)
                if fn is not None:
                    return fn
                _exit_lens_not_found(
                    vertex_lens.stream, view_name, vertex_dir,
                    source=f"vertex lens decl in {vertex_path.name}",
                )

    # Tier 3: built-in defaults
    if view_name == "fold_view":
        from ..lenses.fold import fold_view
        return fold_view
    elif view_name == "stream_view":
        from ..lenses.stream import stream_view
        return stream_view
    elif view_name == "ticks_view":
        from ..lenses.ticks import ticks_view
        return ticks_view

    from ..lenses.fold import fold_view
    return fold_view


def _resolve_lens_fetch(
    lens_flag: str | None,
    vertex_path: Path | None,
    view_name: str,
):
    """Return a lens-declared fetch callable, or None to fall through to default.

    A lens module may export ``fetch(vertex_path, **kwargs)`` alongside its
    view function. When present, the lens owns its input contract — useful
    for composition lenses (fold + ticks, etc.).
    """
    name = _effective_lens_name(lens_flag, vertex_path, view_name)
    if name is None:
        return None
    from ..lens_resolver import resolve_lens_fetch
    vertex_dir = vertex_path.parent if vertex_path is not None else None
    return resolve_lens_fetch(name, vertex_dir=vertex_dir)
