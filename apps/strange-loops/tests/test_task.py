"""Tests for task commands."""

from __future__ import annotations

import json
import subprocess
import time
from pathlib import Path

import pytest
from atoms import Fact
from engine import SqliteStore

from strange_loops.cli import main


def _read_all(db_path: Path) -> list[dict]:
    with SqliteStore(path=db_path, serialize=Fact.to_dict, deserialize=Fact.from_dict) as store:
        return [Fact.to_dict(f) for f in store.since(0)]


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


class TestTaskCreate:
    def test_emits_fact(self, workspace: Path, monkeypatch):
        monkeypatch.chdir(workspace)
        # Init session first so store exists for later queries
        rc = main(["task", "create", "build-api", "--title", "Build the API", "--base", "main"])
        assert rc == 0

        db = workspace / "data" / "tasks.db"
        assert db.exists()

        facts = _read_all(db)
        assert len(facts) == 1
        assert facts[0]["kind"] == "task.created"
        assert facts[0]["payload"]["name"] == "build-api"
        assert facts[0]["payload"]["title"] == "Build the API"
        assert facts[0]["payload"]["base_branch"] == "main"

    def test_idempotent(self, workspace: Path, monkeypatch):
        monkeypatch.chdir(workspace)
        main(["task", "create", "build-api", "--base", "main"])
        main(["task", "create", "build-api", "--base", "main"])

        facts = _read_all(workspace / "data" / "tasks.db")
        assert len(facts) == 2
        assert all(f["kind"] == "task.created" for f in facts)

    def test_observer_flag(self, workspace: Path, monkeypatch):
        monkeypatch.chdir(workspace)
        main(["task", "create", "build-api", "--base", "main", "--observer", "alice"])

        facts = _read_all(workspace / "data" / "tasks.db")
        assert facts[0]["observer"] == "alice"


class TestTaskAssign:
    def test_creates_worktree(self, git_repo: Path, monkeypatch):
        monkeypatch.chdir(git_repo)
        main(["task", "create", "feature-x", "--base", "main"])
        rc = main(["task", "assign", "feature-x"])
        assert rc == 0

        wt_path = git_repo / ".worktrees" / "feature-x"
        assert wt_path.exists()

        facts = _read_all(git_repo / "data" / "tasks.db")
        assigned = [f for f in facts if f["kind"] == "task.assigned"]
        assert len(assigned) == 1
        assert assigned[0]["payload"]["name"] == "feature-x"
        assert assigned[0]["payload"]["harness"] == "shell"

    def test_errors_without_create(self, git_repo: Path, monkeypatch, capsys):
        monkeypatch.chdir(git_repo)
        # Need a store to exist
        main(["session", "start"])
        capsys.readouterr()

        rc = main(["task", "assign", "nonexistent"])
        assert rc == 1
        assert "not found" in capsys.readouterr().err


class TestTaskSend:
    def test_spawns_worker(self, git_repo: Path, monkeypatch, capsys):
        monkeypatch.chdir(git_repo)
        main(["task", "create", "feature-y", "--base", "main"])
        main(["task", "assign", "feature-y"])
        capsys.readouterr()

        rc = main(["task", "send", "feature-y", "echo hello"])
        assert rc == 0

        out = capsys.readouterr().out
        assert "pid" in out.lower()

        # Wait for worker to finish
        db = git_repo / "data" / "tasks.db"
        for _ in range(50):
            time.sleep(0.1)
            facts = _read_all(db)
            if any(f["kind"] == "worker.output.complete" for f in facts):
                break

        facts = _read_all(db)
        assert any(f["kind"] == "worker.output.complete" for f in facts)
        assert any(f["kind"] == "task.stage" for f in facts)

    def test_errors_without_assign(self, git_repo: Path, monkeypatch, capsys):
        monkeypatch.chdir(git_repo)
        main(["task", "create", "feature-z", "--base", "main"])
        capsys.readouterr()

        rc = main(["task", "send", "feature-z", "echo hello"])
        assert rc == 1
        assert "not assigned" in capsys.readouterr().err.lower()


class TestTaskStatus:
    def test_shows_task(self, git_repo: Path, monkeypatch, capsys):
        monkeypatch.chdir(git_repo)
        main(["task", "create", "feature-s", "--base", "main", "--title", "Status test"])
        capsys.readouterr()

        rc = main(["task", "status", "feature-s"])
        assert rc == 0
        out = capsys.readouterr().out
        assert "feature-s" in out

    def test_json_output(self, git_repo: Path, monkeypatch, capsys):
        monkeypatch.chdir(git_repo)
        main(["task", "create", "feature-j", "--base", "main"])
        capsys.readouterr()

        rc = main(["task", "status", "feature-j", "--json"])
        assert rc == 0

        out = capsys.readouterr().out
        data = json.loads(out)
        assert data["name"] == "feature-j"
        assert data["status"] == "created"

    def test_errors_without_store(self, workspace: Path, monkeypatch, capsys):
        monkeypatch.chdir(workspace)
        rc = main(["task", "status"])
        assert rc == 1
        assert "No session initialized" in capsys.readouterr().err


class TestTaskList:
    def test_shows_all_tasks(self, git_repo: Path, monkeypatch, capsys):
        monkeypatch.chdir(git_repo)
        main(["task", "create", "task-a", "--base", "main"])
        main(["task", "create", "task-b", "--base", "main"])
        capsys.readouterr()

        rc = main(["task", "list"])
        assert rc == 0
        out = capsys.readouterr().out
        assert "task-a" in out
        assert "task-b" in out

    def test_json_output(self, git_repo: Path, monkeypatch, capsys):
        monkeypatch.chdir(git_repo)
        main(["task", "create", "task-c", "--base", "main"])
        capsys.readouterr()

        rc = main(["task", "list", "--json"])
        assert rc == 0

        out = capsys.readouterr().out
        data = json.loads(out)
        assert isinstance(data, list)
        assert len(data) >= 1


class TestTaskClose:
    def test_closes_task(self, git_repo: Path, monkeypatch, capsys):
        monkeypatch.chdir(git_repo)
        main(["task", "create", "feature-close", "--base", "main"])
        main(["task", "assign", "feature-close"])
        capsys.readouterr()

        rc = main(["task", "close", "feature-close"])
        assert rc == 0

        facts = _read_all(git_repo / "data" / "tasks.db")
        stage_facts = [f for f in facts if f["kind"] == "task.stage"]
        assert any(f["payload"]["status"] == "closed" for f in stage_facts)

    def test_errors_without_task(self, git_repo: Path, monkeypatch, capsys):
        monkeypatch.chdir(git_repo)
        main(["session", "start"])
        capsys.readouterr()

        rc = main(["task", "close", "nonexistent"])
        assert rc == 1
        assert "not found" in capsys.readouterr().err.lower()
