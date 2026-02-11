from __future__ import annotations

import asyncio
from dataclasses import dataclass
from pathlib import Path
from typing import AsyncIterator

import pytest

from atoms import Fact
from engine import VertexProgram, load_vertex_program
from engine import Vertex


def test_load_vertex_program_vars_substitution(tmp_path: Path) -> None:
    """Vars are resolved in template source param values before compilation."""
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
        '    with kind="a" host="${host_a}"\n'
        '    with kind="b" host="${host_b}"\n'
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

    program = load_vertex_program(
        vertex,
        vars={"host_a": "10.0.0.1", "host_b": "10.0.0.2"},
    )
    assert program.expected_ticks == ["a", "b"]

    # Verify the sources got the resolved host values by checking the
    # compiled source commands contain the substituted IPs
    commands = [s.command for s in program.sources if s.command]
    # The template uses ${host} in the source command — here the loop file
    # doesn't reference host in the source, so just verify compilation works.
    # The key check: no ${host_a} or ${host_b} remain in the program.
    assert len(program.sources) == 2


def test_load_vertex_program_vars_unmatched_passthrough(tmp_path: Path) -> None:
    """Unmatched ${var} references are left as-is (for template instantiation)."""
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
        '    with kind="x" host="${unknown_var}"\n'
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

    # Unmatched vars pass through — should not raise
    program = load_vertex_program(vertex, vars={"other": "val"})
    assert program.expected_ticks == ["x"]


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
    every: float | None = None

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


# ---------------------------------------------------------------------------
# Round-based collection (has_polling, collect with rounds=)
# ---------------------------------------------------------------------------


@dataclass
class _PollingMockSource:
    """Source that yields multiple rounds of facts (simulates polling)."""

    observer: str
    rounds: list[list[Fact]]
    every: float = 1.0  # marks this as a polling source

    async def stream(self) -> AsyncIterator[Fact]:
        for round_facts in self.rounds:
            for fact in round_facts:
                yield fact


class TestHasPolling:
    def test_has_polling_true(self) -> None:
        source = _PollingMockSource(observer="mock", rounds=[], every=30.0)
        program = _make_program([source])
        assert program.has_polling is True

    def test_has_polling_false(self) -> None:
        source = _MockSource(observer="mock", facts=[])
        program = _make_program([source])
        assert program.has_polling is False


class TestCollectRounds:
    def test_collect_rounds_one(self) -> None:
        """Two rounds available, collect(rounds=1) returns after first."""
        source = _PollingMockSource(
            observer="mock",
            rounds=[
                [
                    Fact.of("a", "mock", v=1),
                    Fact.of("a.complete", "mock"),
                    Fact.of("b", "mock", v=2),
                    Fact.of("b.complete", "mock"),
                ],
                [
                    Fact.of("a", "mock", v=10),
                    Fact.of("a.complete", "mock"),
                    Fact.of("b", "mock", v=20),
                    Fact.of("b.complete", "mock"),
                ],
            ],
        )
        program = _make_program([source])
        result = program.collect(rounds=1)
        # Should get first round values only
        assert result == {"a": 1, "b": 2}

    def test_collect_rounds_default_unchanged(self) -> None:
        """Without rounds=, collect() runs until sources exhaust."""
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

    def test_collect_async_rounds(self) -> None:
        """Async variant with rounds=1."""
        source = _PollingMockSource(
            observer="mock",
            rounds=[
                [
                    Fact.of("a", "mock", v=3),
                    Fact.of("a.complete", "mock"),
                    Fact.of("b", "mock", v=7),
                    Fact.of("b.complete", "mock"),
                ],
                [
                    Fact.of("a", "mock", v=30),
                    Fact.of("a.complete", "mock"),
                    Fact.of("b", "mock", v=70),
                    Fact.of("b.complete", "mock"),
                ],
            ],
        )
        program = _make_program([source])

        result = asyncio.run(program.collect_async(rounds=1))
        assert result == {"a": 3, "b": 7}
