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


# --- Surface interposition (S2) --------------------------------------------


class TestSurfaceInterposition:
    """The S2 keystone: the default fold path routes through the Surface so
    plain and --json encode the SAME structured rows. --json is a HARD BREAK
    (to_dict(surface), not the raw FoldState). The gate keeps vertex-decl /
    --lens-override fold lenses (and non-FoldState shapes) on the raw path."""

    @staticmethod
    def _state():
        from atoms import FoldItem, FoldSection, FoldState

        return FoldState(
            sections=(
                FoldSection(
                    kind="decision", fold_type="by", key_field="topic",
                    items=(
                        FoldItem(payload={"topic": "design/a", "message": "body a"},
                                 ts=100.0, n=2, refs=("decision/design/b",)),
                        FoldItem(payload={"topic": "design/b", "message": "body b"},
                                 ts=90.0, n=1),
                    ),
                ),
            ),
            vertex="t",
        )

    def test_json_gate_pass_is_to_dict_surface(self):
        """--json on the default fold path deep-equals to_dict(project(state))
        — the hard break + behavioral parity."""
        import json

        from painted.cli import Format

        from loops.surface import project, to_dict

        state = self._state()
        op = Operation(
            verb="read", fn=lambda: state, render_lens="fold",
            format=Format.JSON,
        )
        reporter = BufferReporter()
        rc = dispatch(op, reporter=reporter)
        assert rc == 0
        emitted = json.loads(reporter.out_lines[0])
        assert emitted == to_dict(project(state))
        # the structured shape, not the raw FoldState
        assert "rows" in emitted and "sections" not in emitted
        a = next(r for r in emitted["rows"] if r["key"] == "design/a")
        assert a["salience"] == 2 and a["address"] == "decision/design/a"

    def test_json_gate_fail_falls_back_to_raw(self):
        """A --lens override (not the built-in) fails the gate → --json keeps
        the legacy raw FoldState dump, not the Surface encoding."""
        import json

        from painted.cli import Format

        state = self._state()
        op = Operation(
            verb="read", fn=lambda: state, render_lens="fold",
            lens_override="autoresearch",  # resolvable, != built-in fold
            format=Format.JSON,
        )
        reporter = BufferReporter()
        rc = dispatch(op, reporter=reporter)
        assert rc == 0
        raw = json.loads(reporter.out_lines[0])
        # raw FoldState dump carries "sections"; the Surface shape does not
        assert "sections" in raw
        assert "rows" not in raw

    def test_text_gate_pass_renders_block(self):
        """Gate-pass text path projects → built-in fold_view(Surface) → Block."""
        state = self._state()
        op = Operation(verb="read", fn=lambda: state, render_lens="fold")
        reporter = BufferReporter()
        rc = dispatch(op, reporter=reporter)
        assert rc == 0
        assert reporter.blocks  # a rendered Block landed
        from loops.lenses.fold import fold_view
        from loops.surface import project
        from painted import Zoom
        # parity: the dispatched render equals fold_view(project(state))
        from .golden.helpers import block_to_text
        expected = block_to_text(fold_view(project(state), Zoom.SUMMARY, 80))
        assert block_to_text(reporter.blocks[0]) == expected

    def test_text_gate_fail_override_still_renders(self):
        """A --lens override fails the gate but still renders via the lens's
        polymorphic front door (autoresearch re-exports fold_view)."""
        state = self._state()
        op = Operation(
            verb="read", fn=lambda: state, render_lens="fold",
            lens_override="autoresearch",
        )
        reporter = BufferReporter()
        rc = dispatch(op, reporter=reporter)
        assert rc == 0
        assert reporter.blocks
