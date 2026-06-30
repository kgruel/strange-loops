"""Local-first resolution for declaration commands — thread:global-local-walk-broken.

The incident these tests pin (2026-06-09): ``sl add project kind X`` wrote to
the GLOBAL ~/.config/loops/project/project.vertex while ``sl read project``
resolved the LOCAL .loops/project.vertex — the kind landed in a file the
verbs never read. Declaration commands must resolve through the same
local-first chain the verbs use (``_resolve_vertex_for_dispatch``).

Every test here uses an isolated cwd (local-first resolution makes cwd part
of the resolution context — see observation:test/cwd-is-resolution-context-now).
"""

from __future__ import annotations

from pathlib import Path

import pytest
from engine.builder import fold_by, vertex
from loops.commands.add import _run_add
from loops.commands.ls import fetch_declarations
from loops.commands.rm import _run_rm

from .helpers import block_text as _text


@pytest.fixture
def shadowed_project(loops_env, monkeypatch) -> tuple[Path, Path]:
    """Same vertex name in both layers: local .loops/ and global home.

    Returns (local_path, global_path). cwd is the tmp workspace (loops_env
    parent), with a .loops/ directory beside it — mirroring a repo checkout.
    """
    workspace = loops_env.parent / "workspace"
    loops_dir = workspace / ".loops"
    loops_dir.mkdir(parents=True)
    local_path = loops_dir / "project.vertex"
    (
        vertex("project")
        .store("./data/project.db")
        .loop("thread", fold_by("name"))
        .loop("decision", fold_by("topic"))
        .write(local_path)
    )

    gdir = loops_env / "project"
    gdir.mkdir(parents=True)
    global_path = gdir / "project.vertex"
    (
        vertex("project")
        .store("./data/project.db")
        .loop("thread", fold_by("name"))
        .write(global_path)
    )

    monkeypatch.chdir(workspace)
    return local_path, global_path


class TestAddResolvesLocalFirst:
    def test_add_kind_writes_local_not_global(self, shadowed_project):
        local_path, global_path = shadowed_project
        before_global = global_path.read_text()

        rc = _run_add(["project", "kind", "observation", "--by", "topic"])

        assert rc == 0
        assert "observation" in local_path.read_text()
        assert global_path.read_text() == before_global  # untouched

    def test_add_falls_back_to_global_without_local(self, loops_env, monkeypatch):
        workspace = loops_env.parent / "bare-workspace"
        workspace.mkdir()
        monkeypatch.chdir(workspace)

        gdir = loops_env / "solo"
        gdir.mkdir(parents=True)
        global_path = gdir / "solo.vertex"
        (
            vertex("solo")
            .store("./data/solo.db")
            .loop("thread", fold_by("name"))
            .write(global_path)
        )

        rc = _run_add(["solo", "kind", "decision", "--by", "topic"])

        assert rc == 0
        assert "decision" in global_path.read_text()


class TestRmResolvesLocalFirst:
    def test_rm_kind_removes_from_local_not_global(self, shadowed_project):
        local_path, global_path = shadowed_project
        before_global = global_path.read_text()

        rc = _run_rm(["project", "kind", "thread"])

        assert rc == 0
        assert "thread" not in local_path.read_text()
        assert global_path.read_text() == before_global  # still has thread


class TestLsResolvesLocalFirst:
    def test_ls_vertex_form_shows_local_kinds(self, shadowed_project):
        local_path, _ = shadowed_project
        # Distinguish the layers: only the local file gets a marker kind.
        _run_add(["project", "kind", "localonly", "--by", "name"])

        data = fetch_declarations("project")

        assert "error" not in data
        assert str(Path(data["vertex_path"]).resolve()) == str(local_path.resolve())


class TestReceiptsShowFullPath:
    def test_add_receipt_prints_full_path(self, shadowed_project, capsys):
        local_path, _ = shadowed_project

        _run_add(["project", "kind", "observation", "--by", "topic"])

        out = capsys.readouterr().out
        # Receipt names the layer, not just the basename.
        assert ".loops" in out


class TestRootLsLocalLayer:
    def test_fetch_vertices_local_discovers_dotloops(self, shadowed_project):
        from loops.commands.vertices import fetch_vertices_local

        found = fetch_vertices_local()

        names = [v["name"] for v in found]
        assert "project" in names
        assert all(v["scope"] == "local" for v in found)

    def test_fetch_vertices_local_empty_without_local(self, loops_env, monkeypatch):
        from loops.commands.vertices import fetch_vertices_local

        workspace = loops_env.parent / "empty-workspace"
        workspace.mkdir()
        monkeypatch.chdir(workspace)

        assert fetch_vertices_local() == []


class TestVerticesLensLocalGroup:
    BASE = {
        "name": "ambient",
        "path": "/x/ambient.vertex",
        "kind": "hybrid",
        "loops": [],
    }
    LOCAL = {
        "name": "project",
        "path": "/y/.loops/project.vertex",
        "kind": "instance",
        "loops": [{"name": "thread", "folds": ["by name"]}],
        "scope": "local",
        "shadows": True,
    }

    def test_no_local_layer_renders_config_as_primary(self):
        from loops.lenses.vertices import vertices_view
        from painted import Zoom

        # Outside a project the config layer IS the primary listing — it gets
        # the "config —" header and its vertices render with stat rows
        # (decision:design/ls-as-stat-over-containment).
        text = _text(vertices_view({"vertices": [self.BASE]}, Zoom.SUMMARY, 80))
        assert "local —" not in text
        assert "config — ~/.config/loops" in text
        assert "ambient" in text

    def test_local_layer_renders_groups_and_shadow_marker(self):
        from loops.lenses.vertices import vertices_view
        from painted import Zoom

        # --all (expand_config) shows both groups in full; the default collapses
        # config to a count-line (tested separately below).
        data = {
            "vertices": [self.BASE],
            "local_vertices": [self.LOCAL],
            "expand_config": True,
        }
        text = _text(vertices_view(data, Zoom.SUMMARY, 80))
        assert "local — cwd, verbs resolve these first" in text
        assert "config — ~/.config/loops" in text
        assert "⊳ shadows" in text
        # Local group renders before config group.
        assert text.index("project") < text.index("ambient")

    def test_config_collapses_to_count_line_by_default(self):
        from loops.lenses.vertices import vertices_view
        from painted import Zoom

        data = {"vertices": [self.BASE], "local_vertices": [self.LOCAL]}
        text = _text(vertices_view(data, Zoom.SUMMARY, 80))
        # Default (no --all): config is a drillable count-line, not full rows.
        assert "sl ls --all" in text
        assert "ambient" not in text

    def test_minimal_zoom_counts_both_layers(self):
        from loops.lenses.vertices import vertices_view
        from painted import Zoom

        data = {"vertices": [self.BASE], "local_vertices": [self.LOCAL]}
        assert "1 local + 1 config" in _text(vertices_view(data, Zoom.MINIMAL, 80))
