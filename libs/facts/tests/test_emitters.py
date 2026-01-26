"""Tests for reference emitters (Json, Plain)."""

import json
from io import StringIO

from facts import Event, Result
from facts.emitter import Emitter
from facts.emitters import JsonEmitter, PlainEmitter


class TestJsonEmitter:
    """Tests for JsonEmitter."""

    def test_satisfies_emitter_protocol(self):
        """JsonEmitter satisfies the Emitter protocol."""
        emitter: Emitter = JsonEmitter()
        emitter.emit(Event(kind="log", message="test"))
        emitter.finish(Result(status="ok"))

    def test_default_outputs_events_and_result(self):
        """Default mode outputs {"events": [...], "result": {...}}."""
        stdout = StringIO()
        stderr = StringIO()
        emitter = JsonEmitter(stdout=stdout, stderr=stderr)

        emitter.emit(Event(kind="log", message="first"))
        emitter.emit(Event(kind="log", message="second"))
        emitter.finish(Result(status="ok", summary="done"))

        output = json.loads(stdout.getvalue())
        assert "events" in output
        assert "result" in output
        assert len(output["events"]) == 2
        assert output["events"][0]["message"] == "first"
        assert output["events"][1]["message"] == "second"
        assert output["result"]["status"] == "ok"
        assert output["result"]["summary"] == "done"
        assert stderr.getvalue() == ""

    def test_include_events_false_outputs_only_result(self):
        """With include_events=False, only result is output."""
        stdout = StringIO()
        emitter = JsonEmitter(stdout=stdout, include_events=False)

        emitter.emit(Event(kind="log", message="ignored"))
        emitter.finish(Result(status="ok", summary="done"))

        output = json.loads(stdout.getvalue())
        assert "events" not in output
        assert output["status"] == "ok"
        assert output["summary"] == "done"

    def test_stream_events_writes_jsonl_to_stderr(self):
        """With stream_events=True, events stream to stderr as JSONL."""
        stdout = StringIO()
        stderr = StringIO()
        emitter = JsonEmitter(stdout=stdout, stderr=stderr, stream_events=True)

        emitter.emit(Event(kind="log", message="first"))
        emitter.emit(Event(kind="log", message="second"))
        emitter.finish(Result(status="ok"))

        # stderr should have JSONL
        lines = stderr.getvalue().strip().split("\n")
        assert len(lines) == 2
        assert json.loads(lines[0])["message"] == "first"
        assert json.loads(lines[1])["message"] == "second"

        # stdout should still have full output
        output = json.loads(stdout.getvalue())
        assert len(output["events"]) == 2

    def test_empty_events_list(self):
        """Empty events list is handled correctly."""
        stdout = StringIO()
        emitter = JsonEmitter(stdout=stdout)

        emitter.finish(Result(status="ok"))

        output = json.loads(stdout.getvalue())
        assert output["events"] == []
        assert output["result"]["status"] == "ok"

    def test_output_is_valid_json(self):
        """Output is valid, parseable JSON."""
        stdout = StringIO()
        emitter = JsonEmitter(stdout=stdout)

        emitter.emit(Event(kind="metric", data={"name": "duration", "value": 1.5}))
        emitter.finish(Result(status="ok", data={"items": [1, 2, 3]}))

        # Should not raise
        output = json.loads(stdout.getvalue())
        assert output["result"]["data"]["items"] == [1, 2, 3]

    def test_output_ends_with_newline(self):
        """Output ends with a newline for shell friendliness."""
        stdout = StringIO()
        emitter = JsonEmitter(stdout=stdout)
        emitter.finish(Result(status="ok"))

        assert stdout.getvalue().endswith("\n")


