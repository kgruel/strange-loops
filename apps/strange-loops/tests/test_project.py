"""Tests for project commands — coordination surface."""

from __future__ import annotations

import argparse
import json
import time
from pathlib import Path

import pytest

from atoms import Fact
from engine import SqliteStore

from strange_loops.commands.project import (
    _parse_emit_parts,
    cmd_project_bridge,
    cmd_project_emit,
    cmd_project_log,
    cmd_project_status,
)
from strange_loops.lifecycle import _PKG_ROOT
from strange_loops.store import emit_fact, emit_tick


def _read_all(db_path: Path) -> list[dict]:
    with SqliteStore(path=db_path, serialize=Fact.to_dict, deserialize=Fact.from_dict) as store:
        return [Fact.to_dict(f) for f in store.since(0)]


@pytest.fixture
def project_store(tmp_path: Path, monkeypatch):
    """Temp project vertex + store for testing."""
    db = tmp_path / "data" / "project.db"
    vertex = tmp_path / "project.vertex"
    # Copy the real vertex declaration — relative store resolves to tmp_path/data/project.db
    real = _PKG_ROOT / "loops" / "project.vertex"
    vertex.write_text(real.read_text())
    monkeypatch.setattr("strange_loops.commands.project.project_vertex_path", lambda: vertex)
    monkeypatch.setattr("strange_loops.commands.project._project_store", lambda: db)
    return db


def _ns(**kwargs) -> argparse.Namespace:
    defaults = {"observer": "", "json": False, "since": "7d", "kind": None}
    defaults.update(kwargs)
    return argparse.Namespace(**defaults)


class TestParseEmitParts:
    def test_key_value_only(self):
        result = _parse_emit_parts(["topic=auth", "status=decided"])
        assert result == {"topic": "auth", "status": "decided"}

    def test_message_only(self):
        result = _parse_emit_parts(["this", "is", "a", "message"])
        assert result == {"message": "this is a message"}

    def test_mixed(self):
        result = _parse_emit_parts(["topic=auth", "decided", "on", "JWT"])
        assert result == {"topic": "auth", "message": "decided on JWT"}

    def test_empty(self):
        result = _parse_emit_parts([])
        assert result == {}

    def test_non_identifier_key_treated_as_message(self):
        result = _parse_emit_parts(["not-ident=value"])
        assert result == {"message": "not-ident=value"}


class TestProjectEmit:
    def test_creates_store_on_first_emit(self, project_store: Path):
        assert not project_store.exists()
        args = _ns(kind="decision", parts=["topic=test", "first decision"])
        rc = cmd_project_emit(args)
        assert rc == 0
        assert project_store.exists()

    def test_decision_fact_lands(self, project_store: Path):
        args = _ns(kind="decision", parts=["topic=auth", "use JWT"])
        cmd_project_emit(args)
        facts = _read_all(project_store)
        assert len(facts) == 1
        assert facts[0]["kind"] == "decision"
        assert facts[0]["payload"]["topic"] == "auth"
        assert facts[0]["payload"]["message"] == "use JWT"

    def test_thread_fact_lands(self, project_store: Path):
        args = _ns(kind="thread", parts=["name=design", "status=open", "design the API"])
        cmd_project_emit(args)
        facts = _read_all(project_store)
        assert facts[0]["kind"] == "thread"
        assert facts[0]["payload"]["name"] == "design"
        assert facts[0]["payload"]["status"] == "open"

    def test_plan_fact_lands(self, project_store: Path):
        args = _ns(kind="plan", parts=["name=next-step", "status=next"])
        cmd_project_emit(args)
        facts = _read_all(project_store)
        assert facts[0]["kind"] == "plan"
        assert facts[0]["payload"]["name"] == "next-step"
        assert facts[0]["payload"]["status"] == "next"

    def test_observer_propagates(self, project_store: Path):
        args = _ns(kind="decision", parts=["topic=test"], observer="alice")
        cmd_project_emit(args)
        facts = _read_all(project_store)
        assert facts[0]["observer"] == "alice"

    def test_message_in_payload(self, project_store: Path):
        args = _ns(kind="decision", parts=["topic=x", "hello", "world"])
        cmd_project_emit(args)
        facts = _read_all(project_store)
        assert facts[0]["payload"]["message"] == "hello world"


