"""Tests for loops emit command."""

from __future__ import annotations

import json
from datetime import datetime as py_datetime, timezone
from pathlib import Path

from atoms import Fact
from engine import SqliteStore

from loops.main import main


def _write_vertex(home: Path, name: str, *, store: str | None) -> Path:
    vdir = home / name
    vdir.mkdir(parents=True)
    vertex_path = vdir / f"{name}.vertex"
    store_line = f'store "{store}"\n' if store is not None else ""
    vertex_path.write_text(
        f'name "{name}"\n'
        f"{store_line}"
        "loops {\n"
        "  counter {\n"
        "    fold { count \"inc\" }\n"
        "  }\n"
        "}\n"
    )
    return vertex_path


def _read_all_facts(db_path: Path) -> list[Fact]:
    with SqliteStore(path=db_path, serialize=Fact.to_dict, deserialize=Fact.from_dict) as store:
        return store.since(0)


class TestEmit:
    def test_fact_construction_and_kv_parsing(self, tmp_path, monkeypatch, capsys):
        home = tmp_path / "home"
        _write_vertex(home, "session", store="./data/session.db")
        monkeypatch.setenv("LOOPS_HOME", str(home))
        monkeypatch.delenv("LOOPS_OBSERVER", raising=False)

        fixed = py_datetime(2025, 1, 2, 3, 4, 5, tzinfo=timezone.utc)

        class FakeDateTime:
            @classmethod
            def now(cls, tz=None):
                return fixed

        import loops.main as loops_main

        monkeypatch.setattr(loops_main, "datetime", FakeDateTime)

        result = main(
            [
                "session",
                "emit",
                "decision",
                "topic=sigil",
                "{{var}} over ${var}",
                "--dry-run",
            ]
        )
        assert result == 0
        captured = capsys.readouterr()
        d = json.loads(captured.out)
        assert d["kind"] == "decision"
        assert d["observer"] == ""
        assert d["origin"] == ""
        assert d["ts"] == fixed.timestamp()
        assert d["payload"]["topic"] == "sigil"
        assert d["payload"]["message"] == "{{var}} over ${var}"

    def test_value_with_spaces_if_quoted(self, tmp_path, monkeypatch, capsys):
        home = tmp_path / "home"
        _write_vertex(home, "session", store="./data/session.db")
        monkeypatch.setenv("LOOPS_HOME", str(home))

        result = main(
            [
                "session",
                "emit",
                "change",
                "summary=structural AST",
                "--dry-run",
            ]
        )
        assert result == 0
        d = json.loads(capsys.readouterr().out)
        assert d["payload"]["summary"] == "structural AST"

    def test_store_injection_round_trip(self, tmp_path, monkeypatch):
        home = tmp_path / "home"
        vertex_path = _write_vertex(home, "session", store="./data/session.db")
        monkeypatch.setenv("LOOPS_HOME", str(home))

        result = main(
            [
                "session",
                "emit",
                "task",
                "name=fix/review",
                "status=merged",
            ]
        )
        assert result == 0

        db_path = (vertex_path.parent / "data" / "session.db").resolve()
        facts = _read_all_facts(db_path)
        assert len(facts) == 1
        assert facts[0].kind == "task"
        assert dict(facts[0].payload) == {"name": "fix/review", "status": "merged"}

    def test_dry_run_prints_without_storing(self, tmp_path, monkeypatch, capsys):
        home = tmp_path / "home"
        vertex_path = _write_vertex(home, "session", store="./data/session.db")
        monkeypatch.setenv("LOOPS_HOME", str(home))

        db_path = (vertex_path.parent / "data" / "session.db").resolve()
        assert not db_path.exists()

        result = main(
            [
                "session",
                "emit",
                "thread",
                "name=env-passthrough",
                "status=open",
                "literal override bug",
                "--dry-run",
            ]
        )
        assert result == 0
        out = capsys.readouterr().out
        assert json.loads(out)["payload"]["message"] == "literal override bug"
        assert not db_path.exists()

    def test_missing_store_clause_errors(self, tmp_path, monkeypatch, capsys):
        home = tmp_path / "home"
        _write_vertex(home, "session", store=None)
        monkeypatch.setenv("LOOPS_HOME", str(home))

        result = main(["session", "emit", "decision", "topic=sigil"])
        assert result == 1
        captured = capsys.readouterr()
        assert "vertex has no store configured" in captured.err

    def test_observer_flag(self, tmp_path, monkeypatch):
        home = tmp_path / "home"
        vertex_path = _write_vertex(home, "session", store="./data/session.db")
        monkeypatch.setenv("LOOPS_HOME", str(home))
        monkeypatch.delenv("LOOPS_OBSERVER", raising=False)

        result = main(
            [
                "session",
                "emit",
                "decision",
                "--observer",
                "human",
                "topic=sigil",
            ]
        )
        assert result == 0

        db_path = (vertex_path.parent / "data" / "session.db").resolve()
        facts = _read_all_facts(db_path)
        assert facts[0].observer == "human"


