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

import ast
import importlib
import importlib.util
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Callable

if TYPE_CHECKING:
    from painted import Block, Zoom


# Type alias for lens render functions
LensRenderFn = Callable  # (data, zoom: Zoom, width: int | None) -> Block


def zoom_from_fidelity(fidelity) -> "Zoom":
    """Adapt the renderer contract's open depth to a legacy lens Zoom.

    The renderer boundary keeps ``Fidelity`` whole.  Built-in and third-party
    lenses still use the pre-contract bounded ``Zoom`` vocabulary, so this is
    the one compatibility seam that owns its required two-sided clamp.

    ``Zoom`` is imported lazily so this module stays render-free to *import* —
    shell completion's lens enumeration (:func:`enumerate_lenses`) rides the
    no-renderer-on-TAB path, and a top-level ``from painted import Zoom`` would
    drag the renderer onto it.
    """
    from painted import Zoom

    if isinstance(fidelity, Zoom):
        return fidelity
    return Zoom(min(max(fidelity.depth, 0), 3))


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
        if mod is None:
            # The user's custom file exists but failed to IMPORT: falling
            # back to a same-named built-in would silently run a different
            # lens than the one selected (review round 4 #4). The load
            # failure was reported to stderr; refuse here.
            return None
        fn = _extract_view(mod, candidates)
        if fn is not None:
            return fn
        # Loaded fine but exposes no matching view: historical shadowing
        # behavior — fall through to the built-in.

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
        if mod is None:
            # Same no-fallback rule as resolve_lens (review rounds 4 #4,
            # 5 #2): a custom file that failed to IMPORT must not silently
            # become the same-named built-in's fetch.
            return None
        fn = getattr(mod, "fetch", None)
        if fn is not None:
            return fn
        # Loaded, no fetch attribute: historical shadowing fallback.

    # Built-in fallback
    try:
        mod = importlib.import_module(f"loops.lenses.{name}")
    except (ImportError, ModuleNotFoundError):
        return None
    return getattr(mod, "fetch", None)


def _labeled_search_path(vertex_dir: Path | None) -> list[tuple[str, Path]]:
    """Ordered lens-file search path, each dir tagged with its resolver tier.

    Single source of the custom-lens search order — both file resolution
    (:func:`_build_search_path`) and completion enumeration
    (:func:`enumerate_lenses`) read it, so they cannot drift on which
    directories are searched or in what precedence.
    """
    dirs: list[tuple[str, Path]] = []

    # 1. Vertex-local: <vertex_dir>/lenses/
    if vertex_dir is not None:
        dirs.append(("vertex", vertex_dir / "lenses"))

    # 2. Project-local: <cwd>/lenses/
    cwd_lenses = Path.cwd() / "lenses"
    if cwd_lenses not in [d for _, d in dirs]:
        dirs.append(("cwd", cwd_lenses))

    # 3. User-global: ~/.config/loops/lenses/
    user_lenses = Path.home() / ".config" / "loops" / "lenses"
    dirs.append(("user", user_lenses))

    return dirs


def _build_search_path(vertex_dir: Path | None) -> list[Path]:
    """Build ordered search path for lens files."""
    return [d for _, d in _labeled_search_path(vertex_dir)]


# --- Lens enumeration (completion) -----------------------------------------
#
# Shell completion needs the *set* of resolvable lens names, where resolution
# needs *one* name's render function. Both must agree on which directories are
# searched, in what precedence, and what makes a file a lens — so enumeration
# reuses ``_labeled_search_path`` (the search order) and the same view-function
# convention resolution keys off (``_view_candidates`` looks up ``*_view``
# functions). The difference is depth, not rules: resolution *executes* a module
# to extract its callable; enumeration only *inspects* it (``ast``), so it never
# runs a lens body and stays safe on the render-free TAB path.


@dataclass(frozen=True)
class LensInfo:
    """One resolvable lens: its name, a one-line description, and its tier.

    ``tier`` is the resolver tier the name resolves in ("vertex" / "cwd" /
    "user" / "builtin") — carried so callers (and tests) can see precedence
    shadowing, e.g. a vertex-local ``graph`` masking the built-in ``graph``.
    """

    name: str
    description: str
    tier: str


# The built-in lens package directory (loops/lenses/), a sibling of this module.
def _builtin_lens_dir() -> Path:
    return Path(__file__).parent / "lenses"


