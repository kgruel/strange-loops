"""Tests for store helpers."""

from __future__ import annotations

import argparse
from pathlib import Path

from atoms import Fact
from engine import SqliteStore

from strange_loops.store import (
    emit_fact,
    format_date,
    format_ts,
    observer,
    parse_duration,
    render_log_entry,
    require_store,
    store_path,
    store_path_for,
)

import pytest


def _read_all(db_path: Path) -> list[dict]:
    with SqliteStore(path=db_path, serialize=Fact.to_dict, deserialize=Fact.from_dict) as store:
        return [Fact.to_dict(f) for f in store.since(0)]


class TestObserver:
    def test_flag(self):
        ns = argparse.Namespace(observer="alice")
        assert observer(ns) == "alice"

    def test_env_strange_loops(self, monkeypatch):
        monkeypatch.setenv("STRANGE_LOOPS_OBSERVER", "bob")
        assert observer() == "bob"

    def test_env_loops_fallback(self, monkeypatch):
        monkeypatch.delenv("STRANGE_LOOPS_OBSERVER", raising=False)
        monkeypatch.setenv("LOOPS_OBSERVER", "carol")
        assert observer() == "carol"

    def test_default_empty(self, monkeypatch):
        monkeypatch.delenv("STRANGE_LOOPS_OBSERVER", raising=False)
        monkeypatch.delenv("LOOPS_OBSERVER", raising=False)
        assert observer() == ""


class TestStorePath:
    def test_returns_data_tasks_db(self, workspace: Path, monkeypatch):
        monkeypatch.chdir(workspace)
        assert store_path() == workspace / "data" / "tasks.db"


class TestEmitFact:
    def test_creates_store_and_emits(self, tmp_path: Path):
        db = tmp_path / "data" / "tasks.db"
        emit_fact(db, "test.kind", "tester", {"key": "val"})
        facts = _read_all(db)
        assert len(facts) == 1
        assert facts[0]["kind"] == "test.kind"
        assert facts[0]["payload"]["key"] == "val"


class TestRequireStore:
    def test_raises_when_missing(self, tmp_path: Path):
        with pytest.raises(FileNotFoundError, match="No session initialized"):
            require_store(tmp_path / "nonexistent.db")

    def test_passes_when_exists(self, tmp_path: Path):
        db = tmp_path / "tasks.db"
        db.touch()
        require_store(db)  # should not raise


class TestRequireStoreCustomMessage:
    def test_custom_message(self, tmp_path: Path):
        with pytest.raises(FileNotFoundError, match="custom error"):
            require_store(tmp_path / "nope.db", message="custom error")


class TestParseDuration:
    def test_days(self):
        assert parse_duration("7d") == 7 * 86400

    def test_hours(self):
        assert parse_duration("24h") == 24 * 3600

    def test_invalid(self):
        with pytest.raises(ValueError, match="Invalid duration"):
            parse_duration("nope")


class TestStorePathFor:
    def test_resolves_tasks_vertex(self):
        path = store_path_for("tasks")
        assert path.name == "tasks.db"
        assert "data" in str(path)

    def test_resolves_project_vertex(self):
        path = store_path_for("project")
        assert path.name == "project.db"
        assert "data" in str(path)

    def test_raises_for_missing_vertex(self):
        with pytest.raises(Exception):
            store_path_for("nonexistent")


class TestFormatHelpers:
    def test_format_ts(self):
        from datetime import datetime, timezone

        dt = datetime(2026, 2, 28, 14, 30, 0, tzinfo=timezone.utc)
        assert format_ts(dt) == "14:30"

    def test_format_date(self):
        from datetime import datetime, timezone

        dt = datetime(2026, 2, 28, 14, 30, 0, tzinfo=timezone.utc)
        assert format_date(dt) == "2026-02-28"


class TestRenderLogEntry:
    def test_renders_fact(self, capsys):
        from datetime import datetime, timezone

        fact = {
            "kind": "test.kind",
            "ts": datetime(2026, 2, 28, 14, 30, 0, tzinfo=timezone.utc),
            "observer": "alice",
            "payload": {"key": "val"},
        }
        render_log_entry(fact)
        out = capsys.readouterr().out
        assert "14:30" in out
        assert "test.kind" in out
        assert "alice" in out
        assert "key=val" in out

    def test_renders_without_observer(self, capsys):
        from datetime import datetime, timezone

        fact = {
            "kind": "decision",
            "ts": datetime(2026, 2, 28, 10, 0, 0, tzinfo=timezone.utc),
            "observer": "",
            "payload": {"topic": "auth"},
        }
        render_log_entry(fact)
        out = capsys.readouterr().out
        assert "decision" in out
        assert "()" not in out
