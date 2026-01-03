"""Tests for ev core types."""

from dataclasses import FrozenInstanceError

import pytest

from ev import Event, Result


class TestEvent:
    """Tests for Event dataclass."""

    def test_create_minimal(self):
        """Event can be created with just kind."""
        event = Event(kind="log")
        assert event.kind == "log"
        assert event.level == "info"
        assert event.message == ""
        assert event.data == {}
        assert event.ts is None

    # Immutability tests

    def test_data_isolated_from_caller(self):
        """Mutation of original dict doesn't affect event."""
        original = {"key": "value"}
        event = Event(kind="log", data=original)
        original["key"] = "mutated"
        assert event.data["key"] == "value"

    def test_data_not_directly_mutable(self):
        """Direct mutation of event.data raises TypeError."""
        event = Event(kind="log", data={"key": "value"})
        with pytest.raises(TypeError):
            event.data["key"] = "mutated"  # type: ignore[index]

    # Serialization tests

    def test_to_dict_returns_plain_dict(self):
        """to_dict() returns a plain dict, not MappingProxyType."""
        event = Event(
            kind="progress",
            level="warn",
            message="test",
            data={"nested": {"deep": 1}},
            ts=1704200000.0,
        )
        d = event.to_dict()
        assert isinstance(d, dict)
        assert isinstance(d["data"], dict)
        assert d == {
            "kind": "progress",
            "level": "warn",
            "message": "test",
            "data": {"nested": {"deep": 1}},
            "ts": 1704200000.0,
        }

    def test_from_dict_round_trips(self):
        """from_dict() reconstructs an equivalent Event."""
        original = Event(
            kind="artifact",
            level="info",
            message="file created",
            data={"type": "file", "path": "/tmp/out.txt"},
            ts=1704200000.0,
        )
        d = original.to_dict()
        reconstructed = Event.from_dict(d)
        assert reconstructed == original

    def test_from_dict_minimal(self):
        """from_dict() works with minimal fields."""
        d = {"kind": "log"}
        event = Event.from_dict(d)
        assert event.kind == "log"
        assert event.level == "info"
        assert event.message == ""
        assert event.data == {}
        assert event.ts is None

    def test_create_full(self):
        """Event can be created with all fields."""
        event = Event(
            kind="progress",
            level="warn",
            message="Something happened",
            data={"key": "value"},
            ts=1704200000.0,
        )
        assert event.kind == "progress"
        assert event.level == "warn"
        assert event.message == "Something happened"
        assert event.data == {"key": "value"}
        assert event.ts == 1704200000.0

    def test_frozen(self):
        """Event is immutable."""
        event = Event(kind="log")
        with pytest.raises(FrozenInstanceError):
            event.kind = "progress"  # type: ignore[misc]

    def test_equality(self):
        """Events with same fields are equal."""
        e1 = Event(kind="log", message="test")
        e2 = Event(kind="log", message="test")
        assert e1 == e2

    # is_kind helper

    def test_is_kind_single_match(self):
        """is_kind returns True for matching kind."""
        event = Event(kind="log")
        assert event.is_kind("log") is True
        assert event.is_kind("progress") is False

    def test_is_kind_multiple_match(self):
        """is_kind returns True if any kind matches."""
        event = Event(kind="artifact")
        assert event.is_kind("log", "artifact") is True
        assert event.is_kind("log", "progress") is False

    # Factory methods

    def test_log_factory_minimal(self):
        """Event.log creates a log event with message."""
        event = Event.log("Starting...")
        assert event.kind == "log"
        assert event.level == "info"
        assert event.message == "Starting..."
        assert event.data == {}

    def test_log_factory_with_level(self):
        """Event.log accepts level parameter."""
        event = Event.log("Warning!", level="warn")
        assert event.kind == "log"
        assert event.level == "warn"
        assert event.message == "Warning!"

    def test_log_factory_with_data(self):
        """Event.log accepts arbitrary data kwargs."""
        event = Event.log("Details", context="test", count=5)
        assert event.message == "Details"
        assert event.data == {"context": "test", "count": 5}

    def test_progress_factory_minimal(self):
        """Event.progress creates a progress event."""
        event = Event.progress()
        assert event.kind == "progress"
        assert event.level == "info"
        assert event.message == ""

    def test_progress_factory_with_step(self):
        """Event.progress accepts step/of parameters."""
        event = Event.progress("Processing", step=2, of=5)
        assert event.kind == "progress"
        assert event.message == "Processing"
        assert event.data == {"step": 2, "of": 5}

    def test_progress_factory_with_percent(self):
        """Event.progress accepts percent parameter."""
        event = Event.progress(percent=75)
        assert event.data == {"percent": 75}

    def test_artifact_factory_minimal(self):
        """Event.artifact creates an artifact event."""
        event = Event.artifact()
        assert event.kind == "artifact"
        assert event.level == "info"

    def test_artifact_factory_file(self):
        """Event.artifact with type and path."""
        event = Event.artifact("Config saved", type="file", path="/tmp/config.json")
        assert event.kind == "artifact"
        assert event.message == "Config saved"
        assert event.data == {"type": "file", "path": "/tmp/config.json"}

    def test_artifact_factory_url(self):
        """Event.artifact with type and href."""
        event = Event.artifact("Report", type="url", href="https://example.com/report")
        assert event.data == {"type": "url", "href": "https://example.com/report"}

    def test_metric_factory(self):
        """Event.metric creates a metric event with name and value."""
        event = Event.metric("duration", 2.3)
        assert event.kind == "metric"
        assert event.data == {"name": "duration", "value": 2.3}

    def test_metric_factory_with_unit(self):
        """Event.metric accepts unit parameter."""
        event = Event.metric("duration", 2.3, unit="s")
        assert event.data == {"name": "duration", "value": 2.3, "unit": "s"}

    def test_metric_factory_with_extra_data(self):
        """Event.metric accepts additional data kwargs."""
        event = Event.metric("requests", 100, unit="req/s", endpoint="/api")
        assert event.data == {"name": "requests", "value": 100, "unit": "req/s", "endpoint": "/api"}

    def test_input_factory_minimal(self):
        """Event.input creates an input event."""
        event = Event.input("Continue?")
        assert event.kind == "input"
        assert event.message == "Continue?"

    def test_input_factory_with_response(self):
        """Event.input accepts response parameter."""
        event = Event.input("Continue?", response="yes")
        assert event.message == "Continue?"
        assert event.data == {"response": "yes"}

    def test_input_factory_with_extra_data(self):
        """Event.input accepts additional data kwargs."""
        event = Event.input("Select option", response="A", options=["A", "B", "C"])
        assert event.data == {"response": "A", "options": ["A", "B", "C"]}

    def test_all_kinds(self):
        """All event kinds can be used."""
        for kind in ["log", "progress", "artifact", "metric", "input"]:
            event = Event(kind=kind)  # type: ignore[arg-type]
            assert event.kind == kind

    def test_all_levels(self):
        """All event levels can be used."""
        for level in ["debug", "info", "warn", "error"]:
            event = Event(kind="log", level=level)  # type: ignore[arg-type]
            assert event.level == level