class TestObserverResolution:
    """Observer resolution from .vertex declarations."""

    def _write_vertex_with_observers(
        self, home: Path, name: str, *, observers_kdl: str
    ) -> Path:
        vdir = home / name
        vdir.mkdir(parents=True)
        vertex_path = vdir / f"{name}.vertex"
        vertex_path.write_text(
            f'name "{name}"\n'
            'store "./data/session.db"\n'
            f"{observers_kdl}\n"
            "loops {\n"
            '  counter { fold { count "inc" } }\n'
            "}\n"
        )
        return vertex_path

    def test_observer_from_global_dotvertex(self, tmp_path, monkeypatch, capsys):
        """Single observer in global .vertex auto-resolves."""
        home = tmp_path / "home"
        home.mkdir(parents=True)
        _write_vertex(home, "session", store="./data/session.db")

        # Write global .vertex with observer
        (home / ".vertex").write_text(
            'discover "./**/*.vertex"\n\n'
            'observers {\n  test-human { }\n}\n'
        )

        monkeypatch.setenv("LOOPS_HOME", str(home))
        monkeypatch.delenv("LOOPS_OBSERVER", raising=False)
        # Ensure cwd has no .loops/.vertex in ancestry (avoid project-level pickup)
        monkeypatch.chdir(tmp_path)

        result = main(
            ["session", "emit", "decision", "topic=test", "--dry-run"]
        )
        assert result == 0
        d = json.loads(capsys.readouterr().out)
        assert d["observer"] == "test-human"

    def test_observer_env_overrides_declaration(self, tmp_path, monkeypatch, capsys):
        """LOOPS_OBSERVER env var selects observer (must still be declared)."""
        home = tmp_path / "home"
        home.mkdir(parents=True)
        _write_vertex(home, "session", store="./data/session.db")

        (home / ".vertex").write_text(
            'discover "./**/*.vertex"\n\n'
            'observers {\n  declared-obs { }\n  env-obs { }\n}\n'
        )

        monkeypatch.setenv("LOOPS_HOME", str(home))
        monkeypatch.setenv("LOOPS_OBSERVER", "env-obs")

        result = main(
            ["session", "emit", "decision", "topic=test", "--dry-run"]
        )
        assert result == 0
        d = json.loads(capsys.readouterr().out)
        assert d["observer"] == "env-obs"

    def test_observer_flag_overrides_all(self, tmp_path, monkeypatch, capsys):
        """--observer flag takes highest priority (must still be declared)."""
        home = tmp_path / "home"
        home.mkdir(parents=True)
        _write_vertex(home, "session", store="./data/session.db")

        (home / ".vertex").write_text(
            'discover "./**/*.vertex"\n\n'
            'observers {\n  declared-obs { }\n  flag-obs { }\n}\n'
        )

        monkeypatch.setenv("LOOPS_HOME", str(home))
        monkeypatch.setenv("LOOPS_OBSERVER", "env-obs")

        result = main(
            [
                "session", "emit", "decision",
                "--observer", "flag-obs",
                "topic=test", "--dry-run",
            ]
        )
        assert result == 0
        d = json.loads(capsys.readouterr().out)
        assert d["observer"] == "flag-obs"

    def test_grant_potential_rejects_invalid_kind(self, tmp_path, monkeypatch, capsys):
        """Observer with grant.potential rejects kinds outside the set."""
        home = tmp_path / "home"
        vertex_path = self._write_vertex_with_observers(
            home, "session",
            observers_kdl='observers {\n  ci-bot {\n    grant {\n      potential "change" "log"\n    }\n  }\n}',
        )

        monkeypatch.setenv("LOOPS_HOME", str(home))
        monkeypatch.delenv("LOOPS_OBSERVER", raising=False)

        result = main(
            [
                "session", "emit", "decision",
                "--observer", "ci-bot",
                "topic=test",
            ]
        )
        assert result == 1
        err = capsys.readouterr().err
        assert "cannot emit kind" in err
        assert "decision" in err

    def test_grant_potential_allows_valid_kind(self, tmp_path, monkeypatch):
        """Observer with grant.potential accepts kinds in the set."""
        home = tmp_path / "home"
        self._write_vertex_with_observers(
            home, "session",
            observers_kdl='observers {\n  ci-bot {\n    grant {\n      potential "change" "counter"\n    }\n  }\n}',
        )

        monkeypatch.setenv("LOOPS_HOME", str(home))
        monkeypatch.delenv("LOOPS_OBSERVER", raising=False)

        result = main(
            [
                "session", "emit", "counter",
                "--observer", "ci-bot",
                "count=1",
            ]
        )
        assert result == 0

    def test_undeclared_observer_rejected(self, tmp_path, monkeypatch, capsys):
        """Undeclared observer is rejected when observers block exists."""
        home = tmp_path / "home"
        self._write_vertex_with_observers(
            home, "session",
            observers_kdl='observers {\n  kyle { }\n}',
        )

        monkeypatch.setenv("LOOPS_HOME", str(home))
        monkeypatch.delenv("LOOPS_OBSERVER", raising=False)

        result = main(
            [
                "session", "emit", "decision",
                "--observer", "unknown-user",
                "topic=test",
            ]
        )
        assert result == 1
        err = capsys.readouterr().err
        assert "not declared" in err
        assert "unknown-user" in err
