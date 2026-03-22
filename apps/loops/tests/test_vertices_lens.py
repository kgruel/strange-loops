"""Tests for vertices lens — all zoom levels."""

from painted import Zoom

from .helpers import block_text as _text


def test_vertices_minimal():
    from loops.lenses.vertices import vertices_view
    data = {"vertices": [{"name": "proj", "kind": "leaf", "loops": []}]}
    assert "1 vertex" in _text(vertices_view(data, Zoom.MINIMAL, 80))

def test_vertices_minimal_plural():
    from loops.lenses.vertices import vertices_view
    data = {"vertices": [{"name": "a", "kind": "leaf"}, {"name": "b", "kind": "leaf"}]}
    assert "2 vertices" in _text(vertices_view(data, Zoom.MINIMAL, 80))

def test_vertices_empty():
    from loops.lenses.vertices import vertices_view
    assert "No vertices" in _text(vertices_view({"vertices": []}, Zoom.SUMMARY, 80))

def test_vertices_summary_leaf():
    from loops.lenses.vertices import vertices_view
    data = {"vertices": [{"name": "proj", "kind": "leaf", "loops": [{"name": "metric", "folds": ["n"]}]}]}
    t = _text(vertices_view(data, Zoom.SUMMARY, 80))
    assert "proj" in t
    assert "metric" in t

def test_vertices_summary_aggregation():
    from loops.lenses.vertices import vertices_view
    data = {"vertices": [{"name": "root", "kind": "aggregation", "loops": [], "combine": ["a", "b"]}]}
    t = _text(vertices_view(data, Zoom.SUMMARY, 80))
    assert "combines 2" in t

def test_vertices_detailed():
    from loops.lenses.vertices import vertices_view
    data = {"vertices": [{"name": "proj", "kind": "leaf", "loops": [{"name": "metric", "folds": ["n", "sum"]}]}]}
    t = _text(vertices_view(data, Zoom.DETAILED, 80))
    assert "n, sum" in t

def test_vertices_full():
    from loops.lenses.vertices import vertices_view
    data = {"vertices": [{"name": "proj", "kind": "leaf", "loops": [],
                           "store": "/data/proj.db", "combine": ["a"], "discover": "*.vertex"}]}
    t = _text(vertices_view(data, Zoom.FULL, 80))
    assert "store:" in t
    assert "combine:" in t
    assert "discover:" in t

def test_vertices_long_line_truncated():
    """Long summary line gets truncated at width (L59)."""
    from loops.lenses.vertices import vertices_view
    data = {"vertices": [{"name": "v", "kind": "leaf",
                           "loops": [{"name": "m" * 40, "folds": ["x"]}]}]}
    block = vertices_view(data, Zoom.SUMMARY, 40)
    t = _text(block)
    # Line should not exceed width
    for line in t.splitlines():
        assert len(line) <= 40

def test_vertices_long_detail_truncated():
    """Long detail line gets truncated (L67)."""
    from loops.lenses.vertices import vertices_view
    data = {"vertices": [{"name": "v", "kind": "leaf",
                           "loops": [{"name": "m", "folds": ["x" * 50]}]}]}
    block = vertices_view(data, Zoom.DETAILED, 40)
    t = _text(block)
    for line in t.splitlines():
        assert len(line) <= 40
