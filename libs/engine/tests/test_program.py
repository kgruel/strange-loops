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
    tick = program.receive(Fact.of("foo", "test", v=2))
    assert tick is None
    tick = program.receive(Fact.of("foo.complete", "test"))
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

    program.receive(Fact.of("a", "test"))
    tick_a = program.receive(Fact.of("a.complete", "test"))
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
    command: str = "mock-cmd"

    async def collect(self) -> AsyncIterator[Fact]:
        for fact in self.facts:
            yield fact


def _make_program(mock_sources: list[_MockSource]) -> VertexProgram:
    """Build a VertexProgram with two loops (a, b) using mock sources."""
    vertex = Vertex("test")
    vertex.register(
        "a", 0, lambda s, p: s + p.get("v", 0), boundary="_sync.a", reset=True
    )
    vertex.register(
        "b", 0, lambda s, p: s + p.get("v", 0), boundary="_sync.b", reset=True
    )
    pairs = [(s, Cadence.always()) for s in mock_sources]
    return VertexProgram(vertex=vertex, sources=pairs, expected_ticks=["a", "b"])


class TestVertexProgramSync:
    """Tests for VertexProgram.sync() via Executor."""

    def test_sync_returns_ticks(self) -> None:
        source_a = _MockSource(
            observer="mock",
            kind="a",
            facts=[Fact.of("a", "mock", v=3)],
        )
        source_b = _MockSource(
            observer="mock",
            kind="b",
            facts=[Fact.of("b", "mock", v=7)],
        )
        program = _make_program([source_a, source_b])
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


class TestVertexProgramProtocol:
    def test_setattr_raises(self):
        program = _make_program([])
        with pytest.raises(AttributeError, match="cannot assign"):
            program.vertex = None

    def test_repr(self):
        program = _make_program([])
        r = repr(program)
        assert "VertexProgram" in r


def test_load_skip_sources(tmp_path: Path) -> None:
    """skip_sources=True omits source compilation."""
    vertex_file = tmp_path / "minimal.vertex"
    vertex_file.write_text(
        'name "minimal"\n'
        'store "./m.db"\n'
        'loops {\n'
        '  heartbeat {\n'
        '    fold { n "inc" }\n'
        '  }\n'
        '}\n'
    )
    prog = load_vertex_program(vertex_file, skip_sources=True)
    assert prog.sources == []


def test_substitute_no_sources():
    """_substitute_vertex_vars with empty sources returns ast unchanged."""
    from engine.program import _substitute_vertex_vars
    from lang.ast import VertexFile

    ast = VertexFile(name="test", loops={}, sources=())
    result = _substitute_vertex_vars(ast, {"k": "v"})
    assert result is ast


def test_substitute_non_template_passthrough():
    """Non-template sources pass through _substitute_vertex_vars unchanged."""
    from engine.program import _substitute_vertex_vars
    from lang.ast import VertexFile

    # A plain source (non-TemplateSource) entry
    class PlainSource:
        pass

    plain = PlainSource()
    ast = VertexFile(name="test", loops={}, sources=(plain,))
    result = _substitute_vertex_vars(ast, {"k": "v"})
    assert result.sources[0] is plain


# ---------------------------------------------------------------------------
# program.receive dispatches run-clauses (the consolidation that closed
# the three-CLI-site dispatch fragility — see decision
# design/dispatch-consolidation-via-program).
# ---------------------------------------------------------------------------


def test_program_receive_dispatches_run_clause(tmp_path: Path) -> None:
    """When vertex.receive produces a tick with .run, program.receive fires the dispatcher."""
    from engine import SqliteStore
    from engine.loop import Loop

    store = SqliteStore(
        path=tmp_path / "test.db",
        serialize=Fact.to_dict,
        deserialize=Fact.from_dict,
    )
    v = Vertex("orch", store=store)
    loop = Loop(
        name="task",
        initial=[],
        fold=lambda s, p: [*s, p],
        boundary_count=1,
        boundary_mode="every",
        boundary_run="scripts/dispatch.sh",
    )
    v.register_loop(loop)
    v.replay()

    calls: list[tuple[str, str, Path]] = []

    def dispatcher(command: str, tick_name: str, vertex_path: Path) -> None:
        calls.append((command, tick_name, vertex_path))

    fake_path = tmp_path / "orch.vertex"
    program = VertexProgram(
        vertex=v, sources=[], expected_ticks=["task"],
        path=fake_path, run_dispatcher=dispatcher,
    )

    tick = program.receive(Fact.of("task", "kyle", name="job1"))
    assert tick is not None
    assert tick.run == "scripts/dispatch.sh"
    assert calls == [("scripts/dispatch.sh", "task", fake_path)]
    store.close()


def test_program_receive_no_dispatcher_is_noop(tmp_path: Path) -> None:
    """No dispatcher wired → program.receive still returns the tick, no error on .run."""
    from engine import SqliteStore
    from engine.loop import Loop

    store = SqliteStore(
        path=tmp_path / "test.db",
        serialize=Fact.to_dict,
        deserialize=Fact.from_dict,
    )
    v = Vertex("orch", store=store)
    loop = Loop(
        name="task",
        initial=[],
        fold=lambda s, p: [*s, p],
        boundary_count=1,
        boundary_mode="every",
        boundary_run="scripts/dispatch.sh",
    )
    v.register_loop(loop)
    v.replay()

    program = VertexProgram(vertex=v, sources=[], expected_ticks=["task"])  # no dispatcher

    tick = program.receive(Fact.of("task", "kyle", name="job1"))
    assert tick is not None
    assert tick.run == "scripts/dispatch.sh"  # tick still carries it
    store.close()


def test_program_sync_dispatches_evaluate_boundary_ticks(tmp_path: Path) -> None:
    """program.sync dispatches run-clauses on ticks produced by evaluate_boundaries (catchup path)."""
    from engine import SqliteStore

    # Pre-seed a store with a fact that will trigger a vertex-level boundary
    # on next sync via evaluate_boundaries (catchup path).
    store = SqliteStore(
        path=tmp_path / "test.db",
        serialize=Fact.to_dict,
        deserialize=Fact.from_dict,
    )
    store.append(Fact.of("task", "kyle", name="job1", status="open"))

    v = Vertex("orch", store=store)
    v.register("task", {}, lambda s, p: {**s, p["name"]: p})
    v.register_vertex_boundary(
        "task", match=(("status", "open"),),
        run="scripts/dispatch.sh",
    )
    v.replay()

    calls: list[tuple[str, str, Path]] = []

    def dispatcher(command: str, tick_name: str, vertex_path: Path) -> None:
        calls.append((command, tick_name, vertex_path))

    fake_path = tmp_path / "orch.vertex"
    program = VertexProgram(
        vertex=v, sources=[], expected_ticks=[],
        path=fake_path, run_dispatcher=dispatcher,
    )

    result = program.sync()
    assert any(t.run == "scripts/dispatch.sh" for t in result.ticks)
    assert calls == [("scripts/dispatch.sh", "orch", fake_path)]
    store.close()
