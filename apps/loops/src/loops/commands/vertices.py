"""Vertex discovery — fetch vertex metadata from workspace root (.vertex)."""

from __future__ import annotations

from pathlib import Path
from typing import Any


def _classify_kind(ast: Any) -> str:
    """Classify a vertex as instance, aggregation, or hybrid."""
    has_store = ast.store is not None
    has_agg = ast.discover is not None or ast.combine is not None
    if has_store and has_agg:
        return "hybrid"
    if has_agg:
        return "aggregation"
    return "instance"


def _describe_fold(fold_decl: Any) -> str:
    """One-line description of a fold declaration."""
    op = fold_decl.op
    cls = type(op).__name__
    if cls == "FoldBy":
        return f"items by {op.key_field}"
    if cls == "FoldCollect":
        return f"collect {op.max_items}"
    if cls == "FoldWindow":
        return f"window {op.max_items}"
    if cls == "FoldCount":
        return "count"
    if cls == "FoldSum":
        return "sum"
    if cls == "FoldLatest":
        return "latest"
    if cls == "FoldMax":
        return "max"
    if cls == "FoldMin":
        return "min"
    if cls == "FoldAvg":
        return "avg"
    return cls.lower().removeprefix("fold")


def _store_stats(store_path: Path) -> dict[str, Any] | None:
    """Cheap stat read over an instance store — the `ls -l` columns.

    Returns ``{facts, kind_count, mtime, kind_stats}`` where ``mtime`` is the
    newest *fact* timestamp (epoch float; decision:design/ls-stat-decisions-a-d
    A — resumption wants the last emit, not the last seal) and ``kind_stats``
    is a count-descending ``[{kind, count, latest}]`` lifted straight from
    ``StoreReader.fact_kind_stats()`` (per-kind MAX(ts) is already computed
    there — decision C, zero net-new query). Returns ``None`` when the store
    file does not yet exist (freshly declared vertex).
    """
    if not store_path.exists():
        return None
    from engine.store_reader import StoreReader

    with StoreReader(store_path) as reader:
        summary = reader.summary()
        freshness = reader.freshness
    kind_rows = summary["facts"]["kinds"]
    kind_stats = sorted(
        (
            {"kind": k, "count": v["count"], "latest": v["latest"].timestamp()}
            for k, v in kind_rows.items()
        ),
        key=lambda r: r["count"],
        reverse=True,
    )
    return {
        "facts": summary["facts"]["total"],
        "kind_count": len(kind_rows),
        "mtime": freshness.timestamp() if freshness is not None else None,
        "kind_stats": kind_stats,
    }


def _enrich_with_stats(info: dict[str, Any]) -> None:
    """Fold the `ls -l` stat columns into a vertex info dict (in place).

    Instance/hybrid vertices stat their own store. Aggregations have no store;
    their ``mtime`` is the newest combined-child freshness, computed by the
    caller (it owns child resolution) and pre-set on ``info`` — left untouched
    here. A missing/empty store leaves the stat keys absent so the lens can
    render ``—`` rather than a misleading ``0``.
    """
    store = info.get("store")
    if not store:
        return
    stats = _store_stats(Path(store))
    if stats is not None:
        info.update(stats)


def _extract_vertex_info(vpath: Path, ast: Any) -> dict[str, Any]:
    """Extract metadata from a parsed vertex AST."""
    kind = _classify_kind(ast)

    loops_info: list[dict[str, Any]] = []
    for loop_name, loop_def in ast.loops.items():
        folds = [_describe_fold(f) for f in loop_def.folds]
        loops_info.append({"name": loop_name, "folds": folds})

    info: dict[str, Any] = {
        "name": ast.name,
        "path": str(vpath),
        "kind": kind,
        "loops": loops_info,
    }

    if ast.store is not None:
        store = ast.store
        if not store.is_absolute():
            store = (vpath.parent / store).resolve()
        info["store"] = str(store)

    if ast.combine is not None:
        info["combine"] = [e.name for e in ast.combine]

    if ast.discover is not None:
        info["discover"] = ast.discover

    return info


