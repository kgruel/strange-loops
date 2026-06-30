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


# --- line-row redesign (rendering/ls-root-line-row) ---------------------------

def _instance(name, facts, kinds, *, mtime=1.75e9, lead=("a", "b", "c"),
              shadows=False, shadows_path=None):
    return {
        "name": name, "kind": "instance", "facts": facts, "kind_count": kinds,
        "mtime": mtime, "loops": [],
        "kind_stats": [{"kind": k, "count": facts // (i + 1)}
                       for i, k in enumerate(lead)],
        "shadows": shadows, "shadows_path": shadows_path,
    }


def test_lead_kinds_preview_is_top_by_count():
    """The ⊃ preview is the top kinds by count (the 'what's inside' glance)."""
    from loops.lenses.vertices import vertices_view
    v = _instance("p", 100, 5, lead=("alpha", "beta", "gamma"))
    t = _text(vertices_view({"local_vertices": [v], "vertices": []}, Zoom.SUMMARY, 100))
    assert "⊃ alpha · beta · gamma" in t


def test_piped_detailed_width_none_does_not_crash():
    """Regression: `sl ls -v`/-vv piped (width None) must not crash on the
    per-kind census or the shadow sub-line (Line.to_block(None) / elide(None))."""
    from loops.lenses.vertices import vertices_view
    v = _instance("p", 50, 3, lead=("alpha", "beta", "gamma"),
                  shadows=True, shadows_path="/home/u/.config/loops/p/p.vertex")
    block = vertices_view({"local_vertices": [v], "vertices": []},
                          Zoom.FULL, None, piped=True)
    t = _text(block)
    assert "alpha" in t and "⊳ shadows" in t  # census + shadow line both rendered


def test_piped_register_is_information_faithful():
    """Piped output is never truncated to a terminal edge — even when a width
    is passed (e.g. COLUMNS-inherited pipe), the full ⊃ preview survives."""
    from loops.lenses.vertices import vertices_view
    v = _instance("project", 2800, 21, lead=("decision", "thread", "session"))
    # width 80 would have clipped the preview before the faithfulness fix.
    t = _text(vertices_view({"local_vertices": [v], "vertices": []},
                            Zoom.SUMMARY, 80, piped=True))
    assert "⊃ decision · thread · session" in t  # full, no ellipsis
    assert "…" not in t


def test_shadow_renders_second_line_with_path():
    """The shadow marker is a clarifying sub-line naming the overridden path."""
    from loops.lenses.vertices import vertices_view
    v = _instance("project", 10, 2, shadows=True,
                  shadows_path="/home/u/.config/loops/project/project.vertex")
    data = {"local_vertices": [v], "vertices": [{"name": "project", "kind": "instance"}],
            "expand_config": False}
    t = _text(vertices_view(data, Zoom.SUMMARY, 100))
    assert "⊳ shadows" in t
    assert "/.config/loops/project/project.vertex" in t


def test_detailed_kind_census_shows_count_and_fold():
    """`-v` expands into the per-kind census: kind name + live count + fold op."""
    from loops.lenses.vertices import vertices_view
    v = {
        "name": "p", "kind": "instance", "facts": 90, "kind_count": 2,
        "mtime": 1.75e9, "loops": [{"name": "decision", "folds": ["items by topic"]}],
        "kind_stats": [{"kind": "decision", "count": 60}, {"kind": "tick", "count": 30}],
    }
    t = _text(vertices_view({"local_vertices": [v], "vertices": []}, Zoom.DETAILED, 100))
    assert "decision" in t and "60" in t and "items by topic" in t
    assert "tick" in t and "30" in t  # undeclared kind shown with no fold op


def test_all_columns_align_across_groups():
    """Regression (cross-group): under --all the ⊃ preview column lands at the
    same offset in the local and config sections (shared column widths)."""
    from loops.lenses.vertices import vertices_view
    local = [_instance("small", 5, 2, lead=("x", "y", "z"))]
    config = [_instance("biggervertex", 99000, 30, lead=("p", "q", "r"))]
    data = {"local_vertices": local, "vertices": config, "expand_config": True}
    t = _text(vertices_view(data, Zoom.SUMMARY, 120))
    offsets = [line.index("⊃") for line in t.splitlines() if "⊃" in line]
    assert len(offsets) == 2  # one local row, one config row
    assert offsets[0] == offsets[1]  # aligned across the section boundary
