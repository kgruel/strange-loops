"""Vertex path resolution — pure utilities (path → path).

Resolves vertex names, store paths, topology, entity references, and
observer scope. No rendering, no argparse — only lang, engine, and
filesystem reads.

Raises ``LoopsError`` subclasses for all domain failures. Callers at
the CLI boundary catch ``LoopsError`` for uniform error presentation.
"""
from __future__ import annotations

import os
import sys
from pathlib import Path
from typing import TYPE_CHECKING

from loops.errors import (
    LoopsError,
    VertexNotFound,
    VertexParseError,
    StoreNotFound,
    StoreAccessError,
)

if TYPE_CHECKING:
    from io import TextIO


def loops_home() -> Path:
    """Resolve the loops config directory."""
    if env := os.environ.get("LOOPS_HOME"):
        return Path(env)
    xdg = os.environ.get("XDG_CONFIG_HOME", str(Path.home() / ".config"))
    return Path(xdg) / "loops"


def _find_local_vertex() -> Path | None:
    """Find a .vertex file in .loops/ or cwd. Returns first match or None."""
    # Prefer .loops/.vertex (workspace root convention)
    loops_dir = Path.cwd() / ".loops"
    dotvertex = loops_dir / ".vertex"
    if dotvertex.exists():
        return dotvertex
    # Fall back to .loops/*.vertex (named vertex)
    if loops_dir.is_dir():
        matches = sorted(loops_dir.glob("*.vertex"))
        if matches:
            return matches[0]
    # Fall back to cwd (existing projects)
    matches = sorted(Path.cwd().glob("*.vertex"))
    return matches[0] if matches else None


# --- Internal helpers ---


def _parse_vertex(vertex_path: Path):
    """Parse a vertex file, translating raw exceptions to domain errors.

    Raises:
        VertexNotFound: file doesn't exist or can't be read
        VertexParseError: file exists but has invalid syntax
    """
    from lang import parse_vertex_file

    try:
        return parse_vertex_file(vertex_path)
    except FileNotFoundError:
        raise VertexNotFound(vertex_path) from None
    except OSError as e:
        raise VertexNotFound(vertex_path, context=str(e)) from e
    except Exception as e:
        raise VertexParseError(vertex_path, e) from e


def _err(msg: str, file: TextIO | None = None) -> None:
    """Show an error message through painted."""
    from painted import show, Block
    from painted.palette import current_palette

    show(Block.text(msg, current_palette().error), file=file or sys.stderr)


# --- Warning / best-effort functions (catch LoopsError, never raise) ---


def _warn_missing_fold_key(
    vertex_path: Path,
    kind: str,
    payload: dict,
) -> None:
    """Warn on stderr if the payload lacks the fold key field.

    When a kind folds 'by' a key field (e.g. thread folds by 'name'),
    a fact without that field will be stored but silently skipped by the
    fold — orphaned data that never appears in the folded state.
    """
    from lang.ast import FoldBy

    # Follow combine chain to the vertex with actual loop declarations
    try:
        writable = _resolve_writable_vertex(vertex_path)
    except LoopsError:
        writable = None
    if writable is not None:
        vertex_path = writable

    try:
        ast = _parse_vertex(vertex_path)
    except LoopsError:
        return

    loop_def = ast.loops.get(kind)
    if loop_def is None:
        return

    for fold_decl in loop_def.folds:
        if isinstance(fold_decl.op, FoldBy) and fold_decl.op.key_field not in payload:
            key = fold_decl.op.key_field
            _err(
                f"Warning: kind '{kind}' folds by '{key}' but payload has no "
                f"'{key}=' field — fact will be stored but not foldable"
            )
            return


def _extract_kind_keys(vertex_path: Path) -> dict[str, str]:
    """Extract kind → fold key_field map from a vertex's AST.

    Returns {kind_name: key_field} for each kind that folds "by" a key field.
    Skips kinds that use collect or other non-keyed folds.
    Best-effort: returns empty dict on any vertex error.
    """
    from lang.ast import FoldBy

    try:
        ast = _parse_vertex(vertex_path)
    except LoopsError:
        return {}

    kind_keys: dict[str, str] = {}
    for kind_name, loop_def in ast.loops.items():
        for fold_decl in loop_def.folds:
            if isinstance(fold_decl.op, FoldBy):
                kind_keys[kind_name] = fold_decl.op.key_field
                break
    return kind_keys


# --- Topology ---


