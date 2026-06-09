"""Tests for `loops rm <vertex> {kind,observer,combine,row}` — Phase 3.

Refusal cases are written FIRST per the asymmetric-pair discipline named in
observation:pattern/asymmetric-pair-test-fired-again. Happy-path tests
follow, then sequential mutations + change-fact symmetry with add.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from engine.builder import fold_by, fold_collect, vertex
from lang import parse_vertex_file
from loops.commands.add import _run_add
from loops.commands.rm import _run_rm


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def project_with_change(loops_env) -> Path:
    """Project with change kind defined — qualifies for change-fact emission."""
    vdir = loops_env / "project"
    vdir.mkdir(parents=True, exist_ok=True)
    vpath = vdir / "project.vertex"
    (
        vertex("project")
        .store("./data/project.db")
        .loop("thread", fold_by("name"))
        .loop("decision", fold_by("topic"))
        .loop("task", fold_by("name"))
        .loop("change", fold_collect("items", max_items=20))
        .write(vpath)
    )
    return vpath


@pytest.fixture
def aggregation_vertex(loops_env) -> Path:
    """Combine-style aggregation vertex (no store)."""
    vdir = loops_env / "root"
    vdir.mkdir(parents=True, exist_ok=True)
    vpath = vdir / "root.vertex"
    (
        vertex("root")
        .loop("thread", fold_by("name"))
        .write(vpath)
    )
    # Add a couple of combine entries directly via add.
    _run_add(["root", "combine", "./child-a.vertex"])
    _run_add(["root", "combine", "./child-b.vertex", "--as", "b"])
    return vpath


@pytest.fixture
def project_with_observers(loops_env) -> Path:
    """Project with observers pre-declared."""
    vdir = loops_env / "project"
    vdir.mkdir(parents=True, exist_ok=True)
    vpath = vdir / "project.vertex"
    (
        vertex("project")
        .store("./data/project.db")
        .loop("thread", fold_by("name"))
        .loop("change", fold_collect("items", max_items=20))
        .write(vpath)
    )
    _run_add(["project", "observer", "kyle"])
    _run_add(
        [
            "project", "observer", "alcove",
            "--identity", "alcove-id",
            "--grant", "thread",
        ]
    )
    return vpath


# ---------------------------------------------------------------------------
# REFUSAL CASES — written before happy paths
# ---------------------------------------------------------------------------


class TestRmRefusals:
    def test_missing_vertex_target(self, capsys):
        rc = _run_rm([])
        assert rc != 0
        assert "missing vertex target" in capsys.readouterr().err

    def test_nonexistent_vertex(self, loops_env, capsys):
        rc = _run_rm(["nonexistent", "kind", "decision"])
        assert rc != 0
        assert "not found" in capsys.readouterr().err

    def test_rm_kind_not_present_preserves_file(
        self, project_with_change, capsys
    ):
        original = project_with_change.read_text()
        rc = _run_rm(["project", "kind", "nonexistent"])
        assert rc != 0
        err = capsys.readouterr().err
        assert "not found" in err
        # Byte-identical: refusal leaves file unchanged.
        assert project_with_change.read_text() == original

    def test_rm_observer_when_no_observers_block(
        self, project_with_change, capsys
    ):
        original = project_with_change.read_text()
        rc = _run_rm(["project", "observer", "kyle"])
        assert rc != 0
        err = capsys.readouterr().err
        assert "no observers block" in err
        assert project_with_change.read_text() == original

    def test_rm_combine_when_no_combine_block(
        self, project_with_change, capsys
    ):
        original = project_with_change.read_text()
        rc = _run_rm(["project", "combine", "./x.vertex"])
        assert rc != 0
        assert "no combine block" in capsys.readouterr().err
        assert project_with_change.read_text() == original

    def test_rm_observer_not_present_preserves_file(
        self, project_with_observers, capsys
    ):
        original = project_with_observers.read_text()
        rc = _run_rm(["project", "observer", "ghost"])
        assert rc != 0
        assert "not found" in capsys.readouterr().err
        assert project_with_observers.read_text() == original

    def test_rm_combine_not_present_preserves_file(
        self, aggregation_vertex, capsys
    ):
        original = aggregation_vertex.read_text()
        rc = _run_rm(["root", "combine", "./ghost.vertex"])
        assert rc != 0
        assert "not found" in capsys.readouterr().err
        assert aggregation_vertex.read_text() == original

    def test_rm_row_missing_key(self, capsys):
        rc = _run_rm(["project", "row"])
        assert rc != 0
        assert "missing key" in capsys.readouterr().err

    def test_rm_row_no_list_file(self, loops_env, capsys):
        """No template / no .list file — refuses gracefully."""
        # Use a vertex that has no template at all.
        vdir = loops_env / "proj"
        vdir.mkdir(parents=True, exist_ok=True)
        vpath = vdir / "proj.vertex"
        (vertex("proj").loop("t", fold_by("name")).write(vpath))
        rc = _run_rm(["proj", "row", "key"])
        assert rc != 0
        err = capsys.readouterr().err
        # Could be "has no template sources" or similar — just assert error.
        assert err


# ---------------------------------------------------------------------------
# Happy paths
# ---------------------------------------------------------------------------


class TestRmKind:
    def test_rm_kind(self, project_with_change):
        rc = _run_rm(["project", "kind", "task"])
        assert rc == 0
        vf = parse_vertex_file(project_with_change)
        assert "task" not in vf.loops
        assert "thread" in vf.loops
        assert "decision" in vf.loops
        assert "change" in vf.loops


class TestRmObserver:
    def test_rm_observer_bare(self, project_with_observers):
        rc = _run_rm(["project", "observer", "kyle"])
        assert rc == 0
        vf = parse_vertex_file(project_with_observers)
        names = {o.name for o in (vf.observers or ())}
        assert "kyle" not in names
        assert "alcove" in names

    def test_rm_observer_with_identity_and_grant(
        self, project_with_observers
    ):
        rc = _run_rm(["project", "observer", "alcove"])
        assert rc == 0
        vf = parse_vertex_file(project_with_observers)
        names = {o.name for o in (vf.observers or ())}
        assert "alcove" not in names
        assert "kyle" in names


class TestRmCombine:
    def test_rm_combine(self, aggregation_vertex):
        rc = _run_rm(["root", "combine", "./child-a.vertex"])
        assert rc == 0
        vf = parse_vertex_file(aggregation_vertex)
        names = {e.name for e in (vf.combine or ())}
        assert "./child-a.vertex" not in names
        assert "./child-b.vertex" in names

    def test_rm_combine_with_alias(self, aggregation_vertex):
        """Removing by path works even when entry has an alias."""
        rc = _run_rm(["root", "combine", "./child-b.vertex"])
        assert rc == 0
        vf = parse_vertex_file(aggregation_vertex)
        names = {e.name for e in (vf.combine or ())}
        assert "./child-b.vertex" not in names


# ---------------------------------------------------------------------------
# Change-fact emission symmetry with add
# ---------------------------------------------------------------------------


class TestChangeFactSymmetry:
    def test_rm_kind_emits_change(self, project_with_change):
        from engine import StoreReader

        rc = _run_rm(["project", "kind", "task"])
        assert rc == 0
        store_path = project_with_change.parent / "data" / "project.db"
        reader = StoreReader(store_path)
        changes = reader.recent_facts("change", 50)
        rms = [c for c in changes if c["payload"].get("op") == "rm"]
        assert len(rms) == 1
        c = rms[0]
        assert c["payload"]["target"] == "kind"
        assert c["payload"]["name"] == "task"

    def test_rm_observer_emits_change(self, project_with_observers):
        from engine import StoreReader

        rc = _run_rm(["project", "observer", "kyle"])
        assert rc == 0
        store_path = project_with_observers.parent / "data" / "project.db"
        reader = StoreReader(store_path)
        changes = reader.recent_facts("change", 50)
        rms = [c for c in changes if c["payload"].get("op") == "rm"]
        assert len(rms) == 1
        c = rms[0]
        assert c["payload"]["target"] == "observer"
        assert c["payload"]["name"] == "kyle"

    def test_rm_combine_no_change_fact_aggregation(self, aggregation_vertex):
        """Aggregation vertices have no store — combine rm is quiet by design."""
        rc = _run_rm(["root", "combine", "./child-a.vertex"])
        assert rc == 0
        store_path = aggregation_vertex.parent / "data" / "root.db"
        assert not store_path.exists()


# ---------------------------------------------------------------------------
# Add → rm round-trip (sanity check on the inverse-pair semantics)
# ---------------------------------------------------------------------------


class TestAddRmRoundTrip:
    def test_add_then_rm_restores_kinds(self, project_with_change):
        before = project_with_change.read_text()
        rc = _run_add(["project", "kind", "ping", "--count"])
        assert rc == 0
        rc = _run_rm(["project", "kind", "ping"])
        assert rc == 0
        after = project_with_change.read_text()
        # Round-trip should be byte-identical via the splice library.
        assert after == before

    def test_add_then_rm_observer_with_full_decl(self, project_with_change):
        """add observer + rm observer = byte-identical (parent block stripped)."""
        before = project_with_change.read_text()
        _run_add(
            [
                "project", "observer", "peer",
                "--identity", "peer-id",
                "--grant", "thread,decision",
            ]
        )
        rc = _run_rm(["project", "observer", "peer"])
        assert rc == 0
        # Empty observers block was stripped during rm — round-trip is
        # byte-identical (symmetric with add's auto-create).
        assert project_with_change.read_text() == before

    def test_rm_last_observer_strips_block(self, project_with_change):
        """Removing the last observer auto-strips the observers block."""
        _run_add(["project", "observer", "kyle"])
        assert "observers {" in project_with_change.read_text()
        rc = _run_rm(["project", "observer", "kyle"])
        assert rc == 0
        # Block gone — validator would have rejected an empty observers {}.
        assert "observers {" not in project_with_change.read_text()
        # Parses cleanly.
        vf = parse_vertex_file(project_with_change)
        assert vf.observers is None or len(vf.observers) == 0

    def test_rm_last_combine_strips_block(self, aggregation_vertex):
        """Removing the last combine entry auto-strips the combine block."""
        _run_rm(["root", "combine", "./child-a.vertex"])
        _run_rm(["root", "combine", "./child-b.vertex"])
        # Combine block must be gone — validator would reject empty combine
        # OR a combine-less vertex with no loops is invalid; either way the
        # file must remain parseable.
        text = aggregation_vertex.read_text()
        assert "combine {" not in text
        parse_vertex_file(aggregation_vertex)  # raises on failure
