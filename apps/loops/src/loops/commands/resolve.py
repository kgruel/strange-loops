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
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING

from loops.errors import (
    LoopsError,
    VertexNotFound,
    VertexParseError,
    StoreNotFound,
)

if TYPE_CHECKING:
    from io import TextIO


@dataclass(frozen=True)
class EmitStatus:
    """Pure structural classification of an emit attempt — no side effects.

    Used by the emit receipt path to decide whether to print success / WARN /
    refuse. Mirrors the diagnostic surface of ``_warn_missing_fold_key`` but
    without printing, so the caller controls output.
    """
    kind_declared: bool          # is the kind registered in the vertex's loops?
    fold_key_field: str | None   # expected fold-key field name (e.g. "topic"), None if collect-style
    fold_key_present: bool       # did the payload supply the fold-key field?
    fold_key_value: str | None   # the value, when present


@dataclass(frozen=True)
class UnresolvedRef:
    """A payload value that looked like an entity ref but did not resolve."""
    field: str   # payload key (e.g. "ref" or any field carrying an address)
    addr: str    # the raw address string the user wrote (e.g. "decision/design/foo")


@dataclass(frozen=True)
class ResolvedRef:
    """A payload value that resolved to a stored entity's ULID.

    Surfaced so the emit receipt can report the inbound-edge delta — each
    resolved ref is one new inbound edge landing on its target entity.
    """
    field: str    # payload key carrying the address (e.g. "ref" or "superseded_by")
    addr: str     # the entity address the user wrote (e.g. "decision/design/foo")
    ref_id: str   # the resolved ULID


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