def _is_view_fn(fn_name: str, stem: str) -> bool:
    """True when ``fn_name`` is an entrypoint ``resolve_lens`` can actually load.

    Exactly the names ``_view_candidates`` tries for a lens named ``stem``
    (``fold_view``, ``stream_view``, ``<stem>_view``, ``stream_<stem>_view``)
    — not merely any public ``*_view``: a module exposing only an unrelated
    ``phantom_view`` enumerates-but-never-resolves, making ``--lens``
    completion invent a candidate (Sol review review/completion-t3 #5).
    """
    return fn_name in {
        "fold_view",
        "stream_view",
        f"{stem}_view",
        f"stream_{stem}_view",
    }


def _first_line(text: str, *, limit: int = 72) -> str:
    """First non-empty line of a docstring, whitespace-collapsed and truncated."""
    for raw in text.strip().splitlines():
        line = raw.strip()
        if line:
            return line if len(line) <= limit else line[: limit - 1].rstrip() + "…"
    return ""


def _lens_module_info(source: str, stem: str) -> tuple[str, str] | None:
    """Inspect a lens module's source. ``(name, description)`` or None.

    None when the source doesn't parse or exposes no resolvable entrypoint
    (not a lens). Known boundary (review round 2 #7 / round 3 #6): AST
    inspection cannot prove the module body IMPORTS successfully — a module
    whose body raises enumerates here but fails at resolve time. That is the
    render-free trade by design: completion projects the *declared* surface,
    and an import-broken lens is a runtime error the user hits — and READS —
    when they select it (``_load_lens_module`` reports the underlying
    exception to stderr), not a candidate silently hidden at TAB.

    Description is the module docstring's first line, falling back
    to the first view function's docstring; empty is fine. Pure ``ast`` — the
    module body never executes, so this is safe to call at TAB time.
    """
    try:
        tree = ast.parse(source)
    except SyntaxError:
        return None

    view_fns = [
        node
        for node in tree.body
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
        and _is_view_fn(node.name, stem)
    ]
    if not view_fns:
        return None

    doc = ast.get_docstring(tree) or ""
    if not doc:
        for fn in view_fns:
            fn_doc = ast.get_docstring(fn)
            if fn_doc:
                doc = fn_doc
                break

    return stem, _first_line(doc)


def _scan_lens_dir(directory: Path) -> list[tuple[str, str]]:
    """Every lens module in ``directory`` as ``(name, description)``.

    A missing directory yields ``[]`` (the common case for vertex/cwd/user
    tiers). Unreadable or non-lens files are skipped — enumeration under-lists,
    never raises. ``_``-prefixed files (``__init__``, private helpers) are
    skipped: they aren't ``--lens`` names.
    """
    out: list[tuple[str, str]] = []
    if not directory.is_dir():
        return out
    for path in sorted(directory.glob("*.py")):
        if path.name.startswith("_"):
            continue
        try:
            source = path.read_text(encoding="utf-8")
        except OSError:
            continue
        info = _lens_module_info(source, path.stem)
        if info is not None:
            out.append(info)
    return out


def enumerate_lenses(*, vertex_dir: Path | None = None) -> list[LensInfo]:
    """Every resolvable lens name + one-line description, in resolver precedence.

    Custom tiers first (vertex-local, cwd, user-global — the
    ``_labeled_search_path`` order), built-ins last; the first spelling of a
    name wins, so a custom lens shadows a built-in of the same name exactly as
    ``resolve_lens`` would resolve it. Inspection-only (no module body runs);
    a broken or missing tier is silently skipped. This is the enumeration side
    of resolution — completion offers precisely the names ``--lens`` accepts.
    """
    seen: set[str] = set()
    result: list[LensInfo] = []

    for tier, directory in _labeled_search_path(vertex_dir):
        for name, desc in _scan_lens_dir(directory):
            if name in seen:
                continue
            seen.add(name)
            result.append(LensInfo(name, desc, tier))

    for name, desc in _scan_lens_dir(_builtin_lens_dir()):
        if name in seen:
            continue
        seen.add(name)
        result.append(LensInfo(name, desc, "builtin"))

    return result


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
    """Dynamically import a Python file. Returns the module, or None on failure.

    A module-body failure is REPORTED to stderr before returning None: a lens
    file that raises at import is a user error the user must be able to read —
    swallowing it leaves ``--lens`` reporting a generic "not found" for a lens
    that visibly exists (and that completion legitimately offered, since
    enumeration projects the declared surface — Sol review review/completion-t3
    round 3 #6).
    """
    module_name = f"_loops_lens_{path.stem}_{id(path)}"

    spec = importlib.util.spec_from_file_location(module_name, path)
    if spec is None or spec.loader is None:
        return None

    mod = importlib.util.module_from_spec(spec)
    sys.modules[module_name] = mod
    try:
        spec.loader.exec_module(mod)
    except Exception as e:
        del sys.modules[module_name]
        # Once per path per process: resolve_lens runs for both the fetch
        # and the view of one command — the same broken file must not
        # report twice (review round 4 #4).
        if path not in _reported_broken:
            _reported_broken.add(path)
            print(
                f"lens {path.stem!r} failed to load ({path}): "
                f"{type(e).__name__}: {e}",
                file=sys.stderr,
            )
        return None

    return mod


