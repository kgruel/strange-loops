"""Tests for cli.dispatch — Operation execution branches.

Step 0 covers the action branch end-to-end with BufferReporter. The
static/live/interactive branches are exercised by view-level tests as
each view migrates (steps 3+).
"""
from __future__ import annotations

from loops.cli.dispatch import dispatch
from loops.cli.operation import Operation
from loops.cli.output import BufferReporter


# --- Action branch ---------------------------------------------------------


class TestActionBranch:
    def test_action_with_none_result_renders_nothing(self):
        called = {"n": 0}

        def fn():
            called["n"] += 1
            return None

        op = Operation(verb="emit", fn=fn)
        reporter = BufferReporter()
        rc = dispatch(op, reporter=reporter)
        assert rc == 0
        assert called["n"] == 1
        assert reporter.shown == []
        assert reporter.blocks == []
        assert reporter.err_lines == []

    def test_action_with_string_result_routes_through_show(self):
        op = Operation(verb="emit", fn=lambda: "receipt: stored")
        reporter = BufferReporter()
        rc = dispatch(op, reporter=reporter)
        assert rc == 0
        assert reporter.shown == ["receipt: stored"]

    def test_action_forwards_params_as_kwargs(self):
        captured = {}

        def fn(**kwargs):
            captured.update(kwargs)
            return None

        op = Operation(verb="emit", fn=fn, params={"a": 1, "b": "two"})
        dispatch(op, reporter=BufferReporter())
        assert captured == {"a": 1, "b": "two"}

    def test_action_returns_zero_on_success(self):
        op = Operation(verb="sync", fn=lambda: None)
        assert dispatch(op, reporter=BufferReporter()) == 0


# --- Interactive branch ----------------------------------------------------


class TestInteractiveBranch:
    def test_interactive_handler_invoked(self):
        called = {"n": 0}

        def handler() -> int:
            called["n"] += 1
            return 42

        op = Operation(
            verb="read",
            fn=lambda: None,
            render_lens="autoresearch",
            mode="interactive",
            interactive_handler=handler,
        )
        rc = dispatch(op, reporter=BufferReporter())
        assert called["n"] == 1
        assert rc == 42

    def test_interactive_without_handler_errors(self):
        op = Operation(
            verb="read", fn=lambda: None,
            render_lens="autoresearch", mode="interactive",
        )
        reporter = BufferReporter()
        rc = dispatch(op, reporter=reporter)
        assert rc == 2
        assert any("no handler" in line for line in reporter.err_lines)


# --- Live branch (stubbed sanity) ------------------------------------------


class TestLiveBranch:
    def test_live_without_stream_fn_errors(self):
        op = Operation(
            verb="read", fn=lambda: None,
            render_lens="fold", mode="live",
        )
        reporter = BufferReporter()
        rc = dispatch(op, reporter=reporter)
        assert rc == 2
        assert any("no stream_fn" in line for line in reporter.err_lines)

    def test_live_folds_onto_run_cli_surface(self, monkeypatch):
        """Live mode delegates to painted.run_cli with the surface tier.

        Locks the step-6 dissolution: loops no longer owns an InPlaceRenderer
        wrapper — the live loop is painted's run_cli(fetch_stream=,
        live_delivery="surface"). We capture the call rather than drive a
        real terminal (surface needs a TTY).
        """
        captured = {}

        def fake_run_cli(args, **kwargs):
            captured["args"] = args
            captured["kwargs"] = kwargs
            return 0

        import painted

        monkeypatch.setattr(painted, "run_cli", fake_run_cli)

        async def _stream():
            yield {"sections": (), "vertex": "x"}

        def stream_fn():
            return _stream()

        op = Operation(
            verb="read", fn=lambda: None,
            render_lens="fold", mode="live", stream_fn=stream_fn,
        )
        rc = dispatch(op, reporter=BufferReporter())
        assert rc == 0
        assert captured["args"] == ["--live"]
        assert captured["kwargs"]["live_delivery"] == "surface"
        assert captured["kwargs"]["fetch_stream"] is stream_fn
        assert callable(captured["kwargs"]["render"])
        assert callable(captured["kwargs"]["fetch"])


# --- Static branch — minimal smoke -----------------------------------------


class TestStaticBranchSmoke:
    """Static-branch is fully exercised once a real view migrates in step 4.
    Step 0 only verifies that unknown lenses produce a clean error rather
    than crashing."""

    def test_unknown_lens_reports_error(self, capsys):
        """Unknown explicit-named lens triggers the strict
        ``_resolve_render_fn → _exit_lens_not_found → sys.exit(2)`` path.

        Step 4 of the cli refactor wires dispatch through the strict
        resolver so explicit --lens NAME requests fail loudly rather
        than silently falling back to the default. The error goes to
        real stderr (not the Reporter), so we use capsys.
        """
        import pytest as _pytest

        op = Operation(
            verb="read", fn=lambda: {"sections": []},
            render_lens="fold",
            lens_override="this-lens-does-not-exist",
        )
        reporter = BufferReporter()
        with _pytest.raises(SystemExit) as exc_info:
            dispatch(op, reporter=reporter)
        assert exc_info.value.code == 2
        captured = capsys.readouterr()
        assert "this-lens-does-not-exist" in captured.err
