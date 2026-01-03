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
