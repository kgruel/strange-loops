"""Tests for vertex-first status, log, init --template, and emit."""

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
    """Emit a fact via CLI using vertex-first dispatch (local session vertex)."""
    return main(["session", "emit", kind, *parts])


class TestStatus:
    def test_shows_decisions(self, tmp_path, monkeypatch, capsys):
        monkeypatch.chdir(tmp_path)
        monkeypatch.setenv("LOOPS_HOME", str(tmp_path / "unused"))
        _seed_session(tmp_path)

        assert _emit_local("decision", "topic=sigil", "{{var}} over ${var}") == 0
        assert _emit_local("decision", "topic=store", "personal instance") == 0

        result = main(["session", "status"])
        assert result == 0

        out = capsys.readouterr().out
        assert "## DECISION" in out
        # SUMMARY zoom: topics shown as labels with body snippets
        assert "sigil" in out
        assert "store" in out

    def test_shows_decisions_verbose(self, tmp_path, monkeypatch, capsys):
        monkeypatch.chdir(tmp_path)
        monkeypatch.setenv("LOOPS_HOME", str(tmp_path / "unused"))
        _seed_session(tmp_path)

        assert _emit_local("decision", "topic=sigil", "{{var}} over ${var}") == 0

        result = main(["session", "status", "-v"])
        assert result == 0

        out = capsys.readouterr().out
        # DETAILED+ zoom: message bodies visible
        assert "sigil" in out
        assert "{{var}} over ${var}" in out

    def test_latest_decision_wins(self, tmp_path, monkeypatch, capsys):
        monkeypatch.chdir(tmp_path)
        monkeypatch.setenv("LOOPS_HOME", str(tmp_path / "unused"))
        _seed_session(tmp_path)

        assert _emit_local("decision", "topic=sigil", "old choice") == 0
        time.sleep(0.01)
        assert _emit_local("decision", "topic=sigil", "new choice") == 0

        # SUMMARY: only topic visible, message bodies hidden
        result = main(["session", "status"])
        assert result == 0
        out = capsys.readouterr().out
        assert "## DECISION" in out
        assert "sigil" in out

        # DETAILED: message body visible, latest wins
        result = main(["session", "status", "-v"])
        assert result == 0
        out = capsys.readouterr().out
        assert "new choice" in out
        assert "old choice" not in out

    def test_threads_shows_all(self, tmp_path, monkeypatch, capsys):
        """Generic fold shows all accumulated state — no per-kind filtering."""
        monkeypatch.chdir(tmp_path)
        monkeypatch.setenv("LOOPS_HOME", str(tmp_path / "unused"))
        _seed_session(tmp_path)

        assert _emit_local("thread", "name=open-one", "status=open") == 0
        assert _emit_local("thread", "name=resolved-one", "status=resolved") == 0

        result = main(["session", "status"])
        assert result == 0

        out = capsys.readouterr().out
        assert "open-one" in out
        assert "resolved-one" in out

    def test_shows_tasks(self, tmp_path, monkeypatch, capsys):
        monkeypatch.chdir(tmp_path)
        monkeypatch.setenv("LOOPS_HOME", str(tmp_path / "unused"))
        _seed_session(tmp_path)

        assert _emit_local("task", "name=fix/review", "status=merged") == 0

        result = main(["session", "status"])
        assert result == 0

        out = capsys.readouterr().out
        assert "## TASK" in out
        assert "fix/review" in out

    def test_shows_changes(self, tmp_path, monkeypatch, capsys):
        monkeypatch.chdir(tmp_path)
        monkeypatch.setenv("LOOPS_HOME", str(tmp_path / "unused"))
        _seed_session(tmp_path)

        assert _emit_local("change", "summary=structural AST", "files=ast.py,loader.py") == 0

        result = main(["session", "status"])
        assert result == 0

        out = capsys.readouterr().out
        assert "## CHANGE" in out
        assert "structural AST" in out

    def test_json_output(self, tmp_path, monkeypatch, capsys):
        monkeypatch.chdir(tmp_path)
        monkeypatch.setenv("LOOPS_HOME", str(tmp_path / "unused"))
        _seed_session(tmp_path)

        assert _emit_local("decision", "topic=test", "a decision") == 0
        assert _emit_local("task", "name=task1", "status=open") == 0
        capsys.readouterr()  # clear prior output

        result = main(["session", "status", "--json"])
        assert result == 0

        data = json.loads(capsys.readouterr().out)
        assert "sections" in data
        assert "vertex" in data
        # Find sections by kind
        by_kind = {s["kind"]: s for s in data["sections"]}
        assert "decision" in by_kind
        assert "task" in by_kind
        assert len(by_kind["decision"]["items"]) == 1
        assert by_kind["decision"]["items"][0]["payload"]["topic"] == "test"
        assert len(by_kind["task"]["items"]) == 1

    def test_no_vertex_found(self, tmp_path, monkeypatch, capsys):
        monkeypatch.chdir(tmp_path)
        monkeypatch.setenv("LOOPS_HOME", str(tmp_path / "unused"))

        result = main(["session", "status"])
        assert result == 1

        captured = capsys.readouterr()
        assert "Unknown command" in (captured.out + captured.err)

    def test_empty_store(self, tmp_path, monkeypatch, capsys):
        monkeypatch.chdir(tmp_path)
        monkeypatch.setenv("LOOPS_HOME", str(tmp_path / "unused"))
        _seed_session(tmp_path)

        result = main(["session", "status"])
        assert result == 0

        out = capsys.readouterr().out
        assert "No data yet." in out

    def test_loops_home_fallback(self, tmp_path, monkeypatch, capsys):
        """Status resolves via LOOPS_HOME/session/ when no local vertex."""
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
        assert main(["session", "emit", "decision", "topic=fallback", "it works"]) == 0
        capsys.readouterr()

        result = main(["session", "status"])
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

        result = main(["session", "log", "--since", "1h"])
        assert result == 0

        out = capsys.readouterr().out
        assert "[decision]" in out
        # Kind-aware formatting: "topic: message" not "topic=x message=y"
        assert "first: one" in out
        assert "second: two" in out

    def test_kind_filter(self, tmp_path, monkeypatch, capsys):
        monkeypatch.chdir(tmp_path)
        monkeypatch.setenv("LOOPS_HOME", str(tmp_path / "unused"))
        _seed_session(tmp_path)

        assert _emit_local("decision", "topic=d1", "yes") == 0
        assert _emit_local("task", "name=t1", "status=open") == 0

        result = main(["session", "log", "--since", "1h", "--kind", "decision"])
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

        result = main(["session", "log", "--since", "1h", "--json"])
        assert result == 0

        # run_cli serializes the whole fetch result as JSON
        data = json.loads(capsys.readouterr().out)
        assert "facts" in data
        assert "fold_meta" in data
        facts = data["facts"]
        assert len(facts) >= 1
        for item in facts:
            assert "kind" in item
            assert "ts" in item

    def test_since_filter(self, tmp_path, monkeypatch, capsys):
        monkeypatch.chdir(tmp_path)
        monkeypatch.setenv("LOOPS_HOME", str(tmp_path / "unused"))
        _seed_session(tmp_path)

        assert _emit_local("decision", "topic=recent", "yes") == 0

        result = main(["session", "log", "--since", "1m"])
        assert result == 0

        out = capsys.readouterr().out
        assert "[decision]" in out

    def test_no_vertex_found(self, tmp_path, monkeypatch, capsys):
        monkeypatch.chdir(tmp_path)
        monkeypatch.setenv("LOOPS_HOME", str(tmp_path / "unused"))

        result = main(["session", "log"])
        assert result == 1

        captured = capsys.readouterr()
        assert "Unknown command" in (captured.out + captured.err)


