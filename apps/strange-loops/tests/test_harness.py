"""Tests for harness runner — named harness resolution + execution."""

from __future__ import annotations

import time
from pathlib import Path

import pytest
from atoms import Fact
from engine import SqliteStore

from strange_loops.harness import _build_command, _find_loop, run_harness, spawn


def _read_all(db_path: Path) -> list[dict]:
    with SqliteStore(path=db_path, serialize=Fact.to_dict, deserialize=Fact.from_dict) as store:
        return [Fact.to_dict(f) for f in store.since(0)]


class TestFindLoop:
    def test_find_loop_exists(self):
        path = _find_loop("shell")
        assert path.exists()
        assert path.name == "shell.loop"

    def test_find_loop_missing(self):
        with pytest.raises(FileNotFoundError, match="Harness 'nonexistent' not found"):
            _find_loop("nonexistent")

    def test_find_loop_all_harnesses(self):
        for name in ("shell", "sonnet", "codex", "gemini-flash"):
            path = _find_loop(name)
            assert path.exists(), f"{name}.loop not found"


class TestBuildCommand:
    def test_substitutes_prompt(self):
        result = _build_command("claude -p {{prompt}}", "hello world")
        assert result == "claude -p 'hello world'"

    def test_substitutes_command_raw(self):
        result = _build_command("{{command}}", "echo hello")
        assert result == "echo hello"

    def test_escapes_quotes(self):
        result = _build_command("run {{prompt}}", 'it\'s a "test"')
        # shlex.quote wraps in single quotes, escaping internal single quotes
        assert "it" in result
        assert "test" in result
        # Must not contain unescaped quotes that would break shell
        assert result.startswith("run ")

    def test_both_placeholders(self):
        result = _build_command("{{command}} && echo {{prompt}}", "hi")
        assert result == "hi && echo hi"


class TestRunHarness:
    def test_captures_output(self, tmp_path: Path):
        db = tmp_path / "data" / "tasks.db"
        wt = tmp_path / "workdir"
        wt.mkdir()

        run_harness(db, "test-task", wt, "echo hello", "shell", "tester")

        facts = _read_all(db)
        output_facts = [f for f in facts if f["kind"] == "worker.output"]
        assert any(f["payload"]["line"] == "hello" for f in output_facts)

    def test_emits_complete_fact(self, tmp_path: Path):
        db = tmp_path / "data" / "tasks.db"
        wt = tmp_path / "workdir"
        wt.mkdir()

        run_harness(db, "test-task", wt, "echo done", "shell", "tester")

        facts = _read_all(db)
        kinds = [f["kind"] for f in facts]
        assert "worker.output" in kinds
        assert "worker.output.complete" in kinds

    def test_captures_exit_code_success(self, tmp_path: Path):
        db = tmp_path / "data" / "tasks.db"
        wt = tmp_path / "workdir"
        wt.mkdir()

        code = run_harness(db, "test-task", wt, "true", "shell", "tester")
        assert code == 0

        facts = _read_all(db)
        complete = [f for f in facts if f["kind"] == "worker.output.complete"][0]
        assert complete["payload"]["status"] == "ok"
        assert complete["payload"]["returncode"] == 0

    def test_captures_exit_code_failure(self, tmp_path: Path):
        db = tmp_path / "data" / "tasks.db"
        wt = tmp_path / "workdir"
        wt.mkdir()

        code = run_harness(db, "test-task", wt, "false", "shell", "tester")
        assert code != 0

        facts = _read_all(db)
        complete = [f for f in facts if f["kind"] == "worker.output.complete"][0]
        assert complete["payload"]["status"] == "error"
        assert complete["payload"]["returncode"] != 0
        assert "error" in complete["payload"]


class TestEachLoopParses:
    """Verify all .loop files in harnesses/ parse without error."""

    def test_each_loop_parses(self):
        from lang import parse_loop_file

        harness_dir = Path(__file__).resolve().parent.parent / "loops" / "harnesses"
        loop_files = sorted(harness_dir.glob("*.loop"))
        assert len(loop_files) >= 4, f"Expected at least 4 .loop files, found {len(loop_files)}"

        for loop_path in loop_files:
            loop = parse_loop_file(loop_path)
            assert loop.kind == "worker.output", f"{loop_path.stem}: unexpected kind {loop.kind}"
            assert loop.source is not None, f"{loop_path.stem}: missing source"
            assert loop.observer, f"{loop_path.stem}: missing observer"
            assert loop.format == "lines", f"{loop_path.stem}: unexpected format {loop.format}"


class TestSpawn:
    def test_returns_pid(self, tmp_path: Path):
        db = tmp_path / "data" / "tasks.db"
        wt = tmp_path / "workdir"
        wt.mkdir()

        pid = spawn(db, "test-task", wt, "echo spawned", "shell", "tester")
        assert isinstance(pid, int)
        assert pid > 0

        # Wait for the spawned process to finish
        for _ in range(50):
            time.sleep(0.1)
            if db.exists():
                facts = _read_all(db)
                if any(f["kind"] == "worker.output.complete" for f in facts):
                    break

        facts = _read_all(db)
        assert any(f["kind"] == "worker.output.complete" for f in facts)

    def test_emits_worker_started(self, tmp_path: Path):
        db = tmp_path / "data" / "tasks.db"
        wt = tmp_path / "workdir"
        wt.mkdir()

        pid = spawn(db, "test-task", wt, "echo hi", "shell", "tester")

        # worker.started is emitted synchronously before return
        facts = _read_all(db)
        started = [f for f in facts if f["kind"] == "worker.started"]
        assert len(started) == 1
        assert started[0]["payload"]["task"] == "test-task"
        assert started[0]["payload"]["pid"] == pid
