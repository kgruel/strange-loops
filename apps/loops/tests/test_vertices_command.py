"""Tests for loops.commands.vertices metadata extraction and discovery."""

from pathlib import Path
from types import SimpleNamespace

from loops.commands.vertices import (
    _classify_kind,
    _describe_fold,
    _extract_vertex_info,
    fetch_vertices,
)


def _ast(*, name="v", store=None, discover=None, combine=None, loops=None):
    return SimpleNamespace(
        name=name,
        store=store,
        discover=discover,
        combine=combine,
        loops=loops or {},
    )


def _loop_with_fold(op):
    return SimpleNamespace(folds=[SimpleNamespace(op=op)])


class FoldBy:
    def __init__(self, key_field):
        self.key_field = key_field


class FoldCollect:
    def __init__(self, max_items):
        self.max_items = max_items


class FoldWindow:
    def __init__(self, max_items):
        self.max_items = max_items


class FoldCount: ...
class FoldSum: ...
class FoldLatest: ...
class FoldMax: ...
class FoldMin: ...
class FoldAvg: ...
class FoldCustom: ...


class TestClassifyKind:
    def test_instance(self):
        assert _classify_kind(_ast(store=Path("x.db"))) == "instance"

    def test_aggregation_discover(self):
        assert _classify_kind(_ast(discover="**/*.vertex")) == "aggregation"

    def test_aggregation_combine(self):
        assert _classify_kind(_ast(combine=[SimpleNamespace(name="a")])) == "aggregation"

    def test_hybrid(self):
        assert _classify_kind(_ast(store=Path("x.db"), discover="**/*.vertex")) == "hybrid"


class TestDescribeFold:
    def test_fold_by(self):
        assert _describe_fold(SimpleNamespace(op=FoldBy("service"))) == "items by service"

    def test_fold_collect(self):
        assert _describe_fold(SimpleNamespace(op=FoldCollect(10))) == "collect 10"

    def test_fold_window(self):
        assert _describe_fold(SimpleNamespace(op=FoldWindow(5))) == "window 5"

    def test_scalar_fold_names(self):
        assert _describe_fold(SimpleNamespace(op=FoldCount())) == "count"
        assert _describe_fold(SimpleNamespace(op=FoldSum())) == "sum"
        assert _describe_fold(SimpleNamespace(op=FoldLatest())) == "latest"
        assert _describe_fold(SimpleNamespace(op=FoldMax())) == "max"
        assert _describe_fold(SimpleNamespace(op=FoldMin())) == "min"
        assert _describe_fold(SimpleNamespace(op=FoldAvg())) == "avg"

    def test_unknown_fold_fallback(self):
        assert _describe_fold(SimpleNamespace(op=FoldCustom())) == "custom"


class TestExtractVertexInfo:
    def test_relative_store_is_resolved(self, tmp_path):
        vpath = tmp_path / "child.vertex"
        ast = _ast(
            name="child",
            store=Path("./child.db"),
            loops={"metric": _loop_with_fold(FoldBy("service"))},
        )
        info = _extract_vertex_info(vpath, ast)
        assert info["name"] == "child"
        assert info["kind"] == "instance"
        assert info["store"] == str((tmp_path / "child.db").resolve())
        assert info["loops"][0]["folds"] == ["items by service"]

    def test_combine_and_discover_fields(self, tmp_path):
        vpath = tmp_path / "parent.vertex"
        ast = _ast(
            name="parent",
            discover="children/*.vertex",
            combine=[SimpleNamespace(name="a"), SimpleNamespace(name="b")],
            loops={"ping": _loop_with_fold(FoldCount())},
        )
        info = _extract_vertex_info(vpath, ast)
        assert info["kind"] == "aggregation"
        assert info["combine"] == ["a", "b"]
        assert info["discover"] == "children/*.vertex"