class TestResult:
    """Tests for Result dataclass."""

    def test_create_minimal(self):
        """Result can be created with just status."""
        result = Result(status="ok")
        assert result.status == "ok"
        assert result.code == 0
        assert result.summary == ""
        assert result.data == {}
        assert result.meta == {}

    # Immutability tests

    def test_data_isolated_from_caller(self):
        """Mutation of original dict doesn't affect result.data."""
        original = {"key": "value"}
        result = Result(status="ok", data=original)
        original["key"] = "mutated"
        assert result.data["key"] == "value"

    def test_meta_isolated_from_caller(self):
        """Mutation of original dict doesn't affect result.meta."""
        original = {"duration": 1.5}
        result = Result(status="ok", meta=original)
        original["duration"] = 999
        assert result.meta["duration"] == 1.5

    def test_data_not_directly_mutable(self):
        """Direct mutation of result.data raises TypeError."""
        result = Result(status="ok", data={"key": "value"})
        with pytest.raises(TypeError):
            result.data["key"] = "mutated"  # type: ignore[index]

    def test_meta_not_directly_mutable(self):
        """Direct mutation of result.meta raises TypeError."""
        result = Result(status="ok", meta={"duration": 1.5})
        with pytest.raises(TypeError):
            result.meta["duration"] = 999  # type: ignore[index]

    # Serialization tests

    def test_to_dict_returns_plain_dict(self):
        """to_dict() returns a plain dict, not MappingProxyType."""
        result = Result(
            status="error",
            code=1,
            summary="Failed",
            data={"error": {"code": "E001"}},
            meta={"duration": 2.3},
        )
        d = result.to_dict()
        assert isinstance(d, dict)
        assert isinstance(d["data"], dict)
        assert isinstance(d["meta"], dict)
        assert d == {
            "status": "error",
            "code": 1,
            "summary": "Failed",
            "data": {"error": {"code": "E001"}},
            "meta": {"duration": 2.3},
        }

    def test_from_dict_round_trips(self):
        """from_dict() reconstructs an equivalent Result."""
        original = Result(
            status="ok",
            code=0,
            summary="All good",
            data={"items": [1, 2, 3]},
            meta={"duration": 0.5},
        )
        d = original.to_dict()
        reconstructed = Result.from_dict(d)
        assert reconstructed == original

    def test_from_dict_minimal(self):
        """from_dict() works with minimal fields."""
        d = {"status": "ok"}
        result = Result.from_dict(d)
        assert result.status == "ok"
        assert result.code == 0
        assert result.summary == ""
        assert result.data == {}
        assert result.meta == {}

    def test_create_full(self):
        """Result can be created with all fields."""
        result = Result(
            status="error",
            code=1,
            summary="Something failed",
            data={"error": "details"},
            meta={"duration": 2.3},
        )
        assert result.status == "error"
        assert result.code == 1
        assert result.summary == "Something failed"
        assert result.data == {"error": "details"}
        assert result.meta == {"duration": 2.3}

    def test_frozen(self):
        """Result is immutable."""
        result = Result(status="ok")
        with pytest.raises(FrozenInstanceError):
            result.status = "error"  # type: ignore[misc]

    def test_equality(self):
        """Results with same fields are equal."""
        r1 = Result(status="ok", summary="done")
        r2 = Result(status="ok", summary="done")
        assert r1 == r2

    # is_ok / is_error properties

    def test_is_ok_true(self):
        """is_ok returns True for ok status."""
        result = Result(status="ok")
        assert result.is_ok is True
        assert result.is_error is False

    def test_is_error_true(self):
        """is_error returns True for error status."""
        result = Result(status="error", code=1)
        assert result.is_error is True
        assert result.is_ok is False

    # Factory methods

    def test_ok_factory_minimal(self):
        """Result.ok creates an ok result with code=0."""
        result = Result.ok()
        assert result.status == "ok"
        assert result.code == 0
        assert result.summary == ""
        assert result.data == {}
        assert result.meta == {}

    def test_ok_factory_with_summary(self):
        """Result.ok accepts summary parameter."""
        result = Result.ok("All done")
        assert result.status == "ok"
        assert result.code == 0
        assert result.summary == "All done"

    def test_ok_factory_with_data_and_meta(self):
        """Result.ok accepts data and meta parameters."""
        result = Result.ok("Done", data={"count": 5}, meta={"duration": 1.2})
        assert result.summary == "Done"
        assert result.data == {"count": 5}
        assert result.meta == {"duration": 1.2}

    def test_error_factory_minimal(self):
        """Result.error creates an error result with code=1."""
        result = Result.error()
        assert result.status == "error"
        assert result.code == 1
        assert result.summary == ""

    def test_error_factory_with_summary(self):
        """Result.error accepts summary parameter."""
        result = Result.error("Something failed")
        assert result.status == "error"
        assert result.code == 1
        assert result.summary == "Something failed"

    def test_error_factory_with_code(self):
        """Result.error accepts custom error code."""
        result = Result.error("Failed", code=42)
        assert result.status == "error"
        assert result.code == 42

    def test_error_factory_with_data_and_meta(self):
        """Result.error accepts data and meta parameters."""
        result = Result.error("Failed", data={"reason": "timeout"}, meta={"attempts": 3})
        assert result.data == {"reason": "timeout"}
        assert result.meta == {"attempts": 3}

    # Invariants

    def test_ok_status_requires_code_zero(self):
        """Result with status=ok must have code=0."""
        with pytest.raises(ValueError, match="ok.*code.*0"):
            Result(status="ok", code=1)

    def test_error_status_requires_nonzero_code(self):
        """Result with status=error must have code != 0."""
        with pytest.raises(ValueError, match="error.*non-zero"):
            Result(status="error", code=0)

    def test_ok_with_explicit_zero_code_allowed(self):
        """Explicitly passing code=0 with status=ok is fine."""
        result = Result(status="ok", code=0)
        assert result.code == 0

    def test_error_with_explicit_nonzero_code_allowed(self):
        """Explicitly passing non-zero code with status=error is fine."""
        result = Result(status="error", code=2)
        assert result.code == 2
