from __future__ import annotations

import asyncio
from dataclasses import dataclass
from pathlib import Path
from typing import AsyncIterator

import pytest

from atoms import Fact
from engine import Cadence, VertexProgram, load_vertex_program
from engine import Vertex


def test_load_vertex_program_vars_substitution(tmp_path: Path) -> None:
    """Vars are resolved in template source param values before compilation."""
    loop = tmp_path / "template.loop"
    loop.write_text(
        'source #"echo \'{"v": 1}\'"#\n'
        'kind "{{kind}}"\n'
        'observer "test"\n'
        'format "json"\n'
    )

    vertex = tmp_path / "prog.vertex"
    vertex.write_text(
        'name "prog"\n'
        "sources {\n"
        '  template "template.loop" {\n'
        '    with kind="a" host="{{host_a}}"\n'
        '    with kind="b" host="{{host_b}}"\n'
        "    loop {\n"
        "      fold {\n"
        '        acc "sum" "v"\n'
        "      }\n"
        '      boundary when="{{kind}}.complete"\n'
        "    }\n"
        "  }\n"
        "}\n"
        'emit "prog"\n'
    )

    program = load_vertex_program(
        vertex,
        vars={"host_a": "10.0.0.1", "host_b": "10.0.0.2"},
    )
    assert program.expected_ticks == ["a", "b"]

    assert len(program.sources) == 2
    # Each entry is a (Source, Cadence) pair
    for source, cadence in program.sources:
        assert source.command is not None


def test_load_vertex_program_vars_unmatched_passthrough(tmp_path: Path) -> None:
    """Unmatched {{var}} references are left as-is (for template instantiation)."""
    loop = tmp_path / "template.loop"
    loop.write_text(
        'source #"echo \'{"v": 1}\'"#\n'
        'kind "{{kind}}"\n'
        'observer "test"\n'
        'format "json"\n'
    )

    vertex = tmp_path / "prog.vertex"
    vertex.write_text(
        'name "prog"\n'
        "sources {\n"
        '  template "template.loop" {\n'
        '    with kind="x" host="{{unknown_var}}"\n'
        "    loop {\n"
        "      fold {\n"
        '        acc "sum" "v"\n'
        "      }\n"
        '      boundary when="{{kind}}.complete"\n'
        "    }\n"
        "  }\n"
        "}\n"
        'emit "prog"\n'
    )

    # Unmatched vars pass through — should not raise
    program = load_vertex_program(vertex, vars={"other": "val"})
    assert program.expected_ticks == ["x"]


def test_load_vertex_program_expected_ticks_and_default_override(tmp_path: Path) -> None:
    loop = tmp_path / "template.loop"
    loop.write_text(
        'source #"echo \'{"v": 1}\'"#\n'
        'kind "{{kind}}"\n'
        'observer "test"\n'
        'format "json"\n'
    )

    vertex = tmp_path / "prog.vertex"
    vertex.write_text(
        'name "prog"\n'
        "sources {\n"
        '  template "template.loop" {\n'
        '    with kind="foo"\n'
        "    loop {\n"
        "      fold {\n"
        '        acc "sum" "v"\n'
        "      }\n"
        '      boundary when="{{kind}}.complete"\n'
        "    }\n"
        "  }\n"
        "}\n"
        'emit "prog"\n'
    )

    def fold(state: dict, payload: dict) -> dict:
        return {"acc": state.get("acc", 0) + payload.get("v", 0)}

    program = load_vertex_program(vertex, default_fold_override=({"acc": 0}, fold))
    assert program.expected_ticks == ["foo"]

    # Ensure override is actually applied by folding and firing the boundary.
    tick = program.vertex.receive(Fact.of("foo", "test", v=2))
    assert tick is None
    tick = program.vertex.receive(Fact.of("foo.complete", "test"))
    assert tick is not None
    assert tick.name == "foo"
    assert tick.payload["acc"] == 2


