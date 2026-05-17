"""Tests for cli.operation — the Operation IR dataclass."""
from __future__ import annotations

from pathlib import Path

from loops.cli.operation import Operation


def _noop():
    return None


class TestOperationDefaults:
    def test_minimal_action(self):
        op = Operation(verb="emit", fn=_noop)
        assert op.verb == "emit"
        assert op.fn is _noop
        assert op.params == {}
        assert op.render_lens is None
        assert op.fidelity is None
        assert op.render_context == {}
        assert op.vertex_path is None
        assert op.observer is None
        assert op.mode == "static"
        assert op.stream_fn is None
        assert op.interactive_handler is None

    def test_is_action_when_render_lens_none(self):
        op = Operation(verb="emit", fn=_noop)
        assert op.is_action is True

    def test_is_action_false_when_render_lens_set(self):
        op = Operation(verb="read", fn=_noop, render_lens="fold")
        assert op.is_action is False


class TestOperationImmutability:
    def test_frozen(self):
        import dataclasses

        op = Operation(verb="emit", fn=_noop)
        try:
            op.verb = "read"  # type: ignore[misc]
        except dataclasses.FrozenInstanceError:
            return
        raise AssertionError("Operation should be frozen")

    def test_params_default_is_isolated(self):
        # Mutable defaults must not be shared across instances.
        a = Operation(verb="emit", fn=_noop)
        b = Operation(verb="emit", fn=_noop)
        a.params["k"] = "v"
        assert "k" not in b.params


class TestOperationFields:
    def test_display_shape(self):
        op = Operation(
            verb="read",
            fn=_noop,
            params={"vertex_path": Path("/tmp/x.vertex")},
            render_lens="fold",
            render_context={"diff": True},
            vertex_path=Path("/tmp/x.vertex"),
            observer="alice",
        )
        assert op.is_action is False
        assert op.render_lens == "fold"
        assert op.render_context["diff"] is True
        assert op.observer == "alice"

    def test_live_shape(self):
        async def stream():
            yield {"data": 1}

        op = Operation(
            verb="read", fn=_noop, render_lens="fold",
            mode="live", stream_fn=stream,
        )
        assert op.mode == "live"
        assert op.stream_fn is stream

    def test_interactive_shape(self):
        def handler() -> int:
            return 0

        op = Operation(
            verb="read", fn=_noop, render_lens="autoresearch",
            mode="interactive", interactive_handler=handler,
        )
        assert op.mode == "interactive"
        assert op.interactive_handler is handler
