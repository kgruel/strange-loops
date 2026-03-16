"""Vertex builder — programmatic construction of vertex configurations.

Provides a fluent API for building VertexFile AST objects that can be
compiled directly into runtime Vertex instances. Eliminates the need
to write KDL strings in tests or when creating vertices programmatically.

Usage:
    from engine.builder import vertex

    v = (vertex("myproject")
        .store("./data/myproject.db")
        .loop("heartbeat", fold_count("n"), search=["service"])
        .loop("metric", fold_by("service"))
        .loop("event", fold_collect("items", max_items=100))
        .build())

    # v is a VertexFile AST — pass to compile/materialize:
    from engine import compile_vertex_recursive, materialize_vertex
    compiled = compile_vertex_recursive(v)
    runtime = materialize_vertex(compiled)
"""

from __future__ import annotations

from pathlib import Path

from lang.ast import (
    BoundaryAfter,
    BoundaryEvery,
    BoundaryWhen,
    FoldBy,
    FoldCollect,
    FoldCount,
    FoldDecl,
    FoldLatest,
    FoldMax,
    FoldMin,
    FoldSum,
    FoldAvg,
    FoldWindow,
    LoopDef,
    VertexFile,
)


# ---------------------------------------------------------------------------
# Fold helpers — return FoldDecl tuples
# ---------------------------------------------------------------------------

def fold_count(target: str = "count") -> FoldDecl:
    """Count fold: increment per fact."""
    return FoldDecl(target=target, op=FoldCount(max_items=0))

def fold_by(key_field: str, target: str = "") -> FoldDecl:
    """Upsert fold: dict keyed by field."""
    return FoldDecl(target=target or key_field, op=FoldBy(key_field=key_field))

def fold_collect(target: str = "items", max_items: int = 100) -> FoldDecl:
    """Collect fold: keep last N items."""
    return FoldDecl(target=target, op=FoldCollect(max_items=max_items))

def fold_latest(target: str = "latest") -> FoldDecl:
    """Latest fold: most recent timestamp."""
    return FoldDecl(target=target, op=FoldLatest(max_items=0))

def fold_sum(field: str, target: str = "") -> FoldDecl:
    """Sum fold: running total of a field."""
    return FoldDecl(target=target or field, op=FoldSum(field=field))

def fold_max(field: str, target: str = "") -> FoldDecl:
    """Max fold: track maximum value."""
    return FoldDecl(target=target or field, op=FoldMax(field=field))

def fold_min(field: str, target: str = "") -> FoldDecl:
    """Min fold: track minimum value."""
    return FoldDecl(target=target or field, op=FoldMin(field=field))

def fold_avg(field: str, target: str = "") -> FoldDecl:
    """Average fold: running average."""
    return FoldDecl(target=target or field, op=FoldAvg(field=field))

def fold_window(field: str, size: int, target: str = "") -> FoldDecl:
    """Window fold: sliding buffer."""
    return FoldDecl(target=target or field, op=FoldWindow(field=field, size=size))


# ---------------------------------------------------------------------------
# Loop builder
# ---------------------------------------------------------------------------

class LoopBuilder:
    """Builder for a single loop definition."""

    def __init__(self, kind: str, *folds: FoldDecl):
        self._kind = kind
        self._folds = list(folds)
        self._boundary = None
        self._search: list[str] = []

    def fold(self, *folds: FoldDecl) -> LoopBuilder:
        """Add fold declarations."""
        self._folds.extend(folds)
        return self

    def search(self, *fields: str) -> LoopBuilder:
        """Add searchable payload fields."""
        self._search.extend(fields)
        return self

    def boundary_every(self, count: int) -> LoopBuilder:
        """Fire boundary every N facts."""
        self._boundary = BoundaryEvery(count=count)
        return self

    def boundary_after(self, count: int) -> LoopBuilder:
        """Fire boundary after N facts (one-shot)."""
        self._boundary = BoundaryAfter(count=count)
        return self

    def boundary_when(self, kind: str, **match: str) -> LoopBuilder:
        """Fire boundary when fact of given kind with matching payload arrives."""
        self._boundary = BoundaryWhen(
            kind=kind,
            match=tuple(match.items()),
        )
        return self

    def build(self) -> tuple[str, LoopDef]:
        """Build the (kind, LoopDef) pair."""
        return self._kind, LoopDef(
            folds=tuple(self._folds),
            boundary=self._boundary,
            search=tuple(self._search),
        )


# ---------------------------------------------------------------------------
# Vertex builder
# ---------------------------------------------------------------------------

