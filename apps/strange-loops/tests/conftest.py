"""Shared test fixtures for strange-loops."""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest


def pytest_addoption(parser):
    parser.addoption(
        "--update-goldens",
        action="store_true",
        default=False,
        help="Regenerate golden files instead of comparing against them",
    )


@pytest.fixture
def home(tmp_path: Path) -> Path:
    """Isolated LOOPS_HOME directory."""
    h = tmp_path / "home"
    h.mkdir()
    return h


@pytest.fixture
def workspace(tmp_path: Path, monkeypatch) -> Path:
    """Isolated workspace with vertex files for testing.

    Copies real vertex declarations so store paths resolve to ws/data/*.db.
    Patches lifecycle module so all vertex reads go through the temp files.
    """
    ws = tmp_path / "workspace"
    ws.mkdir()

    from strange_loops.lifecycle import _PKG_ROOT

    for name in ("tasks", "project"):
        real = _PKG_ROOT / "loops" / f"{name}.vertex"
        if real.exists():
            (ws / f"{name}.vertex").write_text(real.read_text())

    monkeypatch.setattr("strange_loops.lifecycle._TASKS_VERTEX", ws / "tasks.vertex")
    monkeypatch.setattr("strange_loops.lifecycle._PROJECT_VERTEX", ws / "project.vertex")
    return ws


@pytest.fixture
def git_repo(tmp_path: Path) -> Path:
    """Create a minimal git repo with an initial commit."""
    repo = tmp_path / "repo"
    repo.mkdir()
    subprocess.run(["git", "init", "-b", "main"], cwd=repo, check=True, capture_output=True)
    subprocess.run(
        ["git", "config", "user.email", "test@test.com"],
        cwd=repo,
        check=True,
        capture_output=True,
    )
    subprocess.run(
        ["git", "config", "user.name", "Test"],
        cwd=repo,
        check=True,
        capture_output=True,
    )
    (repo / "README.md").write_text("# Test\n")
    subprocess.run(["git", "add", "."], cwd=repo, check=True, capture_output=True)
    subprocess.run(
        ["git", "commit", "-m", "init"],
        cwd=repo,
        check=True,
        capture_output=True,
    )
    return repo