def test_load_vertex_program_per_kind_overrides(tmp_path: Path) -> None:
    loop = tmp_path / "template.loop"
    loop.write_text(
        'source #"echo \'{"v": 1}\'"#\n'
        'kind "{{kind}}"\n'
        'observer "test"\n'
        'format "json"\n'
    )

    vertex = tmp_path / "prog.vertex"
    vertex.write_text(
        'name "prog"\n'
        "sources {\n"
        '  template "template.loop" {\n'
        '    with kind="a"\n'
        '    with kind="b"\n'
        "    loop {\n"
        "      fold {\n"
        '        seen "inc"\n'
        "      }\n"
        '      boundary when="{{kind}}.complete"\n'
        "    }\n"
        "  }\n"
        "}\n"
        'emit "prog"\n'
    )

    def fold_a(state: dict, payload: dict) -> dict:
        return {"seen": state.get("seen", 0) + 10}

    program = load_vertex_program(vertex, fold_overrides={"a": ({"seen": 0}, fold_a)})
    assert program.expected_ticks == ["a", "b"]

    program.vertex.receive(Fact.of("a", "test"))
    tick_a = program.vertex.receive(Fact.of("a.complete", "test"))
    assert tick_a is not None
    assert tick_a.name == "a"
    assert tick_a.payload["seen"] == 10


# ---------------------------------------------------------------------------
# VertexProgram.run() and .collect()
# ---------------------------------------------------------------------------


@dataclass
class _MockSource:
    """Source that yields predetermined facts."""

    observer: str
    kind: str
    facts: list[Fact]

    async def collect(self) -> AsyncIterator[Fact]:
        for fact in self.facts:
            yield fact


def _make_program(mock_sources: list[_MockSource]) -> VertexProgram:
    """Build a VertexProgram with two loops (a, b) using mock sources."""
    vertex = Vertex("test")
    vertex.register(
        "a", 0, lambda s, p: s + p.get("v", 0), boundary="a.complete", reset=True
    )
    vertex.register(
        "b", 0, lambda s, p: s + p.get("v", 0), boundary="b.complete", reset=True
    )
    pairs = [(s, Cadence.always()) for s in mock_sources]
    return VertexProgram(vertex=vertex, sources=pairs, expected_ticks=["a", "b"])


class TestVertexProgramSync:
    """Tests for VertexProgram.sync() via Executor."""

    def test_sync_returns_ticks(self) -> None:
        source = _MockSource(
            observer="mock",
            kind="a",
            facts=[
                Fact.of("a", "mock", v=3),
                Fact.of("a.complete", "mock"),
                Fact.of("b", "mock", v=7),
                Fact.of("b.complete", "mock"),
            ],
        )
        program = _make_program([source])
        result = program.sync(force=True)
        tick_map = {t.name: t.payload for t in result.ticks}
        assert tick_map == {"a": 3, "b": 7}

    def test_sync_with_no_sources(self) -> None:
        program = _make_program([])
        result = program.sync(force=True)
        assert result.ticks == []

    def test_sync_empty_sources_no_force(self) -> None:
        program = _make_program([])
        result = program.sync()
        assert result.ticks == []


# ---------------------------------------------------------------------------
# _substitute_vertex_vars preserves from_
# ---------------------------------------------------------------------------


def test_substitute_vertex_vars_preserves_from(tmp_path: Path) -> None:
    """_substitute_vertex_vars passes from_ through unchanged."""
    from lang.ast import FromFile, SourceParams, TemplateSource, VertexFile
    from engine.program import _substitute_vertex_vars

    from_source = FromFile(path=Path("./feeds.list"))
    ast = VertexFile(
        name="test",
        loops={},
        sources=(
            TemplateSource(
                template=Path("template.loop"),
                params=(SourceParams(values={"kind": "{{k}}"}),),
                from_=from_source,
                loop=None,
            ),
        ),
    )

    result = _substitute_vertex_vars(ast, {"k": "resolved"})

    entry = result.sources[0]
    assert isinstance(entry, TemplateSource)
    assert entry.from_ is from_source
    assert entry.params[0].values["kind"] == "resolved"
