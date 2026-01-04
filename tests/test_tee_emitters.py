"""Tests for TeeEmitter and FileEmitter."""

import json
from pathlib import Path

from ev import Event, Result
from ev.emitters import FileEmitter, TeeEmitter
from ev.emitters.plain import PlainEmitter


class TestTeeEmitter:
    """Tests for TeeEmitter."""

    def test_forwards_emit_to_all_emitters(self) -> None:
        """emit() forwards to all wrapped emitters."""
        from ev import ListEmitter

        em1 = ListEmitter()
        em2 = ListEmitter()
        tee = TeeEmitter(em1, em2)

        event = Event.log("test message")
        tee.emit(event)

        assert len(em1.events) == 1
        assert len(em2.events) == 1
        assert em1.events[0] == event
        assert em2.events[0] == event

    def test_forwards_finish_to_all_emitters(self) -> None:
        """finish() forwards to all wrapped emitters."""
        from io import StringIO

        out1 = StringIO()
        out2 = StringIO()
        em1 = PlainEmitter(file=out1)
        em2 = PlainEmitter(file=out2)
        tee = TeeEmitter(em1, em2)

        result = Result.ok("done")
        tee.finish(result)

        # Both emitters should have output
        assert out1.getvalue() != ""
        assert out2.getvalue() != ""

    def test_works_with_single_emitter(self) -> None:
        """TeeEmitter works with a single emitter."""
        from ev import ListEmitter

        em = ListEmitter()
        tee = TeeEmitter(em)

        event = Event.log("test")
        tee.emit(event)
        tee.finish(Result.ok("done"))

        assert len(em.events) == 1


class TestTeeEmitterContext:
    """Tests for TeeEmitter context protocol."""

    def test_context_manager(self) -> None:
        """TeeEmitter can be used as context manager."""
        from ev import ListEmitter

        em1 = ListEmitter()
        em2 = ListEmitter()

        with TeeEmitter(em1, em2) as tee:
            tee.emit(Event.log("test"))

        assert len(em1.events) == 1
        assert len(em2.events) == 1

    def test_enter_returns_self(self) -> None:
        """__enter__ returns the TeeEmitter itself."""
        from ev import ListEmitter

        tee = TeeEmitter(ListEmitter(), ListEmitter())
        assert tee.__enter__() is tee

    def test_enters_all_children(self) -> None:
        """__enter__ calls __enter__ on all child emitters."""
        enter_calls = []

        class TrackingEmitter:
            def emit(self, event):
                pass

            def finish(self, result):
                pass

            def __enter__(self):
                enter_calls.append(self)
                return self

            def __exit__(self, *args):
                pass

        em1 = TrackingEmitter()
        em2 = TrackingEmitter()
        tee = TeeEmitter(em1, em2)

        tee.__enter__()

        assert em1 in enter_calls
        assert em2 in enter_calls

    def test_exits_all_children(self) -> None:
        """__exit__ calls __exit__ on all child emitters."""
        exit_calls = []

        class TrackingEmitter:
            def emit(self, event):
                pass

            def finish(self, result):
                pass

            def __enter__(self):
                return self

            def __exit__(self, *args):
                exit_calls.append(self)

        em1 = TrackingEmitter()
        em2 = TrackingEmitter()
        tee = TeeEmitter(em1, em2)

        tee.__enter__()
        tee.__exit__(None, None, None)

        assert em1 in exit_calls
        assert em2 in exit_calls

    def test_exits_all_even_on_exception(self) -> None:
        """__exit__ calls __exit__ on all children even if one raises."""
        exit_calls = []

        class FailingEmitter:
            def emit(self, event):
                pass

            def finish(self, result):
                pass

            def __enter__(self):
                return self

            def __exit__(self, *args):
                exit_calls.append("failing")
                raise RuntimeError("exit failed")

        class NormalEmitter:
            def emit(self, event):
                pass

            def finish(self, result):
                pass

            def __enter__(self):
                return self

            def __exit__(self, *args):
                exit_calls.append("normal")

        em1 = FailingEmitter()
        em2 = NormalEmitter()
        tee = TeeEmitter(em1, em2)

        tee.__enter__()

        # Should raise the first error but still call all exits
        import pytest

        with pytest.raises(RuntimeError, match="exit failed"):
            tee.__exit__(None, None, None)

        assert "failing" in exit_calls
        assert "normal" in exit_calls


