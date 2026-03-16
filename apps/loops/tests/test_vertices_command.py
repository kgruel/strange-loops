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
