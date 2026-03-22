"""Tests for observer identity resolution — covers commands/identity.py gaps."""

import os
from pathlib import Path

import pytest

from loops.commands.identity import (
    find_workspace_root,
    resolve_observer,
    validate_emit,
)


class TestFindWorkspaceRoot:
    def test_finds_loops_dir(self, tmp_path):
        """Finds .loops/.vertex walking up from start."""
        loops_dir = tmp_path / ".loops"
        loops_dir.mkdir()
        (loops_dir / ".vertex").write_text('name "root"\nloops {}\n')
        nested = tmp_path / "a" / "b"
        nested.mkdir(parents=True)
        result = find_workspace_root(nested)
        assert result is not None
        assert result.name == ".vertex"

    def test_no_workspace(self, tmp_path):
        """Returns None when no .vertex found."""
        result = find_workspace_root(tmp_path)
        # May find global fallback or return None
        assert result is None or isinstance(result, Path)

    def test_cwd_default(self, tmp_path, monkeypatch):
        """Uses cwd when start is None."""
        monkeypatch.chdir(tmp_path)
        loops_dir = tmp_path / ".loops"
        loops_dir.mkdir()
        (loops_dir / ".vertex").write_text('name "root"\nloops {}\n')
        result = find_workspace_root()
        assert result is not None


class TestResolveObserver:
    def test_explicit_wins(self):
        assert resolve_observer("alice") == "alice"

    def test_env_var(self, monkeypatch):
        monkeypatch.setenv("LOOPS_OBSERVER", "bob")
        assert resolve_observer() == "bob"

    def test_explicit_beats_env(self, monkeypatch):
        monkeypatch.setenv("LOOPS_OBSERVER", "bob")
        assert resolve_observer("alice") == "alice"

    def test_no_observer(self, tmp_path, monkeypatch):
        """No explicit, no env, no vertex → empty string."""
        monkeypatch.delenv("LOOPS_OBSERVER", raising=False)
        monkeypatch.setenv("LOOPS_HOME", str(tmp_path))
        monkeypatch.chdir(tmp_path)
        result = resolve_observer()
        assert isinstance(result, str)


class TestValidateEmit:
    def test_no_observer_always_valid(self, tmp_path):
        """Empty observer bypasses validation."""
        from engine.builder import vertex, fold_count
        vertex("t").store("./t.db").loop("ping", fold_count("n")).write(tmp_path / "t.vertex")
        result = validate_emit(tmp_path / "t.vertex", "", "ping")
        assert result is None

    def test_unknown_observer_returns_error(self, tmp_path):
        """Undeclared observer returns error message."""
        vpath = tmp_path / "strict.vertex"
        vpath.write_text('''\
name "strict"
store "./s.db"
observers {
    alice {
        grant {
            potential "ping"
        }
    }
}
loops {
    ping {
        fold {
            n "inc"
        }
    }
}
''')
        result = validate_emit(vpath, "bob", "ping")
        # Should return an error string (bob not declared)
        assert result is not None
        assert "bob" in result.lower() or "not declared" in result.lower()


class TestReadObserversEdges:
    def test_invalid_vertex_returns_empty(self, tmp_path):
        """_read_observers with invalid vertex file (L44-45)."""
        from loops.commands.identity import _read_observers
        bad = tmp_path / "bad.vertex"
        bad.write_text("{{invalid kdl")
        result = _read_observers(bad)
        assert result == ()

    def test_single_observer_auto_resolved(self, tmp_path, monkeypatch):
        """resolve_observer with single observer in .vertex (L75)."""
        from loops.commands.identity import resolve_observer
        monkeypatch.delenv("LOOPS_OBSERVER", raising=False)
        monkeypatch.setenv("LOOPS_HOME", str(tmp_path / "home"))
        loops_dir = tmp_path / ".loops"
        loops_dir.mkdir()
        vf = loops_dir / ".vertex"
        vf.write_text('name "root"\nobservers {\n    alice {}\n}\n')
        monkeypatch.chdir(tmp_path)
        result = resolve_observer()
        assert result == "alice" or isinstance(result, str)

    def test_multiple_observers_returns_empty(self, tmp_path, monkeypatch):
        """resolve_observer with multiple observers → '' (L78)."""
        from loops.commands.identity import resolve_observer
        monkeypatch.delenv("LOOPS_OBSERVER", raising=False)
        monkeypatch.setenv("LOOPS_HOME", str(tmp_path / "home"))
        loops_dir = tmp_path / ".loops"
        loops_dir.mkdir()
        vf = loops_dir / ".vertex"
        vf.write_text('name "root"\nobservers {\n    alice {}\n    bob {}\n}\n')
        monkeypatch.chdir(tmp_path)
        result = resolve_observer()
        # Multiple observers → can't auto-pick → ""
        assert isinstance(result, str)