def _try_topology_from_store(
    store_path: Path,
) -> tuple[dict[str, str], list[Path]] | None:
    """Try reading _topology fold from a store. Returns None on miss.

    Validates that all cached store paths exist on disk. If any are
    stale (deleted vertex), returns None to trigger fallback+refresh.
    """
    from engine import StoreReader

    try:
        with StoreReader(store_path) as reader:
            facts = reader.facts_by_kind("_topology")
    except Exception:
        return None

    if not facts:
        return None

    # Replay upsert fold manually: latest per name wins
    topology: dict[str, dict] = {}
    for fact in facts:
        payload = fact["payload"]
        name = payload.get("name")
        if name:
            topology[name] = payload

    # Validate store paths exist and collect results
    merged_kind_keys: dict[str, str] = {}
    store_paths: list[Path] = []

    for entry in topology.values():
        store_str = entry.get("store", "")
        if store_str:
            sp = Path(store_str)
            if sp.exists():
                store_paths.append(sp)
            else:
                return None  # Stale — trigger fallback

        kind_keys = entry.get("kind_keys", {})
        merged_kind_keys.update(kind_keys)

    return merged_kind_keys, store_paths


def _topology_kind_keys_and_stores(
    root_vertex_path: Path,
) -> tuple[dict[str, str], list[Path]]:
    """Collect kind_keys and store paths from a root vertex's topology.

    Cache-first: tries reading _topology fold from the root's own store.
    On miss (no store, no _topology facts, or stale store paths), falls
    back to filesystem walk and refreshes the cache.
    Best-effort: returns empty results on vertex errors.
    """
    try:
        ast = _parse_vertex(root_vertex_path)
    except LoopsError:
        return {}, []

    # Fast path: try _topology facts from root's own store
    if ast.store is not None:
        own_store = ast.store
        if not own_store.is_absolute():
            own_store = (root_vertex_path.parent / own_store).resolve()
        if own_store.exists():
            result = _try_topology_from_store(own_store)
            if result is not None:
                return result

    # Slow path: filesystem walk
    from engine.vertex_reader import _resolve_stores

    store_paths = _resolve_stores(ast, root_vertex_path)

    merged_kind_keys: dict[str, str] = {}
    base_dir = root_vertex_path.parent

    if ast.discover is not None:
        for match in sorted(base_dir.glob(ast.discover)):
            if match.suffix != ".vertex" or match.resolve() == root_vertex_path.resolve():
                continue
            merged_kind_keys.update(_extract_kind_keys(match))
    elif ast.combine is not None:
        from lang.population import resolve_vertex

        home = loops_home()
        for entry in ast.combine:
            vpath = resolve_vertex(entry.name, home)
            if not vpath.is_absolute():
                vpath = (base_dir / vpath).resolve()
            if vpath.exists():
                merged_kind_keys.update(_extract_kind_keys(vpath))

    # Refresh cache for next time
    from engine.vertex_reader import emit_topology

    try:
        emit_topology(root_vertex_path)
    except Exception:
        pass  # Cache refresh is best-effort

    return merged_kind_keys, store_paths


# --- Entity reference resolution ---


