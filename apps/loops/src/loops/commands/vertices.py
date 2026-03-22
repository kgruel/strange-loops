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


def _walk_root(root_path: Path, home: Path) -> list[dict[str, Any]]:
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

    return vertices


def fetch_vertices_local() -> dict[str, Any] | None:
    """Discover vertices from the local .loops/.vertex if present.

    Returns {"vertices": [...], "scope": "local"} or None if no local root.
    """
    local_root = Path.cwd() / ".loops" / ".vertex"
    if not local_root.exists():
        return None

    from lang import parse_vertex_file

    # Always include the root itself as context
    vertices: list[dict[str, Any]] = []

    # Walk sibling .vertex files in .loops/
    loops_dir = local_root.parent
    for match in sorted(loops_dir.glob("**/*.vertex")):
        if match.resolve() == local_root.resolve():
            continue
        try:
            ast = parse_vertex_file(match)
        except Exception:
            continue
        vertices.append(_extract_vertex_info(match, ast))

    return {"vertices": vertices, "scope": "local"}


def fetch_vertices(home: Path) -> dict[str, Any]:
    """Discover and describe all vertices under .vertex (workspace root).

    Returns {"vertices": [{name, path, kind, loops, ...}, ...]}.
    Raises FileNotFoundError if .vertex is missing.
    """
    root_path = home / ".vertex"
    if not root_path.exists():
        raise FileNotFoundError(
            f"{root_path} not found. Run 'loops init' first."
        )

    vertices = _walk_root(root_path, home)
    return {"vertices": vertices}
