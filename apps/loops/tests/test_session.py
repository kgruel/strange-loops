"""Tests for top-level status, log, init --template, and emit auto-init."""

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


def _seed_session(workspace: Path) -> Path:
    """Create a session vertex + data dir in workspace, return store path."""
    vertex = workspace / "session.vertex"
    vertex.write_text(
        'name "session"\n'
        'store "./data/session.db"\n\n'
        "loops {\n"
        '  decision { fold { items "by" "topic" } }\n'
        '  thread   { fold { items "by" "name" } }\n'
        '  change   { fold { items "collect" 20 } }\n'
        '  task     { fold { items "by" "name" } }\n'
        "}\n"
    )
    (workspace / "data").mkdir()
    return workspace / "data" / "session.db"


def _emit_local(kind: str, *parts: str) -> int:
    """Emit a fact via CLI using local vertex resolution (no vertex arg)."""
    return main(["emit", kind, *parts])


class TestStatus:
    def test_shows_decisions(self, tmp_path, monkeypatch, capsys):
        monkeypatch.chdir(tmp_path)
        monkeypatch.setenv("LOOPS_HOME", str(tmp_path / "unused"))
        _seed_session(tmp_path)

        assert _emit_local("decision", "topic=sigil", "{{var}} over ${var}") == 0
        assert _emit_local("decision", "topic=store", "personal instance") == 0

        result = main(["status"])
        assert result == 0

        out = capsys.readouterr().out
        assert "Decisions (2):" in out
        assert "sigil:" in out
        assert "store:" in out

    def test_latest_decision_wins(self, tmp_path, monkeypatch, capsys):
        monkeypatch.chdir(tmp_path)
        monkeypatch.setenv("LOOPS_HOME", str(tmp_path / "unused"))
        _seed_session(tmp_path)

        assert _emit_local("decision", "topic=sigil", "old choice") == 0
        time.sleep(0.01)
        assert _emit_local("decision", "topic=sigil", "new choice") == 0

        result = main(["status"])
        assert result == 0

        out = capsys.readouterr().out
        assert "Decisions (1):" in out
        assert "new choice" in out
        assert "old choice" not in out

    def test_threads_filters_resolved(self, tmp_path, monkeypatch, capsys):
        monkeypatch.chdir(tmp_path)
        monkeypatch.setenv("LOOPS_HOME", str(tmp_path / "unused"))
        _seed_session(tmp_path)

        assert _emit_local("thread", "name=open-one", "status=open") == 0
        assert _emit_local("thread", "name=resolved-one", "status=resolved") == 0

        result = main(["status"])
        assert result == 0

        out = capsys.readouterr().out
        assert "open-one" in out
        assert "resolved-one" not in out

    def test_shows_tasks(self, tmp_path, monkeypatch, capsys):
        monkeypatch.chdir(tmp_path)
        monkeypatch.setenv("LOOPS_HOME", str(tmp_path / "unused"))
        _seed_session(tmp_path)

        assert _emit_local("task", "name=fix/review", "status=merged") == 0

        result = main(["status"])
        assert result == 0

        out = capsys.readouterr().out
        assert "Active Tasks (1):" in out
        assert "fix/review: merged" in out

    def test_shows_changes(self, tmp_path, monkeypatch, capsys):
        monkeypatch.chdir(tmp_path)
        monkeypatch.setenv("LOOPS_HOME", str(tmp_path / "unused"))
        _seed_session(tmp_path)

        assert _emit_local("change", "summary=structural AST", "files=ast.py,loader.py") == 0

        result = main(["status"])
        assert result == 0

        out = capsys.readouterr().out
        assert "Recent Changes (1):" in out
        assert "structural AST" in out

    def test_json_output(self, tmp_path, monkeypatch, capsys):
        monkeypatch.chdir(tmp_path)
        monkeypatch.setenv("LOOPS_HOME", str(tmp_path / "unused"))
        _seed_session(tmp_path)

        assert _emit_local("decision", "topic=test", "a decision") == 0
        assert _emit_local("task", "name=task1", "status=open") == 0
        capsys.readouterr()  # clear prior output

        result = main(["status", "--json"])
        assert result == 0

        data = json.loads(capsys.readouterr().out)
        assert "decisions" in data
        assert "threads" in data
        assert "tasks" in data
        assert "changes" in data
        assert len(data["decisions"]) == 1
        assert data["decisions"][0]["topic"] == "test"
        assert len(data["tasks"]) == 1

    def test_no_vertex_found(self, tmp_path, monkeypatch, capsys):
        monkeypatch.chdir(tmp_path)
        monkeypatch.setenv("LOOPS_HOME", str(tmp_path / "unused"))

        result = main(["status"])
        assert result == 1

        err = capsys.readouterr().err
        assert "No vertex found" in err

    def test_empty_store(self, tmp_path, monkeypatch, capsys):
        monkeypatch.chdir(tmp_path)
        monkeypatch.setenv("LOOPS_HOME", str(tmp_path / "unused"))
        _seed_session(tmp_path)

        result = main(["status"])
        assert result == 0

        out = capsys.readouterr().out
        assert "No session data yet." in out

    def test_loops_home_fallback(self, tmp_path, monkeypatch, capsys):
        """Status falls back to LOOPS_HOME/session/ when no local vertex."""
        home = tmp_path / "home"
        workspace = tmp_path / "workspace"
        workspace.mkdir()
        monkeypatch.chdir(workspace)
        monkeypatch.setenv("LOOPS_HOME", str(home))

        # Seed session in LOOPS_HOME
        session_dir = home / "session"
        session_dir.mkdir(parents=True)
        (session_dir / "session.vertex").write_text(
            'name "session"\n'
            'store "./data/session.db"\n\n'
            "loops {\n"
            '  decision { fold { items "by" "topic" } }\n'
            "}\n"
        )
        (session_dir / "data").mkdir()

        # Emit via LOOPS_HOME session vertex
        assert main(["emit", "session", "decision", "topic=fallback", "it works"]) == 0
        capsys.readouterr()

        result = main(["status"])
        assert result == 0

        out = capsys.readouterr().out
        assert "fallback" in out


