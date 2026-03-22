"""Root conftest — shared pytest fixtures and options for loops app tests."""
from __future__ import annotations

import time
from pathlib import Path

import pytest

from engine.builder import fold_by, fold_collect, fold_count, vertex


# ---------------------------------------------------------------------------
# CLI options
# ---------------------------------------------------------------------------

def pytest_addoption(parser):
    parser.addoption(
        "--update-goldens",
        action="store_true",
        default=False,
        help="Regenerate golden files instead of comparing against them",
    )


# ---------------------------------------------------------------------------
# LOOPS_HOME / environment fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def loops_home(tmp_path, monkeypatch):
    """Isolated LOOPS_HOME directory. Sets LOOPS_HOME env var automatically."""
    home = tmp_path / "loops_home"
    home.mkdir()
    monkeypatch.setenv("LOOPS_HOME", str(home))
    monkeypatch.delenv("LOOPS_OBSERVER", raising=False)
    return home


@pytest.fixture
def loops_env(loops_home, monkeypatch):
    """Fully isolated loops environment: LOOPS_HOME + cwd set to tmp."""
    monkeypatch.chdir(loops_home.parent)
    return loops_home


# ---------------------------------------------------------------------------
# Vertex fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def simple_vertex(loops_home):
    """A minimal vertex with a single fold-count loop and a store."""
    vpath = loops_home / "simple" / "simple.vertex"
    (vertex("simple")
        .store("./data/simple.db")
        .loop("ping", fold_count("n"))
        .write(vpath))
    return vpath


@pytest.fixture
def project_vertex(loops_home):
    """A project-style vertex with thread (fold_by name) and decision (fold_by topic)."""
    vpath = loops_home / "project" / "project.vertex"
    (vertex("project")
        .store("./data/project.db")
        .loop("thread", fold_by("name"))
        .loop("decision", fold_by("topic"))
        .loop("task", fold_by("name"))
        .write(vpath))
    return vpath


@pytest.fixture
def autoresearch_vertex(loops_home):
    """An autoresearch-style vertex with experiment (fold_collect) and log/finding kinds."""
    vpath = loops_home / "autoresearch" / "autoresearch.vertex"
    (vertex("autoresearch")
        .store("./data/autoresearch.db")
        .loop("experiment", fold_collect("items", max_items=1000))
        .loop("log", fold_collect("items", max_items=500))
        .loop("finding", fold_collect("items", max_items=100))
        .loop("config", fold_by("key"))
        .write(vpath))
    return vpath


# ---------------------------------------------------------------------------
# Store fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def populated_store(project_vertex):
    """Project vertex with a few pre-populated facts. Returns (vertex_path, db_path)."""
    from .builders import StorePopulator

    db_path = project_vertex.parent / "data" / "project.db"
    (StorePopulator(db_path)
        .emit("thread", name="cli-work", status="open")
        .emit("thread", name="store-ops", status="open")
        .emit("decision", topic="arch/layering", message="atoms owns data shapes")
        .done())
    return project_vertex, db_path


# ---------------------------------------------------------------------------
# TUI state fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def app_state():
    """A minimal AppState for AutoresearchApp tests (2 experiments, list focus)."""
    from .builders import AppStateBuilder
    return (AppStateBuilder()
        .metric("efficiency", direction="lower")
        .iteration(metric=4.5, status="keep", description="baseline")
        .iteration(metric=3.5, status="keep", delta_pct=-22.2, description="step up")
        .focus("list")
        .build())


@pytest.fixture
def app_state_with_running():
    """AppState with a completed iteration + an in-progress (running) iteration."""
    from .builders import AppStateBuilder
    return (AppStateBuilder()
        .metric("efficiency", direction="lower")
        .iteration(metric=4.5, status="keep", description="baseline")
        .running(description="")
        .focus("list")
        .build())


@pytest.fixture
def store_explorer_state():
    """A minimal StoreExplorerState for StoreExplorerApp tests."""
    from .builders import StoreExplorerStateBuilder
    return (StoreExplorerStateBuilder()
        .ticks(["2024-01-01", "2024-01-02"])
        .with_detail()
        .focus("list")
        .build())


@pytest.fixture
def store_explorer_state_with_fidelity():
    """StoreExplorerState with a fidelity drill active."""
    from .builders import StoreExplorerStateBuilder, make_fidelity_facts
    return (StoreExplorerStateBuilder()
        .ticks(["2024-01-01"])
        .with_fidelity(make_fidelity_facts(["thread", "decision", "thread"]))
        .build())


# ---------------------------------------------------------------------------
# FoldState fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def autoresearch_fold_state():
    """FoldState representing two autoresearch experiments + a running log."""
    from .builders import FoldStateBuilder
    return (FoldStateBuilder("autoresearch")
        .config(primary_metric="efficiency", direction="lower")
        .experiment(efficiency=4.5, status="keep", commit="abc1234",
                    description="baseline", ts=200.0)
        .experiment(efficiency=3.5, status="keep", commit="def5678",
                    description="step up", ts=300.0)
        .log(type="note", message="mid experiment", ts=250.0)
        .log(type="note", message="in progress", ts=400.0)
        .build())
