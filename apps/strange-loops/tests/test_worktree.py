"""Tests for git worktree operations."""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from strange_loops import worktree


@pytest.fixture
def git_repo(tmp_path: Path) -> Path:
    """Create a minimal git repo with an initial commit."""
    repo = tmp_path / "repo"
    repo.mkdir()
    subprocess.run(["git", "init"], cwd=repo, check=True, capture_output=True)
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


class TestCreate:
    def test_creates_worktree(self, git_repo: Path):
        wt_path = worktree.create(git_repo, "feature-a", "main")
        assert wt_path.exists()
        assert (wt_path / "README.md").exists()

    def test_creates_branch(self, git_repo: Path):
        worktree.create(git_repo, "feature-b", "main")
        result = subprocess.run(
            ["git", "branch", "--list", "feature-b"],
            cwd=git_repo,
            capture_output=True,
            text=True,
        )
        assert "feature-b" in result.stdout


class TestExists:
    def test_exists_true(self, git_repo: Path):
        worktree.create(git_repo, "feature-c", "main")
        assert worktree.exists(git_repo, "feature-c")

    def test_exists_false(self, git_repo: Path):
        assert not worktree.exists(git_repo, "nonexistent")


class TestRemove:
    def test_remove_worktree(self, git_repo: Path):
        wt_path = worktree.create(git_repo, "feature-d", "main")
        assert wt_path.exists()
        worktree.remove(git_repo, "feature-d")
        assert not wt_path.exists()


class TestListWorktrees:
    def test_lists_main_and_created(self, git_repo: Path):
        worktree.create(git_repo, "feature-e", "main")
        wts = worktree.list_worktrees(git_repo)
        paths = [wt["worktree"] for wt in wts]
        assert any("feature-e" in p for p in paths)


class TestDiffStat:
    def test_shows_diff(self, git_repo: Path):
        wt_path = worktree.create(git_repo, "feature-f", "main")
        (wt_path / "new_file.txt").write_text("hello\n")
        subprocess.run(["git", "add", "."], cwd=wt_path, check=True, capture_output=True)
        stat = worktree.diff_stat(wt_path)
        # Staged changes show in diff --stat --cached, not diff --stat
        # But unstaged new file won't show either. Let's modify an existing file.
        (wt_path / "README.md").write_text("# Modified\n")
        stat = worktree.diff_stat(wt_path)
        assert "README.md" in stat


class TestCurrentBranch:
    def test_returns_branch_name(self, git_repo: Path):
        branch = worktree.current_branch(git_repo)
        assert branch == "main"