class VertexBuilder:
    """Fluent builder for VertexFile AST objects."""

    def __init__(self, name: str):
        self._name = name
        self._store: Path | None = None
        self._loops: list[tuple[str, LoopDef]] = []
        self._routes: dict[str, str] | None = None
        self._observer_scoped = False

    def store(self, path: str) -> VertexBuilder:
        """Set the store path."""
        self._store = Path(path)
        return self

    def loop(self, kind: str, *folds: FoldDecl,
             search: list[str] | None = None,
             boundary_every: int | None = None,
             boundary_after: int | None = None) -> VertexBuilder:
        """Add a loop with folds and optional boundary/search."""
        boundary = None
        if boundary_every is not None:
            boundary = BoundaryEvery(count=boundary_every)
        elif boundary_after is not None:
            boundary = BoundaryAfter(count=boundary_after)

        self._loops.append((kind, LoopDef(
            folds=tuple(folds),
            boundary=boundary,
            search=tuple(search or []),
        )))
        return self

    def loop_builder(self, kind: str, *folds: FoldDecl) -> LoopBuilder:
        """Return a LoopBuilder for complex loop config. Call .done() to add."""
        return _AttachedLoopBuilder(self, kind, *folds)

    def route(self, from_kind: str, to_kind: str) -> VertexBuilder:
        """Add a kind route."""
        if self._routes is None:
            self._routes = {}
        self._routes[from_kind] = to_kind
        return self

    def observer_scoped(self) -> VertexBuilder:
        """Enable observer-scoped folds."""
        self._observer_scoped = True
        return self

    def build(self) -> VertexFile:
        """Build the VertexFile AST."""
        return VertexFile(
            name=self._name,
            loops=dict(self._loops),
            store=self._store,
            routes=self._routes,
            observer_scoped=self._observer_scoped,
        )

    def write(self, path: Path) -> VertexFile:
        """Build the AST and write as KDL to the given path.

        This round-trips through KDL serialization — useful for integration
        tests that need a .vertex file on disk.
        """
        ast = self.build()
        # Write a KDL representation
        lines = [f'name "{self._name}"']
        if self._store:
            lines.append(f'store "{self._store}"')
        if self._loops:
            lines.append("loops {")
            for kind, loop_def in self._loops:
                lines.append(f"  {kind} {{")
                if loop_def.folds:
                    lines.append("    fold {")
                    for fd in loop_def.folds:
                        lines.append(f"      {_fold_to_kdl(fd)}")
                    lines.append("    }")
                if loop_def.search:
                    fields = " ".join(f'"{f}"' for f in loop_def.search)
                    lines.append(f"    search {fields}")
                if loop_def.boundary is not None:
                    lines.append(f"    {_boundary_to_kdl(loop_def.boundary)}")
                lines.append("  }")
            lines.append("}")
        if self._routes:
            lines.append("routes {")
            for fr, to in self._routes.items():
                lines.append(f'  "{fr}" "{to}"')
            lines.append("}")
        path.write_text("\n".join(lines) + "\n")
        return ast


class _AttachedLoopBuilder(LoopBuilder):
    """LoopBuilder that adds itself back to the parent VertexBuilder."""

    def __init__(self, parent: VertexBuilder, kind: str, *folds: FoldDecl):
        super().__init__(kind, *folds)
        self._parent = parent

    def done(self) -> VertexBuilder:
        """Finish loop config and return to vertex builder."""
        kind, loop_def = self.build()
        self._parent._loops.append((kind, loop_def))
        return self._parent


# ---------------------------------------------------------------------------
# KDL serialization helpers
# ---------------------------------------------------------------------------

def _fold_to_kdl(fd: FoldDecl) -> str:
    """Emit KDL: target_name "op" [args...]"""
    t = fd.target
    op = fd.op
    if isinstance(op, FoldCount):
        return f'{t} "inc"'
    elif isinstance(op, FoldBy):
        return f'{t} "by" "{op.key_field}"'
    elif isinstance(op, FoldCollect):
        return f'{t} "collect" {op.max_items}'
    elif isinstance(op, FoldLatest):
        return f'{t} "latest"'
    elif isinstance(op, FoldSum):
        return f'{t} "sum" "{op.field}"'
    elif isinstance(op, FoldMax):
        return f'{t} "max" "{op.field}"'
    elif isinstance(op, FoldMin):
        return f'{t} "min" "{op.field}"'
    elif isinstance(op, FoldAvg):
        return f'{t} "avg" "{op.field}"'
    elif isinstance(op, FoldWindow):
        return f'{t} "window" {op.size} "{op.field}"'
    return f'// unknown fold: {fd}'


def _boundary_to_kdl(b) -> str:
    if isinstance(b, BoundaryEvery):
        return f"boundary every={b.count}"
    elif isinstance(b, BoundaryAfter):
        return f"boundary after={b.count}"
    elif isinstance(b, BoundaryWhen):
        match_str = " ".join(f'{k}="{v}"' for k, v in b.match)
        return f'boundary when="{b.kind}" {match_str}'.strip()
    return f"// unknown boundary: {b}"


# ---------------------------------------------------------------------------
# Convenience entry point
# ---------------------------------------------------------------------------

def vertex(name: str) -> VertexBuilder:
    """Create a new vertex builder."""
    return VertexBuilder(name)
