"""Tests for session commands."""

from __future__ import annotations

import json
from pathlib import Path

from atoms import Fact
from engine import SqliteStore

from strange_loops.cli import main


def _read_all(db_path: Path) -> list[dict]:
    with SqliteStore(path=db_path, serialize=Fact.to_dict, deserialize=Fact.from_dict) as store:
        return [Fact.to_dict(f) for f in store.since(0)]


class TestSessionStart:
    def test_creates_store_and_emits_fact(self, workspace: Path, monkeypatch):
        monkeypatch.chdir(workspace)
        rc = main(["session", "start"])
        assert rc == 0

        db = workspace / "data" / "tasks.db"
        assert db.exists()

        facts = _read_all(db)
        assert len(facts) == 1
        assert facts[0]["kind"] == "session.start"

    def test_idempotent(self, workspace: Path, monkeypatch):
        monkeypatch.chdir(workspace)
        main(["session", "start"])
        main(["session", "start"])

        facts = _read_all(workspace / "data" / "tasks.db")
        assert len(facts) == 2
        assert all(f["kind"] == "session.start" for f in facts)

    def test_observer_flag(self, workspace: Path, monkeypatch):
        monkeypatch.chdir(workspace)
        main(["session", "start", "--observer", "alice"])

        facts = _read_all(workspace / "data" / "tasks.db")
        assert facts[0]["observer"] == "alice"

    def test_observer_env_strange_loops(self, workspace: Path, monkeypatch):
        monkeypatch.chdir(workspace)
        monkeypatch.setenv("STRANGE_LOOPS_OBSERVER", "bob")
        main(["session", "start"])

        facts = _read_all(workspace / "data" / "tasks.db")
        assert facts[0]["observer"] == "bob"

    def test_observer_env_loops_fallback(self, workspace: Path, monkeypatch):
        monkeypatch.chdir(workspace)
        monkeypatch.delenv("STRANGE_LOOPS_OBSERVER", raising=False)
        monkeypatch.setenv("LOOPS_OBSERVER", "carol")
        main(["session", "start"])

        facts = _read_all(workspace / "data" / "tasks.db")
        assert facts[0]["observer"] == "carol"

    def test_strange_loops_observer_takes_precedence(self, workspace: Path, monkeypatch):
        monkeypatch.chdir(workspace)
        monkeypatch.setenv("STRANGE_LOOPS_OBSERVER", "bob")
        monkeypatch.setenv("LOOPS_OBSERVER", "carol")
        main(["session", "start"])

        facts = _read_all(workspace / "data" / "tasks.db")
        assert facts[0]["observer"] == "bob"


class TestSessionEnd:
    def test_emits_end_fact(self, workspace: Path, monkeypatch):
        monkeypatch.chdir(workspace)
        main(["session", "start"])
        rc = main(["session", "end"])
        assert rc == 0

        facts = _read_all(workspace / "data" / "tasks.db")
        kinds = [f["kind"] for f in facts]
        assert "session.start" in kinds
        assert "session.end" in kinds

    def test_errors_without_session(self, workspace: Path, monkeypatch, capsys):
        monkeypatch.chdir(workspace)
        rc = main(["session", "end"])
        assert rc == 1
        assert "No session initialized" in capsys.readouterr().err


class TestSessionStatus:
    def test_errors_without_session(self, workspace: Path, monkeypatch, capsys):
        monkeypatch.chdir(workspace)
        rc = main(["session", "status"])
        assert rc == 1
        assert "No session initialized" in capsys.readouterr().out

    def test_json_output(self, workspace: Path, monkeypatch, capsys):
        monkeypatch.chdir(workspace)
        main(["session", "start"])
        capsys.readouterr()

        rc = main(["session", "status", "--json"])
        assert rc == 0

        out = capsys.readouterr().out
        data = json.loads(out)
        assert "facts" in data
        assert "ticks" in data

    def test_text_output_after_start(self, workspace: Path, monkeypatch, capsys):
        monkeypatch.chdir(workspace)
        main(["session", "start"])
        # Clear capsys from start output
        capsys.readouterr()

        rc = main(["session", "status"])
        assert rc == 0

        out = capsys.readouterr().out
        assert "session.start" in out


class TestSessionLog:
    def test_shows_facts(self, workspace: Path, monkeypatch, capsys):
        monkeypatch.chdir(workspace)
        main(["session", "start"])
        capsys.readouterr()

        rc = main(["session", "log", "--since", "1h"])
        assert rc == 0

        out = capsys.readouterr().out
        assert "session.start" in out

    def test_kind_filter(self, workspace: Path, monkeypatch, capsys):
        monkeypatch.chdir(workspace)
        main(["session", "start"])
        main(["session", "end"])
        capsys.readouterr()

        rc = main(["session", "log", "--kind", "session.end"])
        assert rc == 0

        out = capsys.readouterr().out
        assert "session.end" in out
        assert "session.start" not in out

    def test_json_output(self, workspace: Path, monkeypatch, capsys):
        monkeypatch.chdir(workspace)
        main(["session", "start"])
        capsys.readouterr()

        rc = main(["session", "log", "--json"])
        assert rc == 0

        out = capsys.readouterr().out
        data = json.loads(out)
        assert "facts" in data
        assert len(data["facts"]) >= 1
        assert "kind" in data["facts"][0]

    def test_errors_without_session(self, workspace: Path, monkeypatch, capsys):
        monkeypatch.chdir(workspace)
        rc = main(["session", "log"])
        assert rc == 1
        assert "No session initialized" in capsys.readouterr().out

    def test_invalid_duration(self, workspace: Path, monkeypatch, capsys):
        monkeypatch.chdir(workspace)
        main(["session", "start"])
        capsys.readouterr()

        rc = main(["session", "log", "--since", "nope"])
        assert rc == 1
        assert "Invalid duration" in capsys.readouterr().err