class TestPlainEmitter:
    """Tests for PlainEmitter."""

    def test_satisfies_emitter_protocol(self):
        """PlainEmitter satisfies the Emitter protocol."""
        emitter: Emitter = PlainEmitter()
        emitter.emit(Event(kind="log", message="test"))
        emitter.finish(Result(status="ok"))

    def test_log_event_prints_message(self):
        """Log events print their message."""
        out = StringIO()
        emitter = PlainEmitter(file=out)

        emitter.emit(Event(kind="log", message="Hello world"))
        emitter.finish(Result(status="ok"))

        assert "Hello world" in out.getvalue()

    def test_progress_event_formats_step(self):
        """Progress events show step/total when available."""
        out = StringIO()
        emitter = PlainEmitter(file=out)

        emitter.emit(Event(kind="progress", data={"step": 3, "of": 10}))
        emitter.finish(Result(status="ok"))

        output = out.getvalue()
        assert "3" in output and "10" in output

    def test_progress_event_formats_percent(self):
        """Progress events show percentage when available."""
        out = StringIO()
        emitter = PlainEmitter(file=out)

        emitter.emit(Event(kind="progress", data={"percent": 50}))
        emitter.finish(Result(status="ok"))

        assert "50" in out.getvalue()

    def test_artifact_event_shows_path(self):
        """Artifact events show the path or URL."""
        out = StringIO()
        emitter = PlainEmitter(file=out)

        emitter.emit(Event(kind="artifact", data={"path": "/tmp/output.json"}))
        emitter.finish(Result(status="ok"))

        assert "/tmp/output.json" in out.getvalue()

    def test_metric_event_shows_name_value(self):
        """Metric events show name and value."""
        out = StringIO()
        emitter = PlainEmitter(file=out)

        emitter.emit(Event(kind="metric", data={"name": "duration", "value": 2.5}))
        emitter.finish(Result(status="ok"))

        output = out.getvalue()
        assert "duration" in output
        assert "2.5" in output

    def test_input_event_shows_question_response(self):
        """Input events show the question and response."""
        out = StringIO()
        emitter = PlainEmitter(file=out)

        emitter.emit(Event(kind="input", message="Continue?", data={"response": "yes"}))
        emitter.finish(Result(status="ok"))

        output = out.getvalue()
        assert "Continue?" in output
        assert "yes" in output

    def test_result_shows_status_summary(self):
        """Result prints status and summary."""
        out = StringIO()
        emitter = PlainEmitter(file=out)

        emitter.finish(Result(status="ok", summary="All done"))

        output = out.getvalue()
        assert "OK" in output or "ok" in output.lower()
        assert "All done" in output

    def test_error_result_shows_error_status(self):
        """Error results show error status."""
        out = StringIO()
        emitter = PlainEmitter(file=out)

        emitter.finish(Result.error("Something failed"))

        output = out.getvalue()
        assert "ERROR" in output or "error" in output.lower()
        assert "Something failed" in output

    def test_level_prefix_when_enabled(self):
        """Level prefix shown when enabled."""
        out = StringIO()
        emitter = PlainEmitter(file=out, show_level=True)

        emitter.emit(Event(kind="log", level="warn", message="Watch out"))
        emitter.finish(Result(status="ok"))

        assert "WARN" in out.getvalue() or "warn" in out.getvalue().lower()

    def test_no_level_prefix_when_disabled(self):
        """No level prefix when disabled."""
        out = StringIO()
        emitter = PlainEmitter(file=out, show_level=False)

        emitter.emit(Event(kind="log", level="warn", message="Watch out"))
        emitter.finish(Result(status="ok"))

        output = out.getvalue()
        # Should have message but not bracketed level
        assert "Watch out" in output
        assert "[WARN]" not in output

    def test_timestamp_prefix_when_enabled(self):
        """Timestamp prefix shown when enabled."""
        out = StringIO()
        emitter = PlainEmitter(file=out, show_timestamp=True)

        emitter.emit(Event(kind="log", message="test", ts=1704200000.123))
        emitter.finish(Result(status="ok"))

        assert "1704200000.123" in out.getvalue()

    def test_progress_without_data_uses_message(self):
        """Progress with only message renders the message."""
        out = StringIO()
        emitter = PlainEmitter(file=out)

        emitter.emit(Event(kind="progress", message="Working..."))
        emitter.finish(Result(status="ok"))

        assert "Working..." in out.getvalue()

    def test_progress_step_without_message(self):
        """Progress with step/of but no message."""
        out = StringIO()
        emitter = PlainEmitter(file=out)

        emitter.emit(Event(kind="progress", data={"step": 2, "of": 5}))
        emitter.finish(Result(status="ok"))

        output = out.getvalue()
        assert "2" in output and "5" in output

    def test_artifact_with_url(self):
        """Artifact with URL instead of path."""
        out = StringIO()
        emitter = PlainEmitter(file=out)

        emitter.emit(Event(kind="artifact", data={"href": "https://example.com/file"}))
        emitter.finish(Result(status="ok"))

        assert "https://example.com/file" in out.getvalue()

    def test_metric_with_unit(self):
        """Metric with unit included."""
        out = StringIO()
        emitter = PlainEmitter(file=out)

        emitter.emit(Event(kind="metric", data={"name": "size", "value": 1024, "unit": "bytes"}))
        emitter.finish(Result(status="ok"))

        output = out.getvalue()
        assert "size" in output
        assert "1024" in output
        assert "bytes" in output

    def test_result_without_summary(self):
        """Result without summary just shows status."""
        out = StringIO()
        emitter = PlainEmitter(file=out)

        emitter.finish(Result(status="ok"))

        assert "OK" in out.getvalue()

    def test_progress_empty_renders_nothing(self):
        """Progress with no data and no message produces no output."""
        out = StringIO()
        emitter = PlainEmitter(file=out)

        emitter.emit(Event(kind="progress"))  # No message, no data
        emitter.finish(Result(status="ok"))

        # Should only have the result line
        lines = out.getvalue().strip().split("\n")
        assert len(lines) == 1
        assert "OK" in lines[0]

    def test_artifact_with_id(self):
        """Artifact with just an ID."""
        out = StringIO()
        emitter = PlainEmitter(file=out)

        emitter.emit(Event(kind="artifact", message="Resource", data={"id": "res-123"}))
        emitter.finish(Result(status="ok"))

        output = out.getvalue()
        assert "Resource" in output
        assert "res-123" in output

    def test_metric_without_unit(self):
        """Metric without unit."""
        out = StringIO()
        emitter = PlainEmitter(file=out)

        emitter.emit(Event(kind="metric", data={"name": "count", "value": 5}))
        emitter.finish(Result(status="ok"))

        output = out.getvalue()
        assert "count" in output
        assert "5" in output

    def test_progress_step_with_message(self):
        """Progress with step and message shows both."""
        out = StringIO()
        emitter = PlainEmitter(file=out)

        emitter.emit(Event(kind="progress", message="Installing", data={"step": 2, "of": 3}))
        emitter.finish(Result(status="ok"))

        output = out.getvalue()
        assert "2" in output and "3" in output
        assert "Installing" in output

    def test_progress_percent_with_message(self):
        """Progress with percent and message shows both."""
        out = StringIO()
        emitter = PlainEmitter(file=out)

        emitter.emit(Event(kind="progress", message="Downloading", data={"percent": 50}))
        emitter.finish(Result(status="ok"))

        output = out.getvalue()
        assert "50" in output
        assert "Downloading" in output