def _seed_config_vertex(home: Path, name: str, content: str) -> None:
    """Create a config-level instance vertex for testing."""
    config_dir = home / name
    config_dir.mkdir(parents=True, exist_ok=True)
    (config_dir / f"{name}.vertex").write_text(content)


_SESSION_CONTENT = 'name "session"\nstore "./data/session.db"\n\nloops {\n  decision { fold { items "by" "topic" } }\n  task { fold { items "by" "name" } }\n}\n'
_TASKS_CONTENT = 'name "tasks"\nstore "./data/tasks.db"\n\nloops {\n  task { fold { items "by" "name" } }\n}\n'


class TestEmitToConfigVertex:
    def test_emit_to_config_level_vertex(self, tmp_path, monkeypatch, capsys):
        """emit writes to config-level vertex when no local vertex exists."""
        home = tmp_path / "home"
        _seed_config_vertex(home, "session", _SESSION_CONTENT)
        (home / "session" / "data").mkdir()
        monkeypatch.chdir(tmp_path)
        monkeypatch.setenv("LOOPS_HOME", str(home))

        result = main(["session", "emit", "decision", "topic=test", "it works"])
        assert result == 0

        # Store has the fact in config-level location
        db_path = home / "session" / "data" / "session.db"
        facts = _read_all_facts(db_path)
        assert any(f.kind == "decision" for f in facts)

    def test_emit_prefers_local_vertex(self, tmp_path, monkeypatch, capsys):
        """emit uses local vertex when it exists, even if config-level also exists."""
        home = tmp_path / "home"
        _seed_config_vertex(home, "tasks", _TASKS_CONTENT)
        (home / "tasks" / "data").mkdir()
        monkeypatch.chdir(tmp_path)
        monkeypatch.setenv("LOOPS_HOME", str(home))

        # Pre-create a local tasks vertex
        main(["init", "--template", "tasks"])
        capsys.readouterr()

        result = main(["tasks", "emit", "task", "name=do-thing", "status=open"])
        assert result == 0

        # Should use local vertex in .loops/, not config-level
        db_path = tmp_path / ".loops" / "data" / "tasks.db"
        facts = _read_all_facts(db_path)
        assert any(f.kind == "task" for f in facts)