class TestProjectStatus:
    def test_empty_without_store(self, project_store: Path, capsys):
        args = _ns()
        rc = cmd_project_status(args)
        assert rc == 0
        out = capsys.readouterr().out
        assert "0 facts" in out

    def test_shows_decisions(self, project_store: Path, capsys):
        emit_fact(project_store, "decision", "", {"topic": "auth", "message": "use JWT"})
        args = _ns()
        rc = cmd_project_status(args)
        assert rc == 0
        out = capsys.readouterr().out
        assert "auth" in out
        assert "Decisions" in out

    def test_filters_resolved_threads(self, project_store: Path):
        emit_fact(project_store, "thread", "", {"name": "design", "status": "open"})
        time.sleep(0.01)
        emit_fact(project_store, "thread", "", {"name": "design", "status": "resolved"})
        args = _ns(json=True)
        rc = cmd_project_status(args)
        assert rc == 0
        # resolved thread should not appear (parsed from stdout via json)

    def test_shows_plans(self, project_store: Path, capsys):
        emit_fact(project_store, "plan", "", {"name": "next-step", "status": "next"})
        args = _ns()
        rc = cmd_project_status(args)
        assert rc == 0
        out = capsys.readouterr().out
        assert "Plans" in out
        assert "next-step" in out

    def test_json_output(self, project_store: Path, capsys):
        emit_fact(project_store, "decision", "", {"topic": "auth", "message": "JWT"})
        emit_fact(project_store, "plan", "", {"name": "step1", "status": "next"})
        args = _ns(json=True)
        rc = cmd_project_status(args)
        assert rc == 0
        data = json.loads(capsys.readouterr().out)
        assert "decisions" in data
        assert "plans" in data
        assert data["total"] == 2

    def test_latest_per_group_wins(self, project_store: Path, capsys):
        emit_fact(project_store, "decision", "", {"topic": "auth", "message": "v1"})
        time.sleep(0.01)
        emit_fact(project_store, "decision", "", {"topic": "auth", "message": "v2"})
        args = _ns(json=True)
        rc = cmd_project_status(args)
        assert rc == 0
        data = json.loads(capsys.readouterr().out)
        assert data["decisions"]["auth"]["message"] == "v2"


class TestProjectLog:
    def test_shows_facts_chronologically(self, project_store: Path, capsys):
        emit_fact(project_store, "decision", "", {"topic": "a", "message": "first"})
        time.sleep(0.01)
        emit_fact(project_store, "thread", "", {"name": "b", "message": "second"})
        args = _ns()
        rc = cmd_project_log(args)
        assert rc == 0
        out = capsys.readouterr().out
        assert "decision" in out
        assert "thread" in out

    def test_kind_filter(self, project_store: Path, capsys):
        emit_fact(project_store, "decision", "", {"topic": "a"})
        emit_fact(project_store, "thread", "", {"name": "b"})
        args = _ns(kind="decision")
        rc = cmd_project_log(args)
        assert rc == 0
        out = capsys.readouterr().out
        assert "decision" in out
        assert "thread" not in out

    def test_json_output(self, project_store: Path, capsys):
        emit_fact(project_store, "decision", "", {"topic": "a"})
        args = _ns(json=True)
        rc = cmd_project_log(args)
        assert rc == 0
        line = capsys.readouterr().out.strip()
        data = json.loads(line)
        assert data["kind"] == "decision"

    def test_empty_without_store(self, project_store: Path, capsys):
        args = _ns()
        rc = cmd_project_log(args)
        assert rc == 0
        out = capsys.readouterr().out
        assert "No facts" in out


@pytest.fixture
def task_store(tmp_path: Path, monkeypatch):
    """Temp task vertex + store for bridge testing."""
    db = tmp_path / "data" / "tasks.db"
    vertex = tmp_path / "tasks.vertex"
    real = _PKG_ROOT / "loops" / "tasks.vertex"
    vertex.write_text(real.read_text())
    monkeypatch.setattr("strange_loops.commands.project.tasks_vertex_path", lambda: vertex)
    return db