class TestFetchVertices:
    def test_missing_root_vertex(self, tmp_path):
        try:
            fetch_vertices(tmp_path)
        except FileNotFoundError as e:
            assert "loops init" in str(e)
        else:
            raise AssertionError("expected FileNotFoundError")

    def test_discover_children(self, tmp_path):
        root = tmp_path / ".vertex"
        root.write_text('name "root"\ndiscover "children/*.vertex"\n')
        children = tmp_path / "children"
        children.mkdir()
        (children / "a.vertex").write_text('name "a"\nstore "./a.db"\nloops { ping { fold { n "inc" } } }\n')
        (children / "bad.vertex").write_text('not valid kdl')
        result = fetch_vertices(tmp_path)
        assert len(result["vertices"]) == 1
        assert result["vertices"][0]["name"] == "a"

    def test_combine_children(self, tmp_path):
        root = tmp_path / ".vertex"
        root.write_text('name "root"\ncombine { vertex "child" }\n')
        child_dir = tmp_path / "child"
        child_dir.mkdir()
        (child_dir / "child.vertex").write_text('name "child"\nstore "./c.db"\nloops { ping { fold { n "inc" } } }\n')
        result = fetch_vertices(tmp_path)
        assert len(result["vertices"]) == 1
        assert result["vertices"][0]["name"] == "child"


class TestFetchVerticesLocal:
    """Tests for fetch_vertices_local — .loops/.vertex path."""

    def test_no_local_vertex_returns_none(self, tmp_path, monkeypatch):
        """fetch_vertices_local returns None when .loops/.vertex doesn't exist (L137)."""
        from loops.commands.vertices import fetch_vertices_local
        monkeypatch.chdir(tmp_path)
        assert fetch_vertices_local() is None

    def test_with_local_vertex_file(self, tmp_path, monkeypatch):
        """fetch_vertices_local walks .loops directory (L135+)."""
        from loops.commands.vertices import fetch_vertices_local
        monkeypatch.chdir(tmp_path)
        loops_dir = tmp_path / ".loops"
        loops_dir.mkdir()
        root_vertex = loops_dir / ".vertex"
        root_vertex.write_text('name "root"\n')
        child = loops_dir / "proj.vertex"
        child.write_text('name "proj"\nloops {\n    m { fold { n "inc" } }\n}\n')
        result = fetch_vertices_local()
        assert result is not None
        assert "vertices" in result


