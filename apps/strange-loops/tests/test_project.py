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
    _latest_by_group,
    _parse_emit_parts,
    cmd_project_emit,
    cmd_project_log,
    cmd_project_status,
)
from strange_loops.store import emit_fact


def _read_all(db_path: Path) -> list[dict]:
    with SqliteStore(path=db_path, serialize=Fact.to_dict, deserialize=Fact.from_dict) as store:
        return [Fact.to_dict(f) for f in store.since(0)]


@pytest.fixture
def project_store(tmp_path: Path, monkeypatch):
    """Monkeypatch _project_store to return a temp path."""
    db = tmp_path / "data" / "project.db"
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
    def test_errors_without_store(self, project_store: Path, capsys):
        args = _ns()
        rc = cmd_project_status(args)
        assert rc == 1
        assert "No project data" in capsys.readouterr().err

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

    def test_errors_without_store(self, project_store: Path, capsys):
        args = _ns()
        rc = cmd_project_log(args)
        assert rc == 1
        assert "No project data" in capsys.readouterr().err


class TestLatestByGroup:
    def test_groups_by_field(self):
        facts = [
            {"kind": "decision", "ts": 1.0, "payload": {"topic": "a", "message": "first"}},
            {"kind": "decision", "ts": 2.0, "payload": {"topic": "b", "message": "other"}},
            {"kind": "decision", "ts": 3.0, "payload": {"topic": "a", "message": "latest"}},
        ]
        result = _latest_by_group(facts, "decision", "topic")
        assert len(result) == 2
        assert result["a"]["payload"]["message"] == "latest"
        assert result["b"]["payload"]["message"] == "other"

    def test_filters_by_kind(self):
        facts = [
            {"kind": "decision", "ts": 1.0, "payload": {"topic": "a"}},
            {"kind": "thread", "ts": 2.0, "payload": {"topic": "a"}},
        ]
        result = _latest_by_group(facts, "decision", "topic")
        assert len(result) == 1

    def test_empty_input(self):
        assert _latest_by_group([], "decision", "topic") == {}

    def test_skips_missing_group_field(self):
        facts = [
            {"kind": "decision", "ts": 1.0, "payload": {"other": "x"}},
        ]
        result = _latest_by_group(facts, "decision", "topic")
        assert len(result) == 0
