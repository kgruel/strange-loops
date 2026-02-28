"""Tests for recursive source collection from compiled vertex trees."""

from pathlib import Path

import pytest
from lang import parse_vertex_file

from engine.compiler import (
    CompiledVertex,
    collect_all_sources,
    compile_vertex_recursive,
)


def _minimal_vertex(name: str, *, sources_block: str = "", loops_block: str = "") -> str:
    """Build a minimal .vertex file string."""
    loops = loops_block or (
        "loops {\n"
        "  x {\n"
        "    fold {\n"
        '      count "inc"\n'
        "    }\n"
        "  }\n"
        "}\n"
    )
    return f'name "{name}"\n{sources_block}{loops}'


def _minimal_loop(kind: str = "test") -> str:
    """Build a minimal .loop file string."""
    return (
        'source "echo hello"\n'
        f'kind "{kind}"\n'
        'observer "shell"\n'
    )


class TestCollectAllSources:
    """collect_all_sources() flattens the vertex tree."""

    def test_root_sources_only(self, tmp_path: Path):
        """Root with sources, no children → sources collected."""
        loop = tmp_path / "a.loop"
        loop.write_text(_minimal_loop("alpha"))

        vertex_path = tmp_path / "root.vertex"
        vertex_path.write_text(_minimal_vertex(
            "root",
            sources_block=f'sources {{\n  path "{loop}"\n}}\n',
        ))

        ast = parse_vertex_file(vertex_path)
        compiled = compile_vertex_recursive(ast)
        sources, specs = collect_all_sources(compiled)

        assert len(sources) == 1
        assert sources[0].kind == "alpha"
        assert specs == {}

    def test_child_sources_only(self, tmp_path: Path):
        """Root with no sources + child with sources → child sources collected."""
        child_dir = tmp_path / "child"
        child_dir.mkdir()

        loop = child_dir / "b.loop"
        loop.write_text(_minimal_loop("beta"))

        child_path = child_dir / "child.vertex"
        child_path.write_text(_minimal_vertex(
            "child",
            sources_block=f'sources {{\n  path "{loop}"\n}}\n',
        ))

        root_path = tmp_path / "root.vertex"
        root_path.write_text(
            'name "root"\n'
            f'discover "./**/*.vertex"\n'
            "loops {\n"
            "  x {\n"
            "    fold {\n"
            '      count "inc"\n'
            "    }\n"
            "  }\n"
            "}\n"
        )

        ast = parse_vertex_file(root_path)
        compiled = compile_vertex_recursive(ast)
        sources, specs = collect_all_sources(compiled)

        assert len(sources) == 1
        assert sources[0].kind == "beta"

    def test_root_and_child_sources(self, tmp_path: Path):
        """Root + child both have sources → both sets collected."""
        root_loop = tmp_path / "root.loop"
        root_loop.write_text(_minimal_loop("alpha"))

        child_dir = tmp_path / "child"
        child_dir.mkdir()

        child_loop = child_dir / "child.loop"
        child_loop.write_text(_minimal_loop("beta"))

        child_path = child_dir / "child.vertex"
        child_path.write_text(_minimal_vertex(
            "child",
            sources_block=f'sources {{\n  path "{child_loop}"\n}}\n',
        ))

        root_path = tmp_path / "root.vertex"
        root_path.write_text(
            'name "root"\n'
            f'sources {{\n  path "{root_loop}"\n}}\n'
            f'discover "./**/*.vertex"\n'
            "loops {\n"
            "  x {\n"
            "    fold {\n"
            '      count "inc"\n'
            "    }\n"
            "  }\n"
            "}\n"
        )

        ast = parse_vertex_file(root_path)
        compiled = compile_vertex_recursive(ast)
        sources, specs = collect_all_sources(compiled)

        kinds = {s.kind for s in sources}
        assert kinds == {"alpha", "beta"}

    def test_deep_nesting_grandchild(self, tmp_path: Path):
        """Grandchild sources collected through two levels of nesting."""
        gc_dir = tmp_path / "level1" / "level2"
        gc_dir.mkdir(parents=True)

        gc_loop = gc_dir / "deep.loop"
        gc_loop.write_text(_minimal_loop("deep"))

        gc_path = gc_dir / "grandchild.vertex"
        gc_path.write_text(_minimal_vertex(
            "grandchild",
            sources_block=f'sources {{\n  path "{gc_loop}"\n}}\n',
        ))

        # Mid discovers only its own subdirectory (level2)
        mid_dir = tmp_path / "level1"
        mid_path = mid_dir / "mid.vertex"
        mid_path.write_text(
            'name "mid"\n'
            'discover "./level2/*.vertex"\n'
            "loops {\n"
            "  x {\n"
            "    fold {\n"
            '      count "inc"\n'
            "    }\n"
            "  }\n"
            "}\n"
        )

        # Root discovers only level1 (not recursive into level2)
        root_path = tmp_path / "root.vertex"
        root_path.write_text(
            'name "root"\n'
            'discover "./level1/*.vertex"\n'
            "loops {\n"
            "  x {\n"
            "    fold {\n"
            '      count "inc"\n'
            "    }\n"
            "  }\n"
            "}\n"
        )

        ast = parse_vertex_file(root_path)
        compiled = compile_vertex_recursive(ast)
        sources, specs = collect_all_sources(compiled)

        kinds = {s.kind for s in sources}
        assert "deep" in kinds

    def test_template_specs_from_child(self, tmp_path: Path):
        """Template specs from child vertices are merged."""
        child_dir = tmp_path / "child"
        child_dir.mkdir()

        template = child_dir / "tmpl.loop"
        template.write_text(
            'source "echo test"\n'
            'kind "{{kind}}"\n'
            'observer "test"\n'
            'format "json"\n'
        )

        child_path = child_dir / "child.vertex"
        child_path.write_text(
            'name "child"\n'
            'sources {\n'
            '  template "tmpl.loop" {\n'
            '    with kind="sensor"\n'
            '    loop {\n'
            '      fold {\n'
            '        count "inc"\n'
            '      }\n'
            '      boundary when="{{kind}}.complete"\n'
            '    }\n'
            '  }\n'
            '}\n'
            "loops {\n"
            "  x {\n"
            "    fold {\n"
            '      count "inc"\n'
            "    }\n"
            "  }\n"
            "}\n"
        )

        root_path = tmp_path / "root.vertex"
        root_path.write_text(
            'name "root"\n'
            f'discover "./**/*.vertex"\n'
            "loops {\n"
            "  x {\n"
            "    fold {\n"
            '      count "inc"\n'
            "    }\n"
            "  }\n"
            "}\n"
        )

        ast = parse_vertex_file(root_path)
        compiled = compile_vertex_recursive(ast)
        sources, specs = collect_all_sources(compiled)

        assert len(sources) == 1
        assert sources[0].kind == "sensor"
        assert "sensor" in specs
        assert specs["sensor"].boundary.kind == "sensor.complete"

    def test_no_sources_anywhere(self, tmp_path: Path):
        """Vertex tree with no sources anywhere → empty lists."""
        root_path = tmp_path / "root.vertex"
        root_path.write_text(_minimal_vertex("root"))

        ast = parse_vertex_file(root_path)
        compiled = compile_vertex_recursive(ast)
        sources, specs = collect_all_sources(compiled)

        assert sources == []
        assert specs == {}

    def test_backward_compat_root_only(self, tmp_path: Path):
        """Single vertex with sources (no children) — same behavior as before."""
        loop = tmp_path / "test.loop"
        loop.write_text(_minimal_loop("test"))

        root_path = tmp_path / "root.vertex"
        root_path.write_text(
            'name "root"\n'
            f'sources {{\n  path "{loop}"\n}}\n'
            "loops {\n"
            "  test {\n"
            "    fold {\n"
            '      count "inc"\n'
            "    }\n"
            "  }\n"
            "}\n"
        )

        ast = parse_vertex_file(root_path)
        compiled = compile_vertex_recursive(ast)
        sources, specs = collect_all_sources(compiled)

        assert len(sources) == 1
        assert sources[0].kind == "test"
        assert sources[0].command == "echo hello"