def _walk_root(
    root_path: Path, home: Path, *, with_stats: bool = False
) -> list[dict[str, Any]]:
    """Walk a .vertex root and collect vertex info from discover/combine."""
    from lang import parse_vertex_file

    root_ast = parse_vertex_file(root_path)
    vertices: list[dict[str, Any]] = []

    if root_ast.discover is not None:
        base_dir = root_path.parent
        for match in sorted(base_dir.glob(root_ast.discover)):
            if match.suffix != ".vertex":
                continue
            if match.resolve() == root_path.resolve():
                continue
            try:
                ast = parse_vertex_file(match)
            except Exception:
                continue
            vertices.append(_extract_vertex_info(match, ast))

    if root_ast.combine is not None:
        from lang.population import resolve_vertex

        for entry in root_ast.combine:
            vpath = resolve_vertex(entry.name, home)
            if not vpath.is_absolute():
                vpath = (root_path.parent / vpath).resolve()
            if not vpath.exists():
                continue
            if any(v["path"] == str(vpath) for v in vertices):
                continue
            try:
                ast = parse_vertex_file(vpath)
            except Exception:
                continue
            vertices.append(_extract_vertex_info(vpath, ast))

    # If root has no discover/combine, list all .vertex files next to root
    if not vertices:
        base_dir = root_path.parent
        for match in sorted(base_dir.glob("**/*.vertex")):
            if match.resolve() == root_path.resolve():
                continue
            try:
                ast = parse_vertex_file(match)
            except Exception:
                continue
            vertices.append(_extract_vertex_info(match, ast))

    if with_stats:
        for info in vertices:
            if info["kind"] == "aggregation":
                info["mtime"] = _aggregation_mtime(info, home)
            else:
                _enrich_with_stats(info)

    return vertices


def _aggregation_mtime(info: dict[str, Any], home: Path) -> float | None:
    """Newest combined-child freshness for an aggregation vertex.

    decision:design/ls-stat-decisions-a-d D — an aggregation answers "anything
    move under here?" via the freshest fact across its combine targets.
    """
    from lang.population import resolve_vertex

    children = info.get("combine") or []
    newest: float | None = None
    for name in children:
        try:
            cpath = resolve_vertex(name, home)
        except Exception:  # noqa: BLE001
            continue
        if not cpath.exists():
            continue
        try:
            from lang import parse_vertex_file

            cast = parse_vertex_file(cpath)
        except Exception:  # noqa: BLE001
            continue
        if cast.store is None:
            continue
        cstore = cast.store
        if not cstore.is_absolute():
            cstore = (cpath.parent / cstore).resolve()
        stats = _store_stats(cstore)
        if stats and stats.get("mtime") is not None:
            newest = stats["mtime"] if newest is None else max(newest, stats["mtime"])
    return newest


def fetch_vertices_local(*, with_stats: bool = False) -> list[dict[str, Any]]:
    """Discover local vertices — the same locations the verbs resolve first.

    Walks ``.loops/**/*.vertex`` plus ``cwd/*.vertex``, mirroring
    ``_find_local_vertex`` / ``_resolve_vertex_for_dispatch`` so the listing
    shows the layer the verbs actually operate in
    (thread:global-local-walk-broken). Returns [] when no local vertices.

    ``with_stats`` folds in the `ls -l` columns (facts/mtime/kind_stats). The
    local layer is always stat'd by the root listing — it is the resumption
    surface (decision:design/ls-as-stat-over-containment).
    """
    from lang import parse_vertex_file

    vertices: list[dict[str, Any]] = []
    seen: set[Path] = set()

    candidates: list[Path] = []
    loops_dir = Path.cwd() / ".loops"
    if loops_dir.is_dir():
        candidates.extend(sorted(loops_dir.glob("**/*.vertex")))
    candidates.extend(sorted(Path.cwd().glob("*.vertex")))

    for match in candidates:
        resolved = match.resolve()
        if resolved in seen or match.name == ".vertex":
            continue
        seen.add(resolved)
        try:
            ast = parse_vertex_file(match)
        except Exception:
            continue
        info = _extract_vertex_info(match, ast)
        info["scope"] = "local"
        if with_stats:
            _enrich_with_stats(info)
        vertices.append(info)

    return vertices


def fetch_vertices(home: Path, *, with_stats: bool = False) -> dict[str, Any]:
    """Discover and describe all vertices under .vertex (workspace root).

    Returns {"vertices": [{name, path, kind, loops, ...}, ...]}.
    Raises FileNotFoundError if .vertex is missing.

    ``with_stats`` folds in the `ls -l` columns. The root listing stats the
    config layer lazily — only when expanded (``sl ls --all``) — since the
    collapsed default renders it as a single count-line
    (decision:design/ls-as-stat-over-containment).
    """
    root_path = home / ".vertex"
    if not root_path.exists():
        raise FileNotFoundError(
            f"{root_path} not found. Run 'loops init' first."
        )

    vertices = _walk_root(root_path, home, with_stats=with_stats)
    return {"vertices": vertices}