# Broken lens files already reported to stderr this process (dedupe).
_reported_broken: set[Path] = set()


def _load_builtin(name: str, candidates: tuple[str, ...]) -> LensRenderFn | None:
    """Try loading from the built-in lenses package."""
    try:
        mod = importlib.import_module(f"loops.lenses.{name}")
    except (ImportError, ModuleNotFoundError):
        return None
    return _extract_view(mod, candidates)


def normalize_width(width: int | None) -> int | None:
    """Normalize the render width sentinel before it reaches a lens.

    Width carries a two-state contract: a concrete ``int`` (terminal columns
    on a TTY → truncate/pad to fit) or ``None`` (piped → no truncation, full
    payload flows to the consuming tool/system-prompt). This is the single
    chokepoint that documents that contract at the dispatch seam.

    Identity passthrough today — no normalization is applied. It exists as the
    named seam so any future piped-vs-TTY width policy lands in exactly one
    place instead of being re-derived at every ``call_lens`` site.
    """
    return width


def accepts_kwarg(fn, name: str) -> bool:
    """True when ``fn`` would RECEIVE the named kwarg under ``call_lens``/
    ``call_lens_fetch``'s own signature-based dispatch rule (``**kwargs``
    opts into everything; otherwise only a matching named param is passed).

    A predicate sibling of the dispatch itself — for a caller that needs to
    know in advance whether a kwarg will land, rather than passing it and
    seeing it silently dropped (0.8.0 capstone M6: dispatch uses this to
    decide whether a render-only custom lens needs the cursor mode-line
    injected on its behalf, since the lens's own render wouldn't otherwise
    receive — and so wouldn't render — the ``cursor`` kwarg at all).
    """
    import inspect

    params = inspect.signature(fn).parameters
    if any(p.kind is inspect.Parameter.VAR_KEYWORD for p in params.values()):
        return True
    return name in params


def call_lens(fn: LensRenderFn, data, fidelity, width, **kwargs) -> "Block":
    """Call a lens render function, passing optional context kwargs if accepted.

    Existing lenses: fold_view(data, zoom, width) — kwargs silently dropped.
    New lenses: fold_view(data, zoom, width, *, vertex_name=None) — kwargs passed.

    Dispatches by ``inspect.signature`` (symmetric to ``call_lens_fetch``)
    rather than try/except TypeError, so a genuine ``TypeError`` raised inside
    the lens body (bad indexing, missing attr) surfaces normally instead of
    being misread as a kwarg mismatch and silently retried with the body run
    a second time.

    - Lens declares ``**kwargs`` → receives every kwarg (opts into all).
    - Lens has named params → receives only the kwargs whose names match.
    - Lens has neither → receives just ``data, zoom, width``.
    """
    import inspect

    params = inspect.signature(fn).parameters
    zoom = zoom_from_fidelity(fidelity)

    has_var_keyword = any(
        p.kind == inspect.Parameter.VAR_KEYWORD
        for p in params.values()
    )
    if has_var_keyword:
        return fn(data, zoom, width, **kwargs)

    accepted = {k: v for k, v in kwargs.items() if k in params}
    return fn(data, zoom, width, **accepted)


def call_lens_fetch(fetch_fn, vertex_path, **all_kwargs):
    """Call a lens-declared fetch, passing only kwargs the function accepts.

    Symmetric to ``call_lens`` on the render side. Inspects the fetch function's
    signature to decide what to pass:

    - Lens has ``**kwargs`` in signature → passes everything (lens opts into all)
    - Lens has named params → passes only those that match
    - Lens has neither → passes just ``vertex_path``

    Uses ``inspect.signature`` rather than try/except so a TypeError raised inside
    the lens body (bad indexing, missing import) surfaces normally instead of
    being misread as a kwarg mismatch.
    """
    import inspect

    sig = inspect.signature(fetch_fn)
    params = sig.parameters

    has_var_keyword = any(
        p.kind == inspect.Parameter.VAR_KEYWORD
        for p in params.values()
    )
    if has_var_keyword:
        return fetch_fn(vertex_path, **all_kwargs)

    accepted = {k: v for k, v in all_kwargs.items() if k in params}
    return fetch_fn(vertex_path, **accepted)
