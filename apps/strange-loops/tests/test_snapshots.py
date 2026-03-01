"""Snapshot tests for CLI outputs.

Golden-file pattern adapted from painted's demo tests.
Run with --update-goldens to regenerate snapshot files.
"""

from __future__ import annotations

import difflib
import json
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

import pytest

from atoms import Fact
from engine import SqliteStore

from strange_loops.cli import main

GOLDENS_DIR = Path(__file__).parent / "snapshots"

# Fixed timestamps for deterministic output.
# 2025-01-15 10:00:00 UTC — a Wednesday morning.
_BASE = datetime(2025, 1, 15, 10, 0, 0, tzinfo=timezone.utc).timestamp()
_TS_OFFSETS = {
    "session_start": 0,
    "task_alpha_created": 60,
    "task_alpha_assigned": 120,
    "task_alpha_working": 180,
    "task_alpha_worker_output": 200,
    "task_alpha_worker_complete": 240,
    "task_beta_created": 300,
    "task_beta_assigned": 360,
    "decision_auth": 400,
    "thread_api": 450,
    "plan_next": 500,
}


def _ts(name: str) -> float:
    """Return epoch-seconds timestamp for a named event."""
    return _BASE + _TS_OFFSETS[name]


def _frozen_now() -> datetime:
    """A fixed 'now' for log --since calculations. After all events."""
    return datetime.fromtimestamp(_BASE + 600, tz=timezone.utc)


# -- Golden file infrastructure --


@dataclass
class Golden:
    """Compare rendered text against committed golden files."""

    test_module: str
    test_name: str
    update: bool

    def assert_match(self, text: str, name: str = "output") -> None:
        normalized = "\n".join(line.rstrip() for line in text.splitlines()) + "\n"
        path = GOLDENS_DIR / self.test_module / self.test_name / f"{name}.txt"

        if not path.exists() or self.update:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(normalized)
            if not self.update:
                return  # first run — bootstrap, pass
            return

        expected = path.read_text()
        if normalized != expected:
            diff = difflib.unified_diff(
                expected.splitlines(keepends=True),
                normalized.splitlines(keepends=True),
                fromfile=str(path),
                tofile="actual",
            )
            pytest.fail(f"Golden mismatch for {path}:\n{''.join(diff)}")


@pytest.fixture
def golden(request: pytest.FixtureRequest) -> Golden:
    module = request.node.module.__name__
    # Include class name to avoid collisions (e.g. TestSessionStatus::test_text
    # vs TestProjectStatus::test_text).
    cls = (
        request.node.parent.name
        if request.node.parent and request.node.parent != request.node.module
        else ""
    )
    name = f"{cls}::{request.node.name}" if cls else request.node.name
    update = request.config.getoption("--update-goldens")
    return Golden(test_module=module, test_name=name, update=update)


# -- Fixture data helpers --


def _emit(db: Path, kind: str, obs: str, payload: dict, ts: float) -> None:
    """Emit a fact with a specific timestamp (epoch seconds)."""
    fact = Fact(kind=kind, ts=ts, payload=payload, observer=obs, origin="")
    db.parent.mkdir(parents=True, exist_ok=True)
    with SqliteStore(path=db, serialize=Fact.to_dict, deserialize=Fact.from_dict) as store:
        store.append(fact)


@pytest.fixture
def task_store(tmp_path: Path, monkeypatch) -> Path:
    """Create a task store with deterministic fixture data."""
    ws = tmp_path / "workspace"
    ws.mkdir(exist_ok=True)
    monkeypatch.chdir(ws)

    db = ws / "data" / "tasks.db"

    # Session start
    _emit(db, "session.start", "alice", {}, _ts("session_start"))

    # Task alpha — created → assigned → working → worker complete
    _emit(
        db,
        "task.created",
        "alice",
        {
            "name": "alpha",
            "title": "Implement auth module",
            "base_branch": "main",
            "description": "Add JWT authentication",
        },
        _ts("task_alpha_created"),
    )

    _emit(
        db,
        "task.assigned",
        "alice",
        {
            "name": "alpha",
            "harness": "shell",
            "worktree": "/tmp/worktrees/alpha",
        },
        _ts("task_alpha_assigned"),
    )

    _emit(
        db,
        "task.stage",
        "alice",
        {
            "name": "alpha",
            "status": "working",
        },
        _ts("task_alpha_working"),
    )

    _emit(
        db,
        "worker.output",
        "shell",
        {
            "task": "alpha",
            "output": "running tests...\nall 42 tests passed",
        },
        _ts("task_alpha_worker_output"),
    )

    _emit(
        db,
        "worker.output.complete",
        "shell",
        {
            "task": "alpha",
            "status": "ok",
            "returncode": 0,
        },
        _ts("task_alpha_worker_complete"),
    )

    # Task beta — created → assigned (no worker yet)
    _emit(
        db,
        "task.created",
        "bob",
        {
            "name": "beta",
            "title": "Fix pagination bug",
            "base_branch": "main",
            "description": "",
        },
        _ts("task_beta_created"),
    )

    _emit(
        db,
        "task.assigned",
        "bob",
        {
            "name": "beta",
            "harness": "shell",
            "worktree": "/tmp/worktrees/beta",
        },
        _ts("task_beta_assigned"),
    )

    return db


