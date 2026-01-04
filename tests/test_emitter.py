"""Tests for Emitter protocol and implementations."""

import pytest

from ev import Event, Result
from ev.emitter import Emitter, ListEmitter, NullEmitter


class TestEmitterProtocol:
    """Tests for Emitter Protocol."""

    def test_list_emitter_satisfies_protocol(self):
        """ListEmitter satisfies the Emitter protocol."""
        emitter: Emitter = ListEmitter()
        # If this compiles and runs, the protocol is satisfied
        emitter.emit(Event(kind="log"))
        emitter.finish(Result(status="ok"))

    def test_null_emitter_satisfies_protocol(self):
        """NullEmitter satisfies the Emitter protocol."""
        emitter: Emitter = NullEmitter()
        emitter.emit(Event(kind="log"))
        emitter.finish(Result(status="ok"))

    def test_custom_emitter_satisfies_protocol(self):
        """Any object with emit/finish methods satisfies the protocol."""

        class CustomEmitter:
            def emit(self, event: Event) -> None:
                pass

            def finish(self, result: Result) -> None:
                pass

        emitter: Emitter = CustomEmitter()
        emitter.emit(Event(kind="log"))
        emitter.finish(Result(status="ok"))


class TestListEmitter:
    """Tests for ListEmitter."""

    def test_collects_events_in_order(self):
        """Events are collected in emission order."""
        emitter = ListEmitter()
        emitter.emit(Event(kind="log", message="first"))
        emitter.emit(Event(kind="log", message="second"))
        emitter.emit(Event(kind="log", message="third"))

        assert len(emitter.events) == 3
        assert emitter.events[0].message == "first"
        assert emitter.events[1].message == "second"
        assert emitter.events[2].message == "third"

    def test_stores_result(self):
        """Result is stored on finish."""
        emitter = ListEmitter()
        emitter.emit(Event(kind="log"))
        emitter.finish(Result(status="ok", summary="done"))

        assert emitter.result is not None
        assert emitter.result.status == "ok"
        assert emitter.result.summary == "done"

    def test_result_initially_none(self):
        """Result is None before finish is called."""
        emitter = ListEmitter()
        assert emitter.result is None

    def test_raises_on_emit_after_finish(self):
        """Cannot emit events after finish() is called."""
        emitter = ListEmitter()
        emitter.emit(Event(kind="log"))
        emitter.finish(Result(status="ok"))

        with pytest.raises(RuntimeError, match="Cannot emit after finish"):
            emitter.emit(Event(kind="log"))

    def test_raises_on_double_finish(self):
        """Cannot call finish() twice."""
        emitter = ListEmitter()
        emitter.finish(Result.ok())

        with pytest.raises(RuntimeError, match="finish.*already called"):
            emitter.finish(Result.error())

    def test_empty_run(self):
        """A run with no events is valid."""
        emitter = ListEmitter()
        emitter.finish(Result(status="ok"))

        assert emitter.events == []
        assert emitter.result is not None


class TestNullEmitter:
    """Tests for NullEmitter."""

    def test_accepts_events_silently(self):
        """Events are accepted without error."""
        emitter = NullEmitter()
        emitter.emit(Event(kind="log"))
        emitter.emit(Event(kind="progress"))
        emitter.emit(Event(kind="artifact"))
        # No error raised

    def test_accepts_finish_silently(self):
        """Finish is accepted without error."""
        emitter = NullEmitter()
        emitter.finish(Result(status="ok"))
        # No error raised

    def test_no_state_tracking(self):
        """NullEmitter is truly no-op, no invariant enforcement."""
        emitter = NullEmitter()
        emitter.finish(Result.ok())
        # Can emit after finish (no enforcement)
        emitter.emit(Event(kind="log"))
        # Can finish again (no enforcement)
        emitter.finish(Result.error())
        # No errors raised


class TestContextProtocol:
    """Tests for context manager protocol on emitters."""

    def test_list_emitter_context_manager(self):
        """ListEmitter can be used as context manager."""
        with ListEmitter() as emitter:
            emitter.emit(Event.log("test"))

        assert len(emitter.events) == 1
        assert emitter.events[0].message == "test"

    def test_null_emitter_context_manager(self):
        """NullEmitter can be used as context manager."""
        with NullEmitter() as emitter:
            emitter.emit(Event.log("test"))
        # No error raised

    def test_list_emitter_enter_returns_self(self):
        """__enter__ returns the emitter itself."""
        emitter = ListEmitter()
        result = emitter.__enter__()
        assert result is emitter

    def test_null_emitter_enter_returns_self(self):
        """__enter__ returns the emitter itself."""
        emitter = NullEmitter()
        result = emitter.__enter__()
        assert result is emitter

    def test_context_does_not_suppress_exceptions(self):
        """__exit__ does not suppress exceptions."""
        with pytest.raises(ValueError, match="test error"), ListEmitter() as emitter:
            emitter.emit(Event.log("before error"))
            raise ValueError("test error")

    def test_context_exit_safe_after_exception(self):
        """Emitter state is consistent after exception in context."""
        emitter = ListEmitter()
        try:
            with emitter:
                emitter.emit(Event.log("before"))
                raise ValueError("boom")
        except ValueError:
            pass

        # Emitter should still be usable (not in broken state)
        assert len(emitter.events) == 1
        assert emitter.events[0].message == "before"
