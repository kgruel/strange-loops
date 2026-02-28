"""Tests for loops session commands."""

from __future__ import annotations

import json
import time
from pathlib import Path

from atoms import Fact
from engine import SqliteStore

from loops.main import main


def _read_all_facts(db_path: Path) -> list[Fact]:
    with SqliteStore(
        path=db_path, serialize=Fact.to_dict, deserialize=Fact.from_dict
    ) as store:
        return store.since(0)


def _emit(vertex: str, kind: str, *parts: str):
    """Helper: emit a fact via CLI (LOOPS_HOME must be set via monkeypatch)."""
    result = main(["emit", vertex, kind, *parts])
    assert result == 0


class TestSessionStart:
    def test_emits_start_fact(self, tmp_path, monkeypatch):
        home = tmp_path / "home"
        monkeypatch.setenv("LOOPS_HOME", str(home))

        result = main(["session", "start"])
        assert result == 0

        db_path = home / "session" / "data" / "session.db"
        facts = _read_all_facts(db_path)
        assert any(f.kind == "session.start" for f in facts)

    def test_autocreates_vertex(self, tmp_path, monkeypatch):
        home = tmp_path / "home"
        monkeypatch.setenv("LOOPS_HOME", str(home))

        vertex_path = home / "session" / "session.vertex"
        assert not vertex_path.exists()

        result = main(["session", "start"])
        assert result == 0
        assert vertex_path.exists()

        text = vertex_path.read_text()
        assert 'name "session"' in text
        assert 'store "./data/session.db"' in text

    def test_idempotent_vertex_creation(self, tmp_path, monkeypatch):
        home = tmp_path / "home"
        monkeypatch.setenv("LOOPS_HOME", str(home))

        main(["session", "start"])
        vertex_path = home / "session" / "session.vertex"
        text1 = vertex_path.read_text()

        main(["session", "start"])
        text2 = vertex_path.read_text()
        assert text1 == text2

    def test_observer_flag(self, tmp_path, monkeypatch):
        home = tmp_path / "home"
        monkeypatch.setenv("LOOPS_HOME", str(home))

        result = main(["session", "start", "--observer", "human"])
        assert result == 0

        db_path = home / "session" / "data" / "session.db"
        facts = _read_all_facts(db_path)
        start_facts = [f for f in facts if f.kind == "session.start"]
        assert start_facts[0].observer == "human"


class TestSessionEnd:
    def test_emits_end_fact(self, tmp_path, monkeypatch):
        home = tmp_path / "home"
        monkeypatch.setenv("LOOPS_HOME", str(home))

        main(["session", "start"])
        result = main(["session", "end"])
        assert result == 0

        db_path = home / "session" / "data" / "session.db"
        facts = _read_all_facts(db_path)
        assert any(f.kind == "session.end" for f in facts)


class TestSessionStatus:
    def test_shows_decisions(self, tmp_path, monkeypatch, capsys):
        home = tmp_path / "home"
        monkeypatch.setenv("LOOPS_HOME", str(home))

        main(["session", "start"])
        _emit("session", "decision", "topic=sigil", "{{var}} over ${var}")
        _emit("session", "decision", "topic=store", "personal instance")

        result = main(["session", "status"])
        assert result == 0

        out = capsys.readouterr().out
        assert "Decisions (2):" in out
        assert "sigil:" in out
        assert "store:" in out

    def test_latest_decision_wins(self, tmp_path, monkeypatch, capsys):
        home = tmp_path / "home"
        monkeypatch.setenv("LOOPS_HOME", str(home))

        main(["session", "start"])
        _emit("session", "decision", "topic=sigil", "old choice")
        time.sleep(0.01)
        _emit("session", "decision", "topic=sigil", "new choice")

        result = main(["session", "status"])
        assert result == 0

        out = capsys.readouterr().out
        assert "Decisions (1):" in out
        assert "new choice" in out
        assert "old choice" not in out

    def test_threads_filters_resolved(self, tmp_path, monkeypatch, capsys):
        home = tmp_path / "home"
        monkeypatch.setenv("LOOPS_HOME", str(home))

        main(["session", "start"])
        _emit("session", "thread", "name=open-one", "status=open")
        _emit("session", "thread", "name=resolved-one", "status=resolved")

        result = main(["session", "status"])
        assert result == 0

        out = capsys.readouterr().out
        assert "open-one" in out
        assert "resolved-one" not in out

    def test_shows_tasks(self, tmp_path, monkeypatch, capsys):
        home = tmp_path / "home"
        monkeypatch.setenv("LOOPS_HOME", str(home))

        main(["session", "start"])
        _emit("session", "task", "name=fix/review", "status=merged")

        result = main(["session", "status"])
        assert result == 0

        out = capsys.readouterr().out
        assert "Active Tasks (1):" in out
        assert "fix/review: merged" in out

    def test_shows_changes(self, tmp_path, monkeypatch, capsys):
        home = tmp_path / "home"
        monkeypatch.setenv("LOOPS_HOME", str(home))

        main(["session", "start"])
        _emit(
            "session",
            "change",
            "summary=structural AST",
            "files=ast.py,loader.py",
        )

        result = main(["session", "status"])
        assert result == 0

        out = capsys.readouterr().out
        assert "Recent Changes (1):" in out
        assert "structural AST" in out

    def test_json_output(self, tmp_path, monkeypatch, capsys):
        home = tmp_path / "home"
        monkeypatch.setenv("LOOPS_HOME", str(home))

        main(["session", "start"])
        _emit("session", "decision", "topic=test", "a decision")
        _emit("session", "task", "name=task1", "status=open")
        capsys.readouterr()  # clear prior output

        result = main(["session", "status", "--json"])
        assert result == 0

        data = json.loads(capsys.readouterr().out)
        assert "decisions" in data
        assert "threads" in data
        assert "tasks" in data
        assert "changes" in data
        assert len(data["decisions"]) == 1
        assert data["decisions"][0]["topic"] == "test"
        assert len(data["tasks"]) == 1

    def test_no_session_initialized(self, tmp_path, monkeypatch, capsys):
        home = tmp_path / "home"
        monkeypatch.setenv("LOOPS_HOME", str(home))

        # Status before any session started — no vertex exists
        result = main(["session", "status"])
        assert result == 1

        err = capsys.readouterr().err
        assert "No session initialized" in err

    def test_empty_store(self, tmp_path, monkeypatch, capsys):
        home = tmp_path / "home"
        monkeypatch.setenv("LOOPS_HOME", str(home))

        # Start creates vertex + store, but no domain facts yet
        main(["session", "start"])
        capsys.readouterr()  # clear start output

        result = main(["session", "status"])
        assert result == 0

        out = capsys.readouterr().out
        assert "No session data yet." in out