class TestFileEmitter:
    """Tests for FileEmitter."""

    def test_writes_events_as_jsonl(self, tmp_path: Path) -> None:
        """Events are written as JSON lines."""
        log_file = tmp_path / "test.log"

        with FileEmitter(log_file) as emitter:
            emitter.emit(Event.log("hello"))
            emitter.emit(Event.artifact("result", value=42))

        lines = log_file.read_text().strip().split("\n")
        assert len(lines) == 2

        event1 = json.loads(lines[0])
        assert event1["kind"] == "log"
        assert event1["message"] == "hello"

        event2 = json.loads(lines[1])
        assert event2["kind"] == "artifact"
        assert event2["data"]["value"] == 42

    def test_writes_result_on_finish(self, tmp_path: Path) -> None:
        """finish() writes result as final line."""
        log_file = tmp_path / "test.log"

        with FileEmitter(log_file) as emitter:
            emitter.emit(Event.log("work"))
            emitter.finish(Result.ok("done", data={"count": 5}))

        lines = log_file.read_text().strip().split("\n")
        assert len(lines) == 2

        result_line = json.loads(lines[1])
        assert result_line["type"] == "result"
        assert result_line["is_ok"] is True
        assert result_line["summary"] == "done"
        assert result_line["data"]["count"] == 5

    def test_flushes_after_each_write(self, tmp_path: Path) -> None:
        """File is flushed after each event for tail -f compatibility."""
        log_file = tmp_path / "test.log"

        with FileEmitter(log_file) as emitter:
            emitter.emit(Event.log("first"))
            # File should be readable immediately (message is in "message" field)
            content = log_file.read_text()
            data = json.loads(content.strip())
            assert data["message"] == "first"

            emitter.emit(Event.log("second"))
            lines = log_file.read_text().strip().split("\n")
            assert len(lines) == 2
            assert json.loads(lines[1])["message"] == "second"

    def test_handles_signal_events(self, tmp_path: Path) -> None:
        """Signal events include signal_name in output."""
        log_file = tmp_path / "test.log"

        with FileEmitter(log_file) as emitter:
            emitter.emit(Event.log_signal("deploy.started", stack="media"))

        line = json.loads(log_file.read_text().strip())
        assert line["kind"] == "log"
        assert line["signal_name"] == "deploy.started"
        assert line["data"]["stack"] == "media"

    def test_emit_without_context_manager_is_noop(self, tmp_path: Path) -> None:
        """emit() and finish() are no-ops if file not opened."""
        log_file = tmp_path / "test.log"
        emitter = FileEmitter(log_file)

        # Should not crash - both emit and finish are no-ops
        emitter.emit(Event.log("test"))
        emitter.finish(Result.ok("done"))

        # File should not exist (nothing was written)
        assert not log_file.exists()

    def test_exit_without_enter_is_safe(self, tmp_path: Path) -> None:
        """Calling __exit__ without __enter__ doesn't crash."""
        log_file = tmp_path / "test.log"
        emitter = FileEmitter(log_file)

        # Should not crash - _file is None
        emitter.__exit__(None, None, None)

    def test_works_with_path_string(self, tmp_path: Path) -> None:
        """FileEmitter accepts string path."""
        log_file = str(tmp_path / "test.log")

        with FileEmitter(log_file) as emitter:
            emitter.emit(Event.log("test"))

        assert Path(log_file).exists()

    def test_result_with_error(self, tmp_path: Path) -> None:
        """Error results are serialized correctly."""
        log_file = tmp_path / "test.log"

        with FileEmitter(log_file) as emitter:
            emitter.finish(Result.error("failed", code=1))

        result_line = json.loads(log_file.read_text().strip())
        assert result_line["is_ok"] is False
        assert result_line["is_error"] is True
        assert result_line["summary"] == "failed"
        assert result_line["code"] == 1

    def test_artifact_event_has_no_message_or_level(self, tmp_path: Path) -> None:
        """Artifact events don't have message/level fields."""
        log_file = tmp_path / "test.log"

        with FileEmitter(log_file) as emitter:
            emitter.emit(Event.artifact("data", value=123))

        line = json.loads(log_file.read_text().strip())
        assert "message" not in line
        assert "level" not in line
        assert line["kind"] == "artifact"


class TestTeeWithFileEmitter:
    """Integration tests for TeeEmitter + FileEmitter."""

    def test_tee_to_file_and_list(self, tmp_path: Path) -> None:
        """Tee events to both file and list emitter."""
        from ev import ListEmitter

        log_file = tmp_path / "test.log"
        list_em = ListEmitter()

        with FileEmitter(log_file) as file_em:
            tee = TeeEmitter(list_em, file_em)
            tee.emit(Event.log("hello"))
            tee.emit(Event.artifact("result", value=42))
            tee.finish(Result.ok("done"))

        # List emitter has events
        assert len(list_em.events) == 2

        # File has all events + result
        lines = log_file.read_text().strip().split("\n")
        assert len(lines) == 3