def _resolve_entity_refs(
    vertex_path: Path,
    store_path: Path,
    payload: dict[str, str],
) -> dict[str, str]:
    """Resolve entity addresses in payload values to ULIDs.

    Scans payload values for entity addresses (kind/fold_key_value format).
    When a value matches a declared kind, looks up the most recent fact ULID
    for that entity — first in the local store, then across the full topology
    if the local store misses.

    The original field is preserved (navigable address). A sibling field
    {name}_ref is added with the pinned ULID (provenance anchor).

    Returns the payload with any resolved references added.
    """
    from engine import StoreReader

    # Build kind → key_field map from local vertex declaration
    try:
        writable = _resolve_writable_vertex(vertex_path)
    except LoopsError:
        writable = None
    if writable is not None:
        vertex_path = writable

    local_kind_keys = _extract_kind_keys(vertex_path)

    # Lazy topology widening — only computed on first local miss
    _topo: dict | None = None

    def _ensure_topology() -> tuple[dict[str, str], list[Path]]:
        nonlocal _topo
        if _topo is not None:
            return _topo["kind_keys"], _topo["stores"]
        root = _find_local_vertex()
        if root is None or root.resolve() == vertex_path.resolve():
            _topo = {"kind_keys": {}, "stores": []}
            return _topo["kind_keys"], _topo["stores"]
        topo_kind_keys, topo_stores = _topology_kind_keys_and_stores(root)
        _topo = {"kind_keys": topo_kind_keys, "stores": topo_stores}
        return topo_kind_keys, topo_stores

    def _try_resolve(sp: Path, kind: str, key_field: str, value: str) -> str | None:
        try:
            reader = StoreReader(sp)
            try:
                return reader.resolve_entity_id(kind, key_field, value)
            finally:
                reader.close()
        except Exception:
            return None

    # Scan payload values for entity address pattern: kind/fold_key_value
    refs: dict[str, str] = {}
    for field_name, value in payload.items():
        if not isinstance(value, str) or "/" not in value:
            continue
        # Split on first / only: decision/design/format-dissolves → ("decision", "design/format-dissolves")
        addr_kind, addr_value = value.split("/", 1)

        # Try local store first
        if addr_kind in local_kind_keys:
            key_field = local_kind_keys[addr_kind]
            ulid = _try_resolve(store_path, addr_kind, key_field, addr_value)
            if ulid is not None:
                refs[f"{field_name}_ref"] = ulid
                continue

        # Local miss or kind not declared locally — widen to topology
        topo_kind_keys, topo_stores = _ensure_topology()
        if addr_kind not in local_kind_keys and addr_kind not in topo_kind_keys:
            continue  # Not a known kind anywhere in the topology

        key_field = topo_kind_keys.get(addr_kind) or local_kind_keys.get(addr_kind)
        if key_field is None:
            continue

        for sp in topo_stores:
            if sp.resolve() == store_path.resolve():
                continue  # Already searched
            ulid = _try_resolve(sp, addr_kind, key_field, addr_value)
            if ulid is not None:
                refs[f"{field_name}_ref"] = ulid
                break

    if refs:
        payload = {**payload, **refs}

    return payload


# --- Vertex resolution (raise on failure) ---


def _resolve_writable_vertex(vertex_path: Path) -> Path | None:
    """Resolve to the vertex that owns the writable store.

    For vertices with a store, returns the path as-is.
    For combine vertices, follows the chain to find the first constituent
    with a store.  Returns None if no writable vertex is found.

    Raises:
        VertexNotFound: vertex_path doesn't exist
        VertexParseError: vertex_path has invalid syntax
    """
    from lang.population import resolve_vertex

    ast = _parse_vertex(vertex_path)

    if ast.store is not None:
        return vertex_path

    # Follow combine → first entry's vertex
    if ast.combine:
        ref_path = resolve_vertex(ast.combine[0].name, loops_home())
        if not ref_path.is_absolute():
            ref_path = (vertex_path.parent / ref_path).resolve()
        if ref_path.exists():
            return _resolve_writable_vertex(ref_path)

    return None


def _resolve_vertex_store_path(vertex_path: Path) -> Path | None:
    """Resolve store path from a vertex file. Returns None if no store configured.

    For combinatorial vertices (combine block, no store), follows the first
    combine entry to find the writable store.

    Raises:
        VertexNotFound: vertex_path doesn't exist
        VertexParseError: vertex_path has invalid syntax
    """
    from lang.population import resolve_vertex

    ast = _parse_vertex(vertex_path)

    if ast.store is not None:
        store_path = Path(ast.store)
        if not store_path.is_absolute():
            store_path = (vertex_path.parent / store_path).resolve()
        return store_path

    # Follow combine → first entry's store
    if ast.combine:
        ref_path = resolve_vertex(ast.combine[0].name, loops_home())
        if not ref_path.is_absolute():
            ref_path = (vertex_path.parent / ref_path).resolve()
        if ref_path.exists():
            return _resolve_vertex_store_path(ref_path)

    return None


def _resolve_named_store(name: str) -> Path:
    """Resolve a vertex name to its store path via resolve_vertex + store extraction.

    Raises:
        VertexNotFound: vertex name doesn't resolve to an existing file
        StoreNotFound: vertex exists but has no store configured
    """
    from lang.population import resolve_vertex

    vertex_path = resolve_vertex(name, loops_home()).resolve()
    if not vertex_path.exists():
        raise VertexNotFound(vertex_path, context=f"from name '{name}'")
    store_path = _resolve_vertex_store_path(vertex_path)
    if store_path is None:
        raise StoreNotFound(name)
    return store_path