class TestSessionLog:
    def test_chronological_output(self, tmp_path, monkeypatch, capsys):
        home = tmp_path / "home"
        monkeypatch.setenv("LOOPS_HOME", str(home))

        main(["session", "start"])
        _emit("session", "decision", "topic=first", "one")
        time.sleep(0.01)
        _emit("session", "decision", "topic=second", "two")

        result = main(["session", "log", "--since", "1h"])
        assert result == 0

        out = capsys.readouterr().out
        # Should contain both facts
        assert "[decision]" in out
        assert "topic=first" in out
        assert "topic=second" in out

    def test_kind_filter(self, tmp_path, monkeypatch, capsys):
        home = tmp_path / "home"
        monkeypatch.setenv("LOOPS_HOME", str(home))

        main(["session", "start"])
        _emit("session", "decision", "topic=d1", "yes")
        _emit("session", "task", "name=t1", "status=open")

        result = main(["session", "log", "--since", "1h", "--kind", "decision"])
        assert result == 0

        out = capsys.readouterr().out
        assert "[decision]" in out
        assert "[task]" not in out

    def test_json_output(self, tmp_path, monkeypatch, capsys):
        home = tmp_path / "home"
        monkeypatch.setenv("LOOPS_HOME", str(home))

        main(["session", "start"])
        _emit("session", "decision", "topic=d1", "yes")
        capsys.readouterr()  # clear prior output

        result = main(["session", "log", "--since", "1h", "--json"])
        assert result == 0

        lines = capsys.readouterr().out.strip().split("\n")
        # At least session.start + decision
        assert len(lines) >= 2
        for line in lines:
            parsed = json.loads(line)
            assert "kind" in parsed
            assert "ts" in parsed

    def test_since_filter(self, tmp_path, monkeypatch, capsys):
        home = tmp_path / "home"
        monkeypatch.setenv("LOOPS_HOME", str(home))

        main(["session", "start"])
        _emit("session", "decision", "topic=recent", "yes")

        # Very short window should still capture recent facts
        result = main(["session", "log", "--since", "1m"])
        assert result == 0

        out = capsys.readouterr().out
        assert "[decision]" in out

    def test_no_session_initialized(self, tmp_path, monkeypatch, capsys):
        home = tmp_path / "home"
        monkeypatch.setenv("LOOPS_HOME", str(home))

        result = main(["session", "log"])
        assert result == 1

        err = capsys.readouterr().err
        assert "No session initialized" in err


class TestObserverEnv:
    def test_observer_from_env(self, tmp_path, monkeypatch):
        home = tmp_path / "home"
        monkeypatch.setenv("LOOPS_HOME", str(home))
        monkeypatch.setenv("LOOPS_OBSERVER", "claude-agent")

        result = main(["session", "start"])
        assert result == 0

        db_path = home / "session" / "data" / "session.db"
        facts = _read_all_facts(db_path)
        start_facts = [f for f in facts if f.kind == "session.start"]
        assert start_facts[0].observer == "claude-agent"

    def test_flag_overrides_env(self, tmp_path, monkeypatch):
        home = tmp_path / "home"
        monkeypatch.setenv("LOOPS_HOME", str(home))
        monkeypatch.setenv("LOOPS_OBSERVER", "from-env")

        result = main(["session", "start", "--observer", "from-flag"])
        assert result == 0

        db_path = home / "session" / "data" / "session.db"
        facts = _read_all_facts(db_path)
        start_facts = [f for f in facts if f.kind == "session.start"]
        assert start_facts[0].observer == "from-flag"