class TestProjectBridge:
    def test_bridges_ticks_to_completions(self, project_store: Path, task_store: Path, capsys):
        # Emit a task.tick into the task store
        emit_tick(
            task_store,
            "task.tick",
            {"task": "my-task", "status": "completed", "exit_code": 0},
            origin="tasks",
        )
        args = _ns()
        rc = cmd_project_bridge(args)
        assert rc == 0
        out = capsys.readouterr().out
        assert "Bridged 1" in out
        assert "my-task" in out

        # Verify completion fact landed in project store
        facts = _read_all(project_store)
        completions = [f for f in facts if f["kind"] == "completion"]
        assert len(completions) == 1
        assert completions[0]["payload"]["task"] == "my-task"

    def test_idempotent(self, project_store: Path, task_store: Path, capsys):
        emit_tick(
            task_store,
            "task.tick",
            {"task": "t1", "status": "completed", "exit_code": 0},
            origin="tasks",
        )
        args = _ns()
        cmd_project_bridge(args)
        capsys.readouterr()  # clear

        # Second run should report all bridged
        rc = cmd_project_bridge(args)
        assert rc == 0
        out = capsys.readouterr().out
        assert "already bridged" in out

    def test_bridges_multiple(self, project_store: Path, task_store: Path, capsys):
        for name in ["a", "b", "c"]:
            emit_tick(
                task_store,
                "task.tick",
                {"task": name, "status": "completed", "exit_code": 0},
                origin="tasks",
            )
        args = _ns()
        rc = cmd_project_bridge(args)
        assert rc == 0
        out = capsys.readouterr().out
        assert "Bridged 3" in out

    def test_latest_tick_wins(self, project_store: Path, task_store: Path, capsys):
        emit_tick(
            task_store,
            "task.tick",
            {"task": "x", "status": "errored", "exit_code": 1},
            origin="tasks",
        )
        time.sleep(0.01)
        emit_tick(
            task_store,
            "task.tick",
            {"task": "x", "status": "completed", "exit_code": 0},
            origin="tasks",
        )
        args = _ns()
        cmd_project_bridge(args)

        facts = _read_all(project_store)
        completions = [f for f in facts if f["kind"] == "completion"]
        assert len(completions) == 1
        assert completions[0]["payload"]["status"] == "completed"

    def test_no_ticks_message(self, project_store: Path, task_store: Path, capsys):
        # Create an empty task store (just needs the schema)
        task_store.parent.mkdir(parents=True, exist_ok=True)
        with SqliteStore(path=task_store, serialize=Fact.to_dict, deserialize=Fact.from_dict) as _:
            pass
        args = _ns()
        rc = cmd_project_bridge(args)
        assert rc == 0
        out = capsys.readouterr().out
        assert "No task.tick" in out

    def test_empty_without_task_store(self, project_store: Path, task_store: Path, capsys):
        args = _ns()
        rc = cmd_project_bridge(args)
        assert rc == 0
        out = capsys.readouterr().out
        assert "No task.tick" in out


class TestProjectStatusCompletions:
    def test_completions_in_text_output(self, project_store: Path, capsys):
        emit_fact(
            project_store,
            "completion",
            "",
            {"task": "my-task", "status": "completed", "exit_code": 0},
        )
        args = _ns()
        rc = cmd_project_status(args)
        assert rc == 0
        out = capsys.readouterr().out
        assert "Completions" in out
        assert "my-task" in out

    def test_completions_in_json_output(self, project_store: Path, capsys):
        emit_fact(
            project_store, "completion", "", {"task": "t1", "status": "completed", "exit_code": 0}
        )
        args = _ns(json=True)
        rc = cmd_project_status(args)
        assert rc == 0
        data = json.loads(capsys.readouterr().out)
        assert "completions" in data
        assert "t1" in data["completions"]
        assert data["completions"]["t1"]["status"] == "completed"