class TestWalkRoot:
    """Tests for _walk_root — discover/combine paths."""

    def test_walk_root_discover(self, tmp_path):
        """_walk_root with discover pattern finds child vertices (L83-94)."""
        from loops.commands.vertices import _walk_root

        # Root vertex with discover pattern
        root = tmp_path / "root.vertex"
        root.write_text('name "root"\ndiscover "*.vertex"\n')
        # Child vertex
        child = tmp_path / "proj.vertex"
        child.write_text('name "proj"\nloops {\n    m { fold { n "inc" } }\n}\n')

        result = _walk_root(root, tmp_path)
        assert any(v["name"] == "proj" for v in result)

    def test_walk_root_no_discover_no_combine(self, tmp_path):
        """_walk_root with no discover/combine → lists all .vertex (L114-125)."""
        from loops.commands.vertices import _walk_root

        root = tmp_path / "root.vertex"
        root.write_text('name "root"\nloops { m { fold { n "inc" } } }\n')
        sibling = tmp_path / "sibling.vertex"
        sibling.write_text('name "sibling"\nloops {\n    m { fold { n "inc" } }\n}\n')

        result = _walk_root(root, tmp_path)
        assert any(v["name"] == "sibling" for v in result)

    def test_walk_root_broken_child(self, tmp_path):
        """_walk_root skips broken .vertex files (L92-93, L123-124)."""
        from loops.commands.vertices import _walk_root

        root = tmp_path / "root.vertex"
        root.write_text('name "root"\ndiscover "*.vertex"\n')
        bad = tmp_path / "bad.vertex"
        bad.write_text("{{invalid")

        result = _walk_root(root, tmp_path)
        # Bad file is skipped, result is empty or has no "bad" entry
        assert all(v.get("name") != "bad" for v in result)

    def test_walk_root_combine(self, tmp_path):
        """_walk_root with combine entries (L99-111)."""
        from loops.commands.vertices import _walk_root

        child_dir = tmp_path / "child"
        child_dir.mkdir()
        child = child_dir / "child.vertex"
        child.write_text('name "child"\nloops {\n    m { fold { n "inc" } }\n}\n')

        root = tmp_path / "root.vertex"
        root.write_text(
            f'name "root"\nloops {{ m {{ fold {{ n "inc" }} }} }}\ncombine {{\n    vertex "./child/child.vertex"\n}}\n'
        )
        result = _walk_root(root, tmp_path)
        assert any(v["name"] == "child" for v in result)

    def test_fetch_vertices_local_broken_child(self, tmp_path, monkeypatch):
        """fetch_vertices_local skips broken .vertex files (L151-152)."""
        from loops.commands.vertices import fetch_vertices_local
        monkeypatch.chdir(tmp_path)
        loops_dir = tmp_path / ".loops"
        loops_dir.mkdir()
        root_vertex = loops_dir / ".vertex"
        root_vertex.write_text('name "root"\nloops { m { fold { n "inc" } } }\n')
        bad = loops_dir / "broken.vertex"
        bad.write_text("{{invalid")
        result = fetch_vertices_local()
        # Should return without error, skipping bad file
        assert result is not None

    def test_walk_root_all_vertex_suffix_filter(self, tmp_path):
        """_walk_root glob all .vertex — L118 never fires since glob filters."""
        from loops.commands.vertices import _walk_root
        root = tmp_path / "root.vertex"
        root.write_text('name "root"\nloops { m { fold { n "inc" } } }\n')
        # Create a non-.vertex file that glob might catch
        (tmp_path / "notes.txt").write_text("notes")
        result = _walk_root(root, tmp_path)
        assert isinstance(result, list)

    def test_walk_root_combine_nonexistent(self, tmp_path, monkeypatch):
        """_walk_root combine entry where vpath doesn't exist (L104)."""
        from loops.commands.vertices import _walk_root
        monkeypatch.setenv("LOOPS_HOME", str(tmp_path / "home"))
        root = tmp_path / "root.vertex"
        root.write_text(
            'name "root"\nloops { m { fold { n "inc" } } }\ncombine {\n    vertex "./nonexistent/x.vertex"\n}\n'
        )
        result = _walk_root(root, tmp_path)
        # Should return empty (nonexistent path skipped)
        assert result == []

    def test_walk_root_combine_duplicate(self, tmp_path, monkeypatch):
        """_walk_root combine with duplicate entry is skipped (L106)."""
        from loops.commands.vertices import _walk_root
        monkeypatch.setenv("LOOPS_HOME", str(tmp_path / "home"))
        child_dir = tmp_path / "child"
        child_dir.mkdir()
        child_vpath = child_dir / "child.vertex"
        child_vpath.write_text(
            'name "child"\nstore "./child.db"\nloops { ping { fold { n "inc" } } }\n'
        )
        root = tmp_path / "root.vertex"
        root.write_text(
            'name "root"\nloops { ping { fold { n "inc" } } }\n'
            f'combine {{\n  vertex "{str(child_vpath)}"\n  vertex "{str(child_vpath)}"\n}}\n'
        )
        result = _walk_root(root, tmp_path)
        assert len(result) == 1  # duplicate skipped

    def test_walk_root_combine_broken_vertex(self, tmp_path, monkeypatch):
        """_walk_root combine entry with broken vertex file (L109-110)."""
        from loops.commands.vertices import _walk_root
        monkeypatch.setenv("LOOPS_HOME", str(tmp_path / "home"))
        child_dir = tmp_path / "bad"
        child_dir.mkdir()
        bad_child = child_dir / "bad.vertex"
        bad_child.write_text("{{invalid")
        root = tmp_path / "root.vertex"
        root.write_text(
            'name "root"\nloops { m { fold { n "inc" } } }\ncombine {\n    vertex "./bad/bad.vertex"\n}\n'
        )
        result = _walk_root(root, tmp_path)
        # Bad vertex is skipped
        assert all(v.get("name") != "bad" for v in result)
