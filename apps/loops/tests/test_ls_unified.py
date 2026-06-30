"""Tests for unified `loops ls <vertex>` — Phase 3."""

from __future__ import annotations

from pathlib import Path

import pytest
from engine.builder import fold_by, fold_collect, vertex
from loops.commands.add import _run_add
from loops.commands.ls import fetch_declarations

from .helpers import block_text


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def rich_vertex(loops_home) -> Path:
    """Vertex with kinds + observers + (no combine, no populations)."""
    vdir = loops_home / "proj"
    vdir.mkdir(parents=True, exist_ok=True)
    vpath = vdir / "proj.vertex"
    (
        vertex("proj")
        .store("./data/proj.db")
        .loop("decision", fold_by("topic"))
        .loop("thread", fold_by("name"))
        .loop("change", fold_collect("items", max_items=20))
        .write(vpath)
    )
    _run_add(["proj", "observer", "kyle"])
    _run_add(
        [
            "proj", "observer", "alcove",
            "--identity", "alcove-id",
            "--grant", "decision,thread",
        ]
    )
    return vpath


@pytest.fixture
def aggregation_vertex(loops_home) -> Path:
    """Combine vertex (no store)."""
    vdir = loops_home / "root"
    vdir.mkdir(parents=True, exist_ok=True)
    vpath = vdir / "root.vertex"
    (vertex("root").loop("dummy", fold_by("name")).write(vpath))
    _run_add(["root", "combine", "./a.vertex"])
    _run_add(["root", "combine", "./b.vertex", "--as", "alias-b"])
    return vpath


# ---------------------------------------------------------------------------
# fetch_declarations — data shape
# ---------------------------------------------------------------------------


class TestFetchDeclarations:
    def test_fetch_returns_all_sections(self, rich_vertex):
        data = fetch_declarations("proj")
        assert data["vertex_name"] == "proj"
        kind_names = {k["name"] for k in data["kinds"]}
        assert {"decision", "thread", "change"} <= kind_names
        obs_names = {o["name"] for o in data["observers"]}
        assert obs_names == {"kyle", "alcove"}
        assert data["combine"] == []
        assert data["sources"] == []

    def test_fetch_includes_fold_op_details(self, rich_vertex):
        data = fetch_declarations("proj")
        by_name = {k["name"]: k for k in data["kinds"]}
        assert by_name["decision"]["fold_op"] == 'by "topic"'
        assert by_name["thread"]["fold_op"] == 'by "name"'
        assert by_name["change"]["fold_op"] == "collect 20"

    def test_fetch_includes_observer_grant(self, rich_vertex):
        data = fetch_declarations("proj")
        alcove = next(o for o in data["observers"] if o["name"] == "alcove")
        assert alcove["identity"] == "alcove-id"
        assert set(alcove["grants"]) == {"decision", "thread"}

    def test_fetch_combine_with_alias(self, aggregation_vertex):
        data = fetch_declarations("root")
        by_path = {e["path"]: e for e in data["combine"]}
        assert "./a.vertex" in by_path
        assert "./b.vertex" in by_path
        assert by_path["./b.vertex"]["alias"] == "alias-b"
        assert "alias" not in by_path["./a.vertex"]

    def test_fetch_nonexistent_vertex_returns_error(self, loops_home):
        data = fetch_declarations("nonexistent")
        assert "error" in data
        assert "not found" in data["error"]

    def test_fetch_with_filter(self, rich_vertex):
        data = fetch_declarations("proj", filter_="kind")
        # Filter doesn't drop other data — it's a hint for the lens.
        assert data["filter"] == "kind"
        assert data["kinds"]
        # Other sections still computed; lens decides visibility.


# ---------------------------------------------------------------------------
# Lens rendering at zoom levels
# ---------------------------------------------------------------------------


class TestDeclarationsLens:
    def test_minimal_zoom_one_liner(self, rich_vertex):
        from painted import Zoom

        from loops.lenses.declarations import declarations_view

        data = fetch_declarations("proj")
        block = declarations_view(data, Zoom.MINIMAL, 80)
        text = block_text(block).strip()
        # MINIMAL (stat-over-containment): vertex name + kind count on one line.
        assert "proj" in text
        assert "3 kinds" in text

    def test_summary_leads_with_stat_header_and_kinds(self, rich_vertex):
        from painted import Zoom

        from loops.lenses.declarations import declarations_view

        data = fetch_declarations("proj")
        text = block_text(declarations_view(data, Zoom.SUMMARY, 80))
        # Default view leads with the vertex stat header (type) and lists the
        # KINDS as containment entries — observers fold into a count subline,
        # not a top-level section head.
        assert "instance" in text
        assert "2 observers" in text
        assert "decision" in text
        # The declaration sections do NOT render as heads at SUMMARY anymore.
        assert "OBSERVERS" not in text
        assert "COMBINE" not in text

    def test_detailed_shows_observer_details(self, rich_vertex):
        from painted import Zoom

        from loops.lenses.declarations import declarations_view

        data = fetch_declarations("proj")
        text = block_text(declarations_view(data, Zoom.DETAILED, 120))
        assert "identity=alcove-id" in text
        assert "grants=" in text

    def test_filter_narrows_to_one_section(self, rich_vertex):
        from painted import Zoom

        from loops.lenses.declarations import declarations_view

        data = fetch_declarations("proj", filter_="kind")
        # Section-header text is the terse (piped) register contract.
        text = block_text(declarations_view(data, Zoom.SUMMARY, 80, piped=True))
        # Only KINDS section visible.
        assert "KINDS" in text
        assert "OBSERVERS" not in text
        assert "COMBINE" not in text

    def test_error_renders_inline(self, loops_home):
        from painted import Zoom

        from loops.lenses.declarations import declarations_view

        data = fetch_declarations("nonexistent")
        text = block_text(declarations_view(data, Zoom.SUMMARY, 80))
        assert "Error" in text
        assert "not found" in text

    def test_empty_sections_fold_away(self, rich_vertex):
        from painted import Zoom

        from loops.lenses.declarations import declarations_view

        data = fetch_declarations("proj")
        text = block_text(declarations_view(data, Zoom.SUMMARY, 80))
        # Combine and sources are empty — they no longer render as section
        # heads; the header subline simply omits them (stat-over-containment).
        assert "COMBINE" not in text
        assert "SOURCES" not in text
        assert "combine" not in text.lower()
