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


# --- Static branch — minimal smoke -----------------------------------------


class TestStaticBranchSmoke:
    """Static-branch is fully exercised once a real view migrates in step 4.
    Step 0 only verifies that unknown lenses produce a clean error rather
    than crashing."""

    def test_unknown_lens_reports_error(self):
        op = Operation(
            verb="read", fn=lambda: {"sections": []},
            render_lens="this-lens-does-not-exist",
        )
        reporter = BufferReporter()
        rc = dispatch(op, reporter=reporter)
        assert rc == 2
        assert any("not found" in line.lower() for line in reporter.err_lines)