@pytest.fixture
def project_store(tmp_path: Path, monkeypatch) -> Path:
    """Create a project store with deterministic fixture data."""
    ws = tmp_path / "workspace"
    ws.mkdir(exist_ok=True)

    db = ws / "data" / "project.db"

    _emit(
        db,
        "decision",
        "alice",
        {
            "topic": "auth",
            "message": "Use JWT with refresh tokens",
        },
        _ts("decision_auth"),
    )

    _emit(
        db,
        "thread",
        "bob",
        {
            "name": "api-design",
            "status": "open",
            "message": "REST vs GraphQL for v2",
        },
        _ts("thread_api"),
    )

    _emit(
        db,
        "plan",
        "alice",
        {
            "name": "next-sprint",
            "status": "active",
        },
        _ts("plan_next"),
    )

    monkeypatch.setattr("strange_loops.commands.project._project_store", lambda: db)
    return db


# -- Snapshot tests: Session --


class TestSessionStatus:
    def test_text(self, task_store: Path, golden: Golden, capsys):
        rc = main(["session", "status"])
        assert rc == 0
        golden.assert_match(capsys.readouterr().out)

    def test_json(self, task_store: Path, golden: Golden, capsys):
        rc = main(["session", "status", "--json"])
        assert rc == 0
        out = capsys.readouterr().out
        data = json.loads(out)
        assert "facts" in data
        golden.assert_match(json.dumps(data, indent=2, default=str) + "\n")


class TestSessionLog:
    def test_text(self, task_store: Path, golden: Golden, capsys, monkeypatch):
        _freeze_now(monkeypatch)
        rc = main(["session", "log", "--since", "1h"])
        assert rc == 0
        golden.assert_match(capsys.readouterr().out)

    def test_json(self, task_store: Path, golden: Golden, capsys, monkeypatch):
        _freeze_now(monkeypatch)
        rc = main(["session", "log", "--since", "1h", "--json"])
        assert rc == 0
        out = capsys.readouterr().out.strip()
        lines = [line for line in out.split("\n") if line.strip()]
        for line in lines:
            json.loads(line)
        golden.assert_match("\n".join(lines) + "\n")


# -- Snapshot tests: Task --


class TestTaskStatus:
    def test_single_text(self, task_store: Path, golden: Golden, capsys):
        rc = main(["task", "status", "alpha"])
        assert rc == 0
        golden.assert_match(capsys.readouterr().out)

    def test_single_json(self, task_store: Path, golden: Golden, capsys):
        rc = main(["task", "status", "alpha", "--json"])
        assert rc == 0
        out = capsys.readouterr().out
        data = json.loads(out)
        assert data["name"] == "alpha"
        golden.assert_match(json.dumps(data, indent=2, default=str) + "\n")

    def test_all_text(self, task_store: Path, golden: Golden, capsys):
        rc = main(["task", "status"])
        assert rc == 0
        golden.assert_match(capsys.readouterr().out)

    def test_all_json(self, task_store: Path, golden: Golden, capsys):
        rc = main(["task", "status", "--json"])
        assert rc == 0
        out = capsys.readouterr().out
        data = json.loads(out)
        assert isinstance(data, list)
        golden.assert_match(json.dumps(data, indent=2, default=str) + "\n")


class TestTaskList:
    def test_text(self, task_store: Path, golden: Golden, capsys):
        rc = main(["task", "list"])
        assert rc == 0
        golden.assert_match(capsys.readouterr().out)

    def test_json(self, task_store: Path, golden: Golden, capsys):
        rc = main(["task", "list", "--json"])
        assert rc == 0
        out = capsys.readouterr().out
        data = json.loads(out)
        assert isinstance(data, list)
        golden.assert_match(json.dumps(data, indent=2, default=str) + "\n")


# -- Snapshot tests: Project --


class TestProjectStatus:
    def test_text(self, task_store: Path, project_store: Path, golden: Golden, capsys):
        rc = main(["project", "status"])
        assert rc == 0
        golden.assert_match(capsys.readouterr().out)

    def test_json(self, task_store: Path, project_store: Path, golden: Golden, capsys):
        rc = main(["project", "status", "--json"])
        assert rc == 0
        out = capsys.readouterr().out
        data = json.loads(out)
        assert "decisions" in data
        golden.assert_match(json.dumps(data, indent=2, default=str) + "\n")


class TestProjectLog:
    def test_text(
        self,
        task_store: Path,
        project_store: Path,
        golden: Golden,
        capsys,
        monkeypatch,
    ):
        _freeze_now(monkeypatch)
        rc = main(["project", "log", "--since", "1h"])
        assert rc == 0
        golden.assert_match(capsys.readouterr().out)

    def test_json(
        self,
        task_store: Path,
        project_store: Path,
        golden: Golden,
        capsys,
        monkeypatch,
    ):
        _freeze_now(monkeypatch)
        rc = main(["project", "log", "--since", "1h", "--json"])
        assert rc == 0
        out = capsys.readouterr().out.strip()
        lines = [line for line in out.split("\n") if line.strip()]
        for line in lines:
            json.loads(line)
        golden.assert_match("\n".join(lines) + "\n")


# -- Helpers --


def _freeze_now(monkeypatch) -> None:
    """Monkeypatch datetime.now to return a fixed time for log --since calculations."""
    import strange_loops.commands.session as session_mod
    import strange_loops.commands.project as project_mod

    frozen = _frozen_now()

    class FrozenDatetime(datetime):
        @classmethod
        def now(cls, tz=None):
            return frozen

    monkeypatch.setattr(session_mod, "datetime", FrozenDatetime)
    monkeypatch.setattr(project_mod, "datetime", FrozenDatetime)
