"""Tests for main.py pure helper functions."""

from pathlib import Path

import pytest


class TestVertexName:
    def test_none(self):
        from loops.main import _vertex_name
        assert _vertex_name(None) is None

    def test_dotvertex(self):
        from loops.main import _vertex_name
        # .vertex stem is ".vertex"
        assert _vertex_name(Path("/project/.vertex")) == ".vertex"

    def test_named_vertex(self):
        from loops.main import _vertex_name
        assert _vertex_name(Path("/data/proj.vertex")) == "proj"


class TestExtractBlockText:
    def test_found(self):
        from loops.main import _extract_block_text
        content = 'name "test"\nloops {\n  metric { fold { n "inc" } }\n}\n'
        result = _extract_block_text(content, "loops")
        assert result is not None
        assert "metric" in result

    def test_unclosed_braces(self):
        from loops.main import _extract_block_text
        content = 'loops {\n  metric { fold { n "inc" }\n'
        result = _extract_block_text(content, "loops")
        assert result is None

    def test_not_found(self):
        from loops.main import _extract_block_text
        result = _extract_block_text('name "test"', "loops")
        assert result is None


class TestExtractLoopsText:
    def test_delegates(self):
        from loops.main import _extract_loops_text
        content = 'loops {\n  metric { fold { n "inc" } }\n}\n'
        assert _extract_loops_text(content) is not None


class TestFindLocalVertex:
    def test_no_vertex_returns_none(self, tmp_path, monkeypatch):
        from loops.main import _find_local_vertex
        monkeypatch.chdir(tmp_path)
        # No .loops dir, no .vertex files
        result = _find_local_vertex()
        assert result is None

    def test_dotloops_dir(self, tmp_path, monkeypatch):
        from loops.main import _find_local_vertex
        monkeypatch.chdir(tmp_path)
        loops_dir = tmp_path / ".loops"
        loops_dir.mkdir()
        vf = loops_dir / "proj.vertex"
        vf.write_text('name "proj"')
        result = _find_local_vertex()
        assert result == vf

    def test_dot_vertex(self, tmp_path, monkeypatch):
        from loops.main import _find_local_vertex
        monkeypatch.chdir(tmp_path)
        vf = tmp_path / ".vertex"
        vf.write_text('name "test"')
        result = _find_local_vertex()
        assert result == vf


class TestIsStaticPlain:
    def test_static_plain(self):
        from loops.main import _is_static_plain
        assert _is_static_plain(["--static", "--plain"]) is True

    def test_plain_only(self):
        from loops.main import _is_static_plain
        assert _is_static_plain(["--plain"]) is False

    def test_with_help(self):
        from loops.main import _is_static_plain
        assert _is_static_plain(["--static", "--plain", "--help"]) is False

    def test_no_flags(self):
        from loops.main import _is_static_plain
        assert _is_static_plain(["read", "proj"]) is False