class TestPlainEmitterContext:
    """Tests for PlainEmitter context protocol."""

    def test_context_manager(self):
        """PlainEmitter can be used as context manager."""
        out = StringIO()
        with PlainEmitter(file=out) as emitter:
            emitter.emit(Event.log("test"))

        assert "test" in out.getvalue()

    def test_enter_returns_self(self):
        """__enter__ returns the emitter itself."""
        emitter = PlainEmitter()
        assert emitter.__enter__() is emitter


class TestPlainEmitterSignalFallback:
    """Tests for signal fallback rendering in PlainEmitter."""

    def test_renders_signal_with_data(self):
        """Signals render with name and key=value pairs."""
        out = StringIO()
        emitter = PlainEmitter(file=out, show_level=False)

        emitter.emit(Event.log_signal("stack_status", stack="media", healthy=True))
        emitter.finish(Result.ok())

        output = out.getvalue()
        assert "stack_status" in output
        assert "stack=media" in output
        assert "healthy=True" in output

    def test_renders_signal_name_only_when_no_extra_data(self):
        """Signal with only the signal marker shows just the name."""
        out = StringIO()
        emitter = PlainEmitter(file=out, show_level=False)

        emitter.emit(Event.log_signal("heartbeat"))
        emitter.finish(Result.ok())

        output = out.getvalue()
        assert "heartbeat" in output

    def test_signal_key_excluded_from_output(self):
        """The 'signal' key itself is not rendered as a value."""
        out = StringIO()
        emitter = PlainEmitter(file=out, show_level=False)

        emitter.emit(Event.log_signal("foo", bar=1))
        emitter.finish(Result.ok())

        output = out.getvalue()
        # Should NOT contain "signal=foo"
        assert "signal=" not in output
        # Should contain the signal name and the data
        assert "foo" in output
        assert "bar=1" in output

    def test_signal_with_message_includes_message(self):
        """Signal with a message includes both message and data."""
        out = StringIO()
        emitter = PlainEmitter(file=out, show_level=False)

        emitter.emit(Event.log_signal("deploy.stage", message="Deploying", stage="rsync"))
        emitter.finish(Result.ok())

        output = out.getvalue()
        assert "deploy.stage" in output
        assert "Deploying" in output
        assert "stage=rsync" in output


class TestJsonEmitterContext:
    """Tests for JsonEmitter context protocol."""

    def test_context_manager(self):
        """JsonEmitter can be used as context manager."""
        stdout = StringIO()
        with JsonEmitter(stdout=stdout) as emitter:
            emitter.emit(Event.log("test"))
            emitter.finish(Result.ok())

        output = json.loads(stdout.getvalue())
        assert len(output["events"]) == 1

    def test_enter_returns_self(self):
        """__enter__ returns the emitter itself."""
        emitter = JsonEmitter()
        assert emitter.__enter__() is emitter


