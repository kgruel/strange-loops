"""Tests for health check feedback handler and lens."""

from __future__ import annotations

import io
import time
from pathlib import Path

from atoms import Fact
from engine import SqliteStore
from engine.compiler import compile_sources_block
from lang.ast import InlineSource, SourcesBlock
from painted import Zoom
from painted.core.writer import print_block

import importlib.util
import sys

# health.py graduated to config/dev/ — load it from file path
_health_path = Path(__file__).resolve().parents[3] / "config" / "dev" / "health.py"
_spec = importlib.util.spec_from_file_location("config_dev_health", _health_path)
_health_mod = importlib.util.module_from_spec(_spec)
sys.modules["config_dev_health"] = _health_mod
_spec.loader.exec_module(_health_mod)

CheckStep = _health_mod.CheckStep
health_lens = _health_mod.health_lens
health_view = _health_mod.health_view
run_checks = _health_mod.run_checks
run_sequential_checks = _health_mod.run_sequential_checks


def _block_text(block) -> str:
    """Render a Block into plain text."""
    buf = io.StringIO()
    print_block(block, buf, use_ansi=False)
    return buf.getvalue()


def _read_all_facts(db_path: Path) -> list[Fact]:
    with SqliteStore(
        path=db_path, serialize=Fact.to_dict, deserialize=Fact.from_dict
    ) as store:
        return store.since(0)


def _seed_vertex(workspace: Path) -> Path:
    """Create a minimal vertex + data dir, return store path."""
    vertex = workspace / "test.vertex"
    vertex.write_text(
        'name "test"\n'
        'store "./data/test.db"\n'
    )
    (workspace / "data").mkdir()
    return workspace / "data" / "test.db"


class TestRunChecks:
    def test_passing_checks_emit_facts(self, tmp_path):
        store_path = _seed_vertex(tmp_path)
        steps = [
            CheckStep("lint", "true"),
            CheckStep("test", "echo ok"),
        ]

        results = run_checks(store_path, steps)

        assert len(results) == 2
        assert results[0]["kind"] == "lint.result"
        assert results[0]["payload"]["status"] == "passed"
        assert results[1]["kind"] == "test.result"
        assert results[1]["payload"]["status"] == "passed"
        assert results[1]["payload"]["duration_s"] >= 0

        # Facts persisted to store
        facts = _read_all_facts(store_path)
        assert len(facts) == 2
        assert facts[0].kind == "lint.result"
        assert facts[1].kind == "test.result"

    def test_failing_check_stops_sequence(self, tmp_path):
        store_path = _seed_vertex(tmp_path)
        steps = [
            CheckStep("lint", "true"),
            CheckStep("test", "false"),
            CheckStep("arch", "true"),
        ]

        results = run_checks(store_path, steps)

        assert len(results) == 2
        assert results[0]["payload"]["status"] == "passed"
        assert results[1]["payload"]["status"] == "failed"
        # arch never ran
        facts = _read_all_facts(store_path)
        assert len(facts) == 2

    def test_captures_stdout(self, tmp_path):
        store_path = _seed_vertex(tmp_path)
        steps = [CheckStep("echo", "echo hello world")]

        results = run_checks(store_path, steps)

        assert "hello world" in results[0]["payload"]["output"]

    def test_captures_stderr_on_failure(self, tmp_path):
        store_path = _seed_vertex(tmp_path)
        steps = [CheckStep("fail", "echo oops >&2; false")]

        results = run_checks(store_path, steps)

        assert results[0]["payload"]["status"] == "failed"
        assert "oops" in results[0]["payload"]["output"]

    def test_custom_observer(self, tmp_path):
        store_path = _seed_vertex(tmp_path)
        steps = [CheckStep("lint", "true")]

        results = run_checks(store_path, steps, observer="ci")

        assert results[0]["observer"] == "ci"

    def test_custom_cwd(self, tmp_path):
        store_path = _seed_vertex(tmp_path)
        subdir = tmp_path / "project"
        subdir.mkdir()
        (subdir / "marker.txt").write_text("here")
        steps = [CheckStep("check", "cat marker.txt")]

        results = run_checks(store_path, steps, cwd=subdir)

        assert results[0]["payload"]["status"] == "passed"
        assert "here" in results[0]["payload"]["output"]


class TestHealthLens:
    def _result_payload(self, status="passed", duration_s=1.5, output="all good"):
        return {"status": status, "duration_s": duration_s, "output": output}

    def test_minimal_shows_name_and_status(self):
        result = health_lens("lint.result", self._result_payload(), Zoom.MINIMAL)
        assert isinstance(result, str)
        assert "lint" in result
        assert "passed" in result

    def test_non_result_kind_returns_empty(self):
        result = health_lens("decision", {}, Zoom.SUMMARY)
        assert result == ""

    def test_summary_returns_block(self):
        result = health_lens("test.result", self._result_payload(), Zoom.SUMMARY)
        # At SUMMARY zoom, returns a Block (styled output)
        from painted import Block
        assert isinstance(result, Block)

    def test_detailed_returns_summary_only(self):
        """DETAILED lens returns summary — record_line handles output continuation."""
        payload = self._result_payload(output="line1\nline2\nline3")
        result = health_lens("test.result", payload, Zoom.DETAILED)
        from painted import Block
        assert isinstance(result, Block)
        text = _block_text(result)
        # Lens returns name + status + duration, NOT the output
        assert "test" in text
        assert "passed" in text
        assert "line1" not in text

    def test_full_returns_summary_only(self):
        """FULL lens returns summary — record_line handles full field rendering."""
        payload = self._result_payload(output="line1\nline2")
        result = health_lens("test.result", payload, Zoom.FULL)
        text = _block_text(result)
        assert "test" in text
        assert "passed" in text
        assert "line1" not in text