def classify_emit_status(
    vertex_path: Path,
    kind: str,
    payload: dict,
) -> EmitStatus:
    """Classify an emit attempt without side effects.

    Returns an ``EmitStatus`` describing whether the kind is declared,
    whether the kind folds by a key field, and whether the payload supplies
    that field. This is the pure-data substrate underneath the emit receipt
    path — the caller decides whether to print WARN, ERROR, or success.

    Vertex resolution failures (parse errors, combine misses) degrade to
    "kind not declared" — the receipt's WARN line will mention the missing
    declaration, matching observed behavior from today's live incident.
    """
    # cite is implicitly universal — every vertex accepts it regardless of whether
    # it explicitly declares a cite {} loop. Treat as declared with collect semantics
    # (no fold-key required).
    if kind == "cite":
        return EmitStatus(
            kind_declared=True,
            fold_key_field=None,
            fold_key_present=True,
            fold_key_value=None,
        )

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
        return EmitStatus(
            kind_declared=False,
            fold_key_field=None,
            fold_key_present=False,
            fold_key_value=None,
        )

    loop_def = ast.loops.get(kind)
    if loop_def is None:
        return EmitStatus(
            kind_declared=False,
            fold_key_field=None,
            fold_key_present=False,
            fold_key_value=None,
        )

    # Kind is declared — does it fold by a key field?
    for fold_decl in loop_def.folds:
        if isinstance(fold_decl.op, FoldBy):
            key = fold_decl.op.key_field
            present = key in payload
            return EmitStatus(
                kind_declared=True,
                fold_key_field=key,
                fold_key_present=present,
                fold_key_value=payload.get(key) if present else None,
            )

    # Kind is declared but folds by collect/count/etc. — no key required
    return EmitStatus(
        kind_declared=True,
        fold_key_field=None,
        fold_key_present=True,  # vacuously satisfied
        fold_key_value=None,
    )


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
    kind: str | None = None,
) -> tuple[dict[str, str], list[UnresolvedRef], list[ResolvedRef]]:
    """Resolve entity addresses in payload values to ULIDs.

    Scans payload values for entity addresses (kind/fold_key_value format).
    When a value matches a declared kind, looks up the most recent fact ULID
    for that entity — first in the local store, then across the full topology
    if the local store misses.

    The original field is preserved (navigable address). A sibling field
    {name}_ref is added with the pinned ULID (provenance anchor).

    The emitted kind's own fold-key field (when ``kind`` is supplied) is
    skipped by the scan: that value names THIS fact's slot in its own kind's
    fold and is self-identity, not a reference to another entity. Without
    this skip, slashed topic values like ``topic=pattern/foo`` would be
    misread as ``pattern/foo`` refs whenever any vertex in the topology
    happens to declare a ``pattern`` kind — producing false unresolved-ref
    warnings on every namespace-prefixed emit.

    Returns ``(augmented_payload, unresolved_refs, resolved_refs)``:
      * ``augmented_payload`` — payload plus any ``{field}_ref`` sibling fields
        whose addresses resolved to a ULID
      * ``unresolved_refs`` — refs where the value LOOKED like an address
        (addr_kind is a declared kind in this vertex or its topology) but no
        matching entity was found. Values whose addr_kind isn't declared
        anywhere are not surfaced — those weren't intended as refs.
      * ``resolved_refs`` — refs that DID resolve, one ``ResolvedRef`` per
        pinned ULID. The receipt path reads these to report the inbound-edge
        delta (each is one new inbound edge on its target entity).

    The receipt path uses ``unresolved_refs`` to emit WARN lines so users
    notice typos / stale refs at write-time, and ``resolved_refs`` for the
    inbound-delta lines.
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

    # The emitted kind's own fold-key field is self-identity, not a ref to
    # another entity — skip it during the scan so namespace-prefixed values
    # (topic=pattern/foo) don't get misread as kind/key addresses against
    # topology kinds that happen to share the prefix.
    self_key_field = local_kind_keys.get(kind) if kind else None

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

    def _resolve_one(addr: str) -> tuple[str | None, bool]:
        """Resolve a single ``kind/key`` address to a ULID.

        Returns ``(resolved_id_or_None, addr_kind_was_declared)``. The
        second bool tells the caller whether to surface this as an
        unresolved ref (declared kind but no match — likely a typo or
        stale ref) or silently skip (unknown kind — not an intended ref).
        """
        if "/" not in addr:
            return None, False
        addr_kind, addr_value = addr.split("/", 1)

        # Try local store first
        if addr_kind in local_kind_keys:
            key_field = local_kind_keys[addr_kind]
            rid = _try_resolve(store_path, addr_kind, key_field, addr_value)
            if rid is not None:
                return rid, True

        # Local miss or kind not declared locally — widen to topology
        topo_kind_keys, topo_stores = _ensure_topology()
        if addr_kind not in local_kind_keys and addr_kind not in topo_kind_keys:
            return None, False  # Not a known kind anywhere — not an intended ref

        key_field = topo_kind_keys.get(addr_kind) or local_kind_keys.get(addr_kind)
        if key_field is None:
            return None, False  # defensive — both maps lack addr_kind (shouldn't reach here)
        for sp in topo_stores:
            if sp.resolve() == store_path.resolve():
                continue  # Already searched
            rid = _try_resolve(sp, addr_kind, key_field, addr_value)
            if rid is not None:
                return rid, True

        return None, True  # declared kind, no match → caller surfaces as unresolved

    # Scan payload values for entity address pattern: kind/fold_key_value.
    # The ``ref`` field accumulates comma-separated addresses (parse-side
    # convention in ``_parse_emit_parts``); resolve each one independently
    # and concatenate the resolved IDs. All other fields are scanned as
    # single addresses — preserves single-ref-on-any-field semantics.
    refs: dict[str, str] = {}
    unresolved: list[UnresolvedRef] = []
    resolved: list[ResolvedRef] = []
    for field_name, value in payload.items():
        if not isinstance(value, str) or "/" not in value:
            continue
        if field_name == self_key_field:
            continue  # fold-key field — self-identity, not a ref
        addresses = (
            [a.strip() for a in value.split(",")]
            if field_name == "ref"
            else [value]
        )
        resolved_ids: list[str] = []
        for addr in addresses:
            if not addr or "/" not in addr:
                continue
            rid, declared = _resolve_one(addr)
            if rid is not None:
                resolved_ids.append(rid)
                resolved.append(ResolvedRef(field=field_name, addr=addr, ref_id=rid))
            elif declared:
                unresolved.append(UnresolvedRef(field=field_name, addr=addr))
        if resolved_ids:
            refs[f"{field_name}_ref"] = ",".join(resolved_ids)

    if refs:
        payload = {**payload, **refs}

    return payload, unresolved, resolved


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


def _display_path(path: Path) -> str:
    """Render a path for receipts — absolute, with $HOME contracted to ~.

    Mutating commands print the FULL path they wrote so the layer hit
    (local .loops/ vs global config) is always visible
    (thread:global-local-walk-broken: 'project.vertex' with no path
    masked a global write while the verbs read local).
    """
    resolved = path.resolve()
    try:
        return "~/" + str(resolved.relative_to(Path.home()))
    except ValueError:
        return str(resolved)


def _resolve_target_or_fail(target: str) -> Path | None:
    """Resolve a vertex target for declaration commands (add/rm/ls).

    Routes through ``_resolve_vertex_for_dispatch`` — the same local-first
    resolution the verbs (read/emit/cite) use — so declaration commands
    edit the file the verbs actually read. Before this, add/rm/ls resolved
    config-level only, silently editing the global template while the verbs
    operated on the local instance (thread:global-local-walk-broken).

    Prints an error and returns None when the target resolves nowhere.
    """
    path = _resolve_vertex_for_dispatch(target)
    if path is not None:
        return path
    from lang.population import resolve_vertex

    candidate = resolve_vertex(target, loops_home())
    _err(f"vertex not found: {candidate} (and no local {target}.vertex in .loops/ or cwd)")
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


# --- Helpers migrated from main.py ---


def _parse_vars(raw: list[str]) -> dict[str, str]:
    """Parse ['KEY=VALUE', ...] into {key: value}."""
    result: dict[str, str] = {}
    for item in raw:
        if "=" not in item:
            raise ValueError(f"Invalid --var format (expected KEY=VALUE): {item!r}")
        key, _, value = item.partition("=")
        result[key] = value
    return result


def _vertex_name(vertex_path: Path | None) -> str | None:
    """Extract vertex name from path — stem without extension."""
    if vertex_path is None:
        return None
    name = vertex_path.stem
    # .vertex (bare dotfile) → infer from parent dir
    if name == "":
        return vertex_path.parent.name
    return name


def _resolve_vertex_path(file_arg: str | None) -> Path | None:
    """Resolve a vertex file path, defaulting to LOOPS_HOME/.vertex."""
    if file_arg is not None:
        return Path(file_arg)
    home = loops_home()
    root = home / ".vertex"
    if root.exists():
        return root
    _err(f"Error: {root} not found. Run 'loops init' first.")
    return None


def _declared_kinds(vertex_path: Path) -> set[str]:
    """Return the set of kinds declared by a vertex (instance or aggregation).

    For an instance vertex, returns the kinds in its ``loops {}`` block.
    For an aggregation vertex that defines its own loops, those kinds.
    For an aggregation vertex with no loops block (pure combine), returns
    the union of source-vertex kinds — same union ``vertex_fold`` uses.

    Returns an empty set on parse/compile failure (validation is best-effort
    — callers should treat empty as "couldn't determine" rather than "vertex
    declares nothing").
    """
    try:
        from lang import parse_vertex_file
        from engine.compiler import compile_vertex
        from engine.vertex_reader import _collect_source_specs

        ast = parse_vertex_file(vertex_path)
        specs = compile_vertex(ast)
        if (ast.combine is not None or ast.discover is not None) and not specs:
            source_specs = _collect_source_specs(
                ast, vertex_path, override_kinds=frozenset(specs),
            )
            return set(source_specs.keys()) | set(specs.keys())
        return set(specs.keys())
    except Exception:
        return set()


def _validate_kind_or_exit(kind: str | None, vertex_path: Path | None) -> None:
    """If ``--kind X`` is set and X is not declared by the vertex, exit 2.

    Silent empty results hide the indistinguishability between:
    - typo in kind name (``--kind decsion``)
    - real kind that this vertex doesn't declare (``--kind decision`` on
      coupling-kernels, which only declares hypothesis/query-run/query-comparison)
    - valid kind with zero facts yet

    Strict validation surfaces the first two as actionable errors; the third
    keeps current "No data yet" behavior because the kind IS declared.

    Skips validation when ``kind`` is None (no filter requested) or the
    vertex's declared-kinds set is empty (couldn't determine — don't block).
    Path-style ``kind/key`` is split: only the kind half is validated.
    """
    if kind is None or vertex_path is None:
        return
    kind_only = kind.split("/", 1)[0]
    declared = _declared_kinds(vertex_path)
    if not declared:
        return
    if kind_only in declared:
        return

    import difflib
    suggestions = difflib.get_close_matches(
        kind_only, sorted(declared), n=3, cutoff=0.5,
    )
    lines = [
        f"Vertex '{vertex_path.stem}' does not declare kind '{kind_only}'.",
    ]
    if suggestions:
        lines.append(f"Did you mean: {', '.join(suggestions)}?")
    lines.append(f"Declared kinds: {', '.join(sorted(declared)) or '(none)'}")
    print("\n".join(lines), file=sys.stderr)
    sys.exit(2)
