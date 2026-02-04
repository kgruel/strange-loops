from __future__ import annotations

from pathlib import Path

from data import Fact
from dsl import load_vertex_program


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
