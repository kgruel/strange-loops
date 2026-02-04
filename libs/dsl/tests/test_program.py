from __future__ import annotations

import asyncio
from dataclasses import dataclass
from pathlib import Path
from typing import AsyncIterator

import pytest

from data import Fact
from dsl import VertexProgram, load_vertex_program
from vertex import Vertex


def test_load_vertex_program_expected_ticks_and_default_override(tmp_path: Path) -> None:
    loop = tmp_path / "template.loop"
    loop.write_text(
        'source #"echo \'{"v": 1}\'"#\n'
        'kind "${kind}"\n'
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
        '      boundary when="${kind}.complete"\n'
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
        'kind "${kind}"\n'
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
        '      boundary when="${kind}.complete"\n'
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
    facts: list[Fact]

    async def stream(self) -> AsyncIterator[Fact]:
        for fact in self.facts:
            yield fact


def _make_program(sources: list[_MockSource]) -> VertexProgram:
    """Build a VertexProgram with two loops (a, b) using mock sources."""
    vertex = Vertex("test")
    vertex.register(
        "a", 0, lambda s, p: s + p.get("v", 0), boundary="a.complete", reset=True
    )
    vertex.register(
        "b", 0, lambda s, p: s + p.get("v", 0), boundary="b.complete", reset=True
    )
    return VertexProgram(vertex=vertex, sources=sources, expected_ticks=["a", "b"])


class TestVertexProgramRun:
    """Tests for VertexProgram.run() async iterator."""

    def test_run_yields_ticks(self) -> None:
        source = _MockSource(
            observer="mock",
            facts=[
                Fact.of("a", "mock", v=3),
                Fact.of("a.complete", "mock"),
                Fact.of("b", "mock", v=7),
                Fact.of("b.complete", "mock"),
            ],
        )
        program = _make_program([source])

        async def _run():
            ticks = {}
            async for tick in program.run():
                ticks[tick.name] = tick.payload
            return ticks

        assert asyncio.run(_run()) == {"a": 3, "b": 7}

    def test_run_with_no_sources(self) -> None:
        program = _make_program([])

        async def _run():
            ticks = []
            async for tick in program.run():
                ticks.append(tick)
            return ticks

        assert asyncio.run(_run()) == []


class TestVertexProgramCollect:
    """Tests for VertexProgram.collect() sync convenience."""

    def test_collect_returns_dict(self) -> None:
        source = _MockSource(
            observer="mock",
            facts=[
                Fact.of("a", "mock", v=5),
                Fact.of("a.complete", "mock"),
                Fact.of("b", "mock", v=10),
                Fact.of("b.complete", "mock"),
            ],
        )
        program = _make_program([source])

        result = program.collect()
        assert result == {"a": 5, "b": 10}

    def test_collect_empty_sources(self) -> None:
        program = _make_program([])

        result = program.collect()
        assert result == {}
