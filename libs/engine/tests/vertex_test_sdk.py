"""Test SDK for building Vertex instances with minimal boilerplate.

Collapses the store+vertex+register pattern into a fluent builder.
Focused on test ergonomics — not a public API.
"""
from __future__ import annotations

from pathlib import Path
from typing import Any, Callable

from atoms import Fact, Spec, Count, Latest, Sum, Collect
from engine import Loop, Vertex
from engine.sqlite_store import SqliteStore


def fact(kind: str, observer: str = "test", **payload) -> Fact:
    """Create a Fact for testing."""
    return Fact.of(kind, observer, **payload)


class VertexTestBuilder:
    """Fluent builder for test vertices with optional store."""

    def __init__(self, name: str = "test"):
        self._name = name
        self._loops: list[Loop] = []
        self._store_path: Path | None = None
        self._store: SqliteStore | None = None
        self._routes: dict[str, str] | None = None
        self._parse_pipelines: dict[str, list] | None = None

    def with_store(self, tmp_path: Path, filename: str = "test.db") -> VertexTestBuilder:
        """Attach a SqliteStore backed by a tmp_path database."""
        self._store_path = tmp_path / filename
        return self

    def loop(self, name: str, initial: Any, fold: Callable,
             *, boundary_kind: str | None = None,
             boundary_count: int | None = None,
             boundary_mode: str = "when",
             boundary_match: tuple = (),
             boundary_conditions: tuple = (),
             reset: bool = True) -> VertexTestBuilder:
        """Add a loop with explicit fold function."""
        self._loops.append(Loop(
            name=name, initial=initial, fold=fold,
            boundary_kind=boundary_kind,
            boundary_count=boundary_count,
            boundary_mode=boundary_mode,
            boundary_match=boundary_match,
            boundary_conditions=boundary_conditions,
            reset=reset,
        ))
        return self

    def count_loop(self, name: str, *, boundary_kind: str | None = None,
                   boundary_count: int | None = None,
                   boundary_mode: str = "when",
                   reset: bool = True) -> VertexTestBuilder:
        """Add a loop that counts facts."""
        spec = Spec(name=name, folds=(Count(target="n"),))
        self._loops.append(Loop(
            name=name, initial=spec.initial_state(),
            fold=spec.apply,
            boundary_kind=boundary_kind,
            boundary_count=boundary_count,
            boundary_mode=boundary_mode,
            reset=reset,
        ))
        return self

    def sum_loop(self, name: str, field: str = "value",
                 *, boundary_kind: str | None = None,
                 boundary_count: int | None = None,
                 boundary_mode: str = "when",
                 reset: bool = True) -> VertexTestBuilder:
        """Add a loop that sums a field."""
        spec = Spec(name=name, folds=(Sum(target="total", field=field),))
        self._loops.append(Loop(
            name=name, initial=spec.initial_state(),
            fold=spec.apply,
            boundary_kind=boundary_kind,
            boundary_count=boundary_count,
            boundary_mode=boundary_mode,
            reset=reset,
        ))
        return self

    def latest_loop(self, name: str) -> VertexTestBuilder:
        """Add a loop that keeps the latest payload."""
        spec = Spec(name=name, folds=(Latest(target="_latest"),))
        self._loops.append(Loop(
            name=name, initial=spec.initial_state(),
            fold=spec.apply,
        ))
        return self

    def routes(self, mapping: dict[str, str]) -> VertexTestBuilder:
        """Set routing rules."""
        self._routes = mapping
        return self

    def parse_pipelines(self, pipelines: dict[str, list]) -> VertexTestBuilder:
        """Set parse pipelines."""
        self._parse_pipelines = pipelines
        return self

    def build(self) -> tuple[Vertex, SqliteStore | None]:
        """Build the Vertex and optional store. Caller must close store."""
        store = None
        if self._store_path is not None:
            store = SqliteStore(
                path=self._store_path,
                serialize=Fact.to_dict,
                deserialize=Fact.from_dict,
            )

        v = Vertex(self._name, store=store)
        for loop in self._loops:
            v.register_loop(loop)
        if self._routes:
            v.set_routes(self._routes)
        if self._parse_pipelines:
            v.set_parse_pipelines(self._parse_pipelines)
        return v, store

    def build_vertex(self) -> Vertex:
        """Build just the Vertex (no store)."""
        v, _ = self.build()
        return v


def reopen_store(path: Path) -> SqliteStore:
    """Open a new SqliteStore connection to an existing database."""
    return SqliteStore(
        path=path,
        serialize=Fact.to_dict,
        deserialize=Fact.from_dict,
    )