class TestLog:
    def test_chronological_output(self, tmp_path, monkeypatch, capsys):
        monkeypatch.chdir(tmp_path)
        monkeypatch.setenv("LOOPS_HOME", str(tmp_path / "unused"))
        _seed_session(tmp_path)

        assert _emit_local("decision", "topic=first", "one") == 0
        time.sleep(0.01)
        assert _emit_local("decision", "topic=second", "two") == 0

        result = main(["log", "--since", "1h"])
        assert result == 0

        out = capsys.readouterr().out
        assert "[decision]" in out
        assert "topic=first" in out
        assert "topic=second" in out

    def test_kind_filter(self, tmp_path, monkeypatch, capsys):
        monkeypatch.chdir(tmp_path)
        monkeypatch.setenv("LOOPS_HOME", str(tmp_path / "unused"))
        _seed_session(tmp_path)

        assert _emit_local("decision", "topic=d1", "yes") == 0
        assert _emit_local("task", "name=t1", "status=open") == 0

        result = main(["log", "--since", "1h", "--kind", "decision"])
        assert result == 0

        out = capsys.readouterr().out
        assert "[decision]" in out
        assert "[task]" not in out

    def test_json_output(self, tmp_path, monkeypatch, capsys):
        monkeypatch.chdir(tmp_path)
        monkeypatch.setenv("LOOPS_HOME", str(tmp_path / "unused"))
        _seed_session(tmp_path)

        assert _emit_local("decision", "topic=d1", "yes") == 0
        capsys.readouterr()

        result = main(["log", "--since", "1h", "--json"])
        assert result == 0

        lines = capsys.readouterr().out.strip().split("\n")
        assert len(lines) >= 1
        for line in lines:
            parsed = json.loads(line)
            assert "kind" in parsed
            assert "ts" in parsed

    def test_since_filter(self, tmp_path, monkeypatch, capsys):
        monkeypatch.chdir(tmp_path)
        monkeypatch.setenv("LOOPS_HOME", str(tmp_path / "unused"))
        _seed_session(tmp_path)

        assert _emit_local("decision", "topic=recent", "yes") == 0

        result = main(["log", "--since", "1m"])
        assert result == 0

        out = capsys.readouterr().out
        assert "[decision]" in out

    def test_no_vertex_found(self, tmp_path, monkeypatch, capsys):
        monkeypatch.chdir(tmp_path)
        monkeypatch.setenv("LOOPS_HOME", str(tmp_path / "unused"))

        result = main(["log"])
        assert result == 1

        err = capsys.readouterr().err
        assert "No vertex found" in err