def _resolve_named_vertex(name: str) -> Path:
    """Resolve a vertex name to its .vertex file path.

    Raises:
        VertexNotFound: vertex name doesn't resolve to an existing file
    """
    from lang.population import resolve_vertex

    vertex_path = resolve_vertex(name, loops_home()).resolve()
    if not vertex_path.exists():
        raise VertexNotFound(vertex_path, context=f"from name '{name}'")
    return vertex_path


def _resolve_combine_child(parent_vertex: Path, alias: str) -> Path | None:
    """Resolve a combine child by alias.

    Given a combine vertex and an alias string, find the child entry
    with a matching alias and return its resolved vertex path.
    Returns None if the parent isn't a combine vertex or no alias matches.
    """
    from lang.population import resolve_vertex

    try:
        ast = _parse_vertex(parent_vertex)
    except LoopsError:
        return None

    if ast.combine is None:
        return None

    for entry in ast.combine:
        if entry.alias == alias:
            ref = resolve_vertex(entry.name, loops_home())
            if not ref.is_absolute():
                ref = (parent_vertex.parent / ref).resolve()
            if ref.exists():
                return ref.resolve()
    return None


def _resolve_vertex_for_dispatch(name: str) -> Path | None:
    """Try to resolve a name as a vertex for CLI dispatch. Returns None to fall through.

    Resolution chain (local instance wins over config template):
    1. Path-like strings (.vertex suffix, ./ or / prefix) — resolve directly if file exists
    2. Local: .loops/name.vertex
    3. Local: cwd/name.vertex
    4. Config-level: LOOPS_HOME/name/name.vertex
    5. Combine alias: parent/alias → parent's combine child with that alias
    """
    if name.endswith(".vertex") or name.startswith("./") or name.startswith("/"):
        p = Path(name)
        if p.exists():
            return p.resolve()
        return None

    # Local .loops/
    local = Path.cwd() / ".loops" / f"{name}.vertex"
    if local.exists():
        return local.resolve()

    # Local cwd
    local = Path.cwd() / f"{name}.vertex"
    if local.exists():
        return local.resolve()

    # Config-level resolution
    from lang.population import resolve_vertex

    candidate = resolve_vertex(name, loops_home())
    if candidate.exists():
        return candidate.resolve()

    # Combine alias: project/loops → resolve "project" then find child "loops"
    # Combine vertices live at config level, so we try both local and
    # config-level resolution for the parent.
    if "/" in name:
        parent_name, child_alias = name.split("/", 1)

        # Try local resolution first (might be a local combine vertex)
        parent = _resolve_vertex_for_dispatch(parent_name)
        if parent is not None:
            child = _resolve_combine_child(parent, child_alias)
            if child is not None:
                return child

        # Try config-level explicitly (combine vertices typically live here)
        config_parent = resolve_vertex(parent_name, loops_home())
        if config_parent.exists() and (parent is None or config_parent.resolve() != parent):
            child = _resolve_combine_child(config_parent.resolve(), child_alias)
            if child is not None:
                return child

    return None


# --- Observer resolution ---


def _resolve_observer_flag(raw: str | None) -> str | None:
    """Resolve --observer flag, handling the special 'all' value.

    Returns:
        None — no flag given, defer to vertex scope declaration
        ""   — explicit 'all', always unscoped
        str  — explicit observer name, always scoped
    """
    if raw is None:
        return None  # no flag — vertex decides
    if raw.lower() == "all":
        return ""  # unscoped — will pass None to engine
    from .identity import resolve_observer
    return resolve_observer(raw)


def _apply_vertex_scope(observer: str | None, vertex_path: Path | None) -> str | None:
    """Resolve observer default from vertex scope declaration.

    When observer is None (no flag given), checks the vertex's
    observer_scoped flag. Scoped vertices default to current observer.
    Unscoped vertices default to all.
    """
    if observer is not None:
        return observer  # explicit flag — use as-is

    # No flag: check vertex scope
    if vertex_path is not None:
        # Fast check: scan file text for scope declaration before full parse.
        # Full KDL parse costs ~1.5ms; text scan is ~0.1ms. Only parse if
        # the scope keyword is present (rare — most vertices are unscoped).
        try:
            text = vertex_path.read_text()
        except OSError:
            return None
        if 'scope "observer"' not in text:
            return None  # unscoped — show all
        # Keyword found — confirm with full parse (handles comments, etc.)
        try:
            ast = _parse_vertex(vertex_path)
        except LoopsError:
            return None
        if ast.observer_scoped:
            from .identity import resolve_observer
            return resolve_observer(None)

    # Unscoped vertex or no vertex resolved yet — show all
    return None