class TestHealthView:
    def _make_results(self, *statuses: str) -> list[dict]:
        results = []
        names = ["lint", "test", "arch"]
        for i, status in enumerate(statuses):
            results.append({
                "kind": f"{names[i]}.result",
                "ts": time.time(),
                "payload": {"status": status, "output": "", "duration_s": 0.5},
                "observer": "dev-check",
            })
        return results

    def test_empty_results(self):
        block = health_view([], Zoom.SUMMARY, 80)
        assert "No check results" in _block_text(block)

    def test_minimal_shows_all_names(self):
        results = self._make_results("passed", "passed")
        block = health_view(results, Zoom.MINIMAL, 80)
        text = _block_text(block)
        assert "lint" in text
        assert "test" in text

    def test_summary_renders_blocks(self):
        results = self._make_results("passed", "failed")
        block = health_view(results, Zoom.SUMMARY, 80)
        # Should render without error
        assert block is not None


def _make_seq_block(*steps: tuple[str, str]) -> SourcesBlock:
    """Build a SourcesBlock from (command, kind) pairs."""
    return SourcesBlock(
        mode="sequential",
        sources=tuple(InlineSource(command=cmd, kind=kind) for cmd, kind in steps),
    )


class TestRunSequentialChecks:
    """Tests for run_sequential_checks — the vertex-aware async runner."""

    def test_passing_steps(self, tmp_path):
        store_path = _seed_vertex(tmp_path)
        block = _make_seq_block(
            ("echo ok", "lint.result"),
            ("true", "test.result"),
        )
        seq, _cadence = compile_sources_block(block, "check")

        results = run_sequential_checks(seq, store_path)

        assert len(results) == 2
        assert results[0]["kind"] == "lint.result"
        assert results[0]["payload"]["status"] == "passed"
        assert results[1]["kind"] == "test.result"
        assert results[1]["payload"]["status"] == "passed"

        # Facts persisted
        facts = _read_all_facts(store_path)
        assert len(facts) == 2

    def test_failure_stops_sequence(self, tmp_path):
        store_path = _seed_vertex(tmp_path)
        block = _make_seq_block(
            ("true", "lint.result"),
            ("false", "test.result"),
            ("true", "arch.result"),
        )
        seq, _cadence = compile_sources_block(block, "check")

        results = run_sequential_checks(seq, store_path)

        assert len(results) == 2
        assert results[0]["payload"]["status"] == "passed"
        assert results[1]["payload"]["status"] == "failed"
        # arch never ran
        facts = _read_all_facts(store_path)
        assert len(facts) == 2

    def test_captures_stdout(self, tmp_path):
        store_path = _seed_vertex(tmp_path)
        block = _make_seq_block(("echo hello world", "echo.result"),)
        seq, _cadence = compile_sources_block(block, "check")

        results = run_sequential_checks(seq, store_path)

        assert results[0]["payload"]["status"] == "passed"
        assert "hello world" in results[0]["payload"]["output"]

    def test_captures_stderr_on_failure(self, tmp_path):
        store_path = _seed_vertex(tmp_path)
        block = _make_seq_block(("echo oops >&2; false", "fail.result"),)
        seq, _cadence = compile_sources_block(block, "check")

        results = run_sequential_checks(seq, store_path)

        assert results[0]["payload"]["status"] == "failed"
        assert "oops" in results[0]["payload"]["output"]

    def test_duration_is_positive(self, tmp_path):
        store_path = _seed_vertex(tmp_path)
        block = _make_seq_block(("echo fast", "speed.result"),)
        seq, _cadence = compile_sources_block(block, "check")

        results = run_sequential_checks(seq, store_path)

        assert results[0]["payload"]["duration_s"] >= 0

    def test_custom_observer(self, tmp_path):
        store_path = _seed_vertex(tmp_path)
        block = _make_seq_block(("true", "lint.result"),)
        seq, _cadence = compile_sources_block(block, "check")

        results = run_sequential_checks(seq, store_path, observer="ci")

        assert results[0]["observer"] == "ci"

    def test_results_compatible_with_health_view(self, tmp_path):
        """Results from run_sequential_checks render through health_view."""
        store_path = _seed_vertex(tmp_path)
        block = _make_seq_block(
            ("echo all good", "lint.result"),
            ("true", "test.result"),
        )
        seq, _cadence = compile_sources_block(block, "check")

        results = run_sequential_checks(seq, store_path)
        view = health_view(results, Zoom.SUMMARY, 80)

        assert view is not None
        text = _block_text(view)
        assert "lint" in text
        assert "test" in text