class TestAutoInit:
    def test_emit_creates_vertex_and_store(self, tmp_path, monkeypatch, capsys):
        """emit in empty dir auto-inits session template."""
        monkeypatch.chdir(tmp_path)
        monkeypatch.setenv("LOOPS_HOME", str(tmp_path / "unused"))

        result = main(["emit", "decision", "topic=test", "it works"])
        assert result == 0

        # Vertex created in cwd
        vertex = tmp_path / "session.vertex"
        assert vertex.exists()
        assert 'name "session"' in vertex.read_text()

        # Store has the fact
        db_path = tmp_path / "data" / "session.db"
        facts = _read_all_facts(db_path)
        assert any(f.kind == "decision" for f in facts)

    def test_emit_reuses_existing_local_vertex(self, tmp_path, monkeypatch, capsys):
        """emit finds and uses existing local vertex without creating a new one."""
        monkeypatch.chdir(tmp_path)
        monkeypatch.setenv("LOOPS_HOME", str(tmp_path / "unused"))

        # Pre-create a tasks vertex
        main(["init", "--template", "tasks"])
        capsys.readouterr()

        result = main(["emit", "task", "name=do-thing", "status=open"])
        assert result == 0

        # Should use tasks vertex, not create session
        assert (tmp_path / "tasks.vertex").exists()
        assert not (tmp_path / "session.vertex").exists()

        err = capsys.readouterr().err
        assert "Auto-initialized" not in err


class TestInitTemplate:
    def test_session_template(self, tmp_path, monkeypatch, capsys):
        monkeypatch.chdir(tmp_path)

        result = main(["init", "--template", "session"])
        assert result == 0

        vertex = tmp_path / "session.vertex"
        assert vertex.exists()
        content = vertex.read_text()
        assert 'name "session"' in content
        assert 'store "./data/session.db"' in content
        assert (tmp_path / "data").is_dir()

    def test_tasks_template(self, tmp_path, monkeypatch, capsys):
        monkeypatch.chdir(tmp_path)

        result = main(["init", "--template", "tasks"])
        assert result == 0

        vertex = tmp_path / "tasks.vertex"
        assert vertex.exists()
        content = vertex.read_text()
        assert 'name "tasks"' in content
        assert 'store "./data/tasks.db"' in content
        assert (tmp_path / "data").is_dir()

    def test_no_template_is_root(self, tmp_path, monkeypatch, capsys):
        """init without --template still creates root.vertex in LOOPS_HOME."""
        monkeypatch.setenv("LOOPS_HOME", str(tmp_path))

        result = main(["init"])
        assert result == 0

        root = tmp_path / "root.vertex"
        assert root.exists()
        assert 'name "root"' in root.read_text()

    def test_idempotent_template(self, tmp_path, monkeypatch, capsys):
        monkeypatch.chdir(tmp_path)

        main(["init", "--template", "session"])
        text1 = (tmp_path / "session.vertex").read_text()

        main(["init", "--template", "session"])
        text2 = (tmp_path / "session.vertex").read_text()

        assert text1 == text2
