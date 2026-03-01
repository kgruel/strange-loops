"""Shared test fixtures for strange-loops."""

from __future__ import annotations

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