class TestInitTemplate:
    def test_session_template(self, tmp_path, monkeypatch, capsys):
        monkeypatch.chdir(tmp_path)

        result = main(["init", "--template", "session"])
        assert result == 0

        vertex = tmp_path / ".loops" / "session.vertex"
        assert vertex.exists()
        content = vertex.read_text()
        assert 'name "session"' in content
        assert 'store "./data/session.db"' in content
        assert (tmp_path / ".loops" / "data").is_dir()

    def test_tasks_template(self, tmp_path, monkeypatch, capsys):
        home = tmp_path / "home"
        _seed_config_vertex(home, "tasks", _TASKS_CONTENT)
        monkeypatch.setenv("LOOPS_HOME", str(home))
        monkeypatch.chdir(tmp_path)

        result = main(["init", "--template", "tasks"])
        assert result == 0

        vertex = tmp_path / ".loops" / "tasks.vertex"
        assert vertex.exists()
        content = vertex.read_text()
        assert 'name "tasks"' in content
        assert 'store "./data/tasks.db"' in content
        assert (tmp_path / ".loops" / "data").is_dir()

    def test_no_template_is_root(self, tmp_path, monkeypatch, capsys):
        """init without --template still creates .vertex in LOOPS_HOME."""
        monkeypatch.setenv("LOOPS_HOME", str(tmp_path))

        result = main(["init"])
        assert result == 0

        root = tmp_path / ".vertex"
        assert root.exists()
        assert "discover" in root.read_text()

    def test_idempotent_template(self, tmp_path, monkeypatch, capsys):
        monkeypatch.chdir(tmp_path)

        main(["init", "--template", "session"])
        text1 = (tmp_path / ".loops" / "session.vertex").read_text()

        main(["init", "--template", "session"])
        text2 = (tmp_path / ".loops" / "session.vertex").read_text()

        assert text1 == text2
