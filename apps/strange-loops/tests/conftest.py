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
def workspace(tmp_path: Path) -> Path:
    """Isolated workspace directory (simulates a git worktree root)."""
    ws = tmp_path / "workspace"
    ws.mkdir()
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
