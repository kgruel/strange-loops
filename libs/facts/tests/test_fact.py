"""Tests for the Fact atom."""

import dataclasses
from datetime import datetime, timezone
from types import MappingProxyType

import pytest

from facts import Fact


# --- Construction ---


class TestConstruction:
    def test_direct_construction(self):
        ts = datetime.now(timezone.utc)
        f = Fact(kind="heartbeat", ts=ts, payload={"service": "api"})
        assert f.kind == "heartbeat"
        assert f.ts == ts
        assert f.payload["service"] == "api"

    def test_str_payload(self):
        ts = datetime.now(timezone.utc)
        f = Fact(kind="log", ts=ts, payload="hello")
        assert f.payload == "hello"

    def test_int_payload(self):
        ts = datetime.now(timezone.utc)
        f = Fact(kind="metric", ts=ts, payload=42)
        assert f.payload == 42

    def test_dataclass_payload(self):
        @dataclasses.dataclass(frozen=True)
        class Info:
            name: str
            value: int

        ts = datetime.now(timezone.utc)
        info = Info(name="cpu", value=80)
        f = Fact(kind="metric", ts=ts, payload=info)
        assert f.payload.name == "cpu"
        assert f.payload.value == 80


# --- Factory ---


class TestFactory:
    def test_of_creates_dict_payload(self):
        f = Fact.of("heartbeat", service="api", latency=42)
        assert f.kind == "heartbeat"
        assert f.payload["service"] == "api"
        assert f.payload["latency"] == 42

    def test_of_auto_timestamps(self):
        before = datetime.now(timezone.utc)
        f = Fact.of("deploy", app="web")
        after = datetime.now(timezone.utc)
        assert before <= f.ts <= after
        assert f.ts.tzinfo is not None

    def test_of_empty_payload(self):
        f = Fact.of("ping")
        assert f.payload == {}


# --- Frozen ---


class TestFrozen:
    def test_cannot_reassign_kind(self):
        f = Fact.of("heartbeat")
        with pytest.raises(dataclasses.FrozenInstanceError):
            f.kind = "other"  # type: ignore[misc]

    def test_cannot_reassign_ts(self):
        f = Fact.of("heartbeat")
        with pytest.raises(dataclasses.FrozenInstanceError):
            f.ts = datetime.now(timezone.utc)  # type: ignore[misc]

    def test_cannot_reassign_payload(self):
        f = Fact.of("heartbeat", x=1)
        with pytest.raises(dataclasses.FrozenInstanceError):
            f.payload = {}  # type: ignore[misc]


# --- Payload immutability ---


class TestPayloadImmutability:
    def test_dict_payload_wrapped_in_mapping_proxy(self):
        f = Fact.of("heartbeat", service="api")
        assert isinstance(f.payload, MappingProxyType)

    def test_dict_payload_mutation_raises(self):
        f = Fact.of("heartbeat", service="api")
        with pytest.raises(TypeError):
            f.payload["service"] = "other"  # type: ignore[index]

    def test_original_dict_mutation_does_not_affect_fact(self):
        data = {"service": "api"}
        ts = datetime.now(timezone.utc)
        f = Fact(kind="heartbeat", ts=ts, payload=data)
        data["service"] = "changed"
        assert f.payload["service"] == "api"

    def test_non_dict_payload_not_wrapped(self):
        ts = datetime.now(timezone.utc)
        f = Fact(kind="metric", ts=ts, payload=42)
        assert not isinstance(f.payload, MappingProxyType)


# --- Serialization ---


class TestSerialization:
    def test_to_dict(self):
        ts = datetime(2025, 1, 15, 12, 0, 0, tzinfo=timezone.utc)
        f = Fact(kind="deploy", ts=ts, payload={"app": "web"})
        d = f.to_dict()
        assert d == {
            "kind": "deploy",
            "ts": "2025-01-15T12:00:00+00:00",
            "payload": {"app": "web"},
        }

    def test_to_dict_returns_plain_dict_payload(self):
        f = Fact.of("heartbeat", service="api")
        d = f.to_dict()
        assert isinstance(d["payload"], dict)
        assert not isinstance(d["payload"], MappingProxyType)

    def test_to_dict_non_dict_payload(self):
        ts = datetime(2025, 1, 15, 12, 0, 0, tzinfo=timezone.utc)
        f = Fact(kind="count", ts=ts, payload=42)
        d = f.to_dict()
        assert d["payload"] == 42

    def test_from_dict(self):
        d = {
            "kind": "deploy",
            "ts": "2025-01-15T12:00:00+00:00",
            "payload": {"app": "web"},
        }
        f = Fact.from_dict(d)
        assert f.kind == "deploy"
        assert f.ts == datetime(2025, 1, 15, 12, 0, 0, tzinfo=timezone.utc)
        assert f.payload["app"] == "web"

    def test_round_trip(self):
        original = Fact.of("heartbeat", service="api", latency=42)
        rebuilt = Fact.from_dict(original.to_dict())
        assert rebuilt.kind == original.kind
        assert rebuilt.ts == original.ts
        assert dict(rebuilt.payload) == dict(original.payload)

    def test_round_trip_non_dict_payload(self):
        ts = datetime(2025, 6, 1, 0, 0, 0, tzinfo=timezone.utc)
        original = Fact(kind="count", ts=ts, payload=99)
        rebuilt = Fact.from_dict(original.to_dict())
        assert rebuilt.kind == original.kind
        assert rebuilt.ts == original.ts
        assert rebuilt.payload == original.payload


# --- Kind predicate ---


class TestIsKind:
    def test_single_match(self):
        f = Fact.of("heartbeat")
        assert f.is_kind("heartbeat") is True

    def test_multiple_match(self):
        f = Fact.of("heartbeat")
        assert f.is_kind("heartbeat", "deploy") is True

    def test_no_match(self):
        f = Fact.of("heartbeat")
        assert f.is_kind("deploy", "rollback") is False


# --- Equality and hashing ---


class TestEqualityAndHashing:
    def test_equal_facts(self):
        ts = datetime(2025, 1, 15, 12, 0, 0, tzinfo=timezone.utc)
        f1 = Fact(kind="heartbeat", ts=ts, payload={"x": 1})
        f2 = Fact(kind="heartbeat", ts=ts, payload={"x": 1})
        assert f1 == f2

    def test_unequal_facts(self):
        ts = datetime(2025, 1, 15, 12, 0, 0, tzinfo=timezone.utc)
        f1 = Fact(kind="heartbeat", ts=ts, payload={"x": 1})
        f2 = Fact(kind="deploy", ts=ts, payload={"x": 1})
        assert f1 != f2

    def test_usable_in_set(self):
        ts = datetime(2025, 1, 15, 12, 0, 0, tzinfo=timezone.utc)
        f1 = Fact(kind="heartbeat", ts=ts, payload="a")
        f2 = Fact(kind="heartbeat", ts=ts, payload="a")
        f3 = Fact(kind="deploy", ts=ts, payload="b")
        s = {f1, f2, f3}
        assert len(s) == 2


# --- Generic typing ---


class TestGeneric:
    def test_fact_int(self):
        ts = datetime.now(timezone.utc)
        f: Fact[int] = Fact(kind="count", ts=ts, payload=42)
        assert f.payload == 42

    def test_fact_str(self):
        ts = datetime.now(timezone.utc)
        f: Fact[str] = Fact(kind="label", ts=ts, payload="hello")
        assert f.payload == "hello"

    def test_fact_dict(self):
        ts = datetime.now(timezone.utc)
        f: Fact[dict] = Fact(kind="data", ts=ts, payload={"a": 1})
        assert f.payload["a"] == 1


# --- dataclasses.replace ---


class TestReplace:
    def test_replace_kind(self):
        f = Fact.of("heartbeat", service="api")
        f2 = dataclasses.replace(f, kind="deploy")
        assert f2.kind == "deploy"
        assert f2.payload["service"] == "api"

    def test_replace_payload_rewraps_dict(self):
        f = Fact.of("heartbeat", service="api")
        f2 = dataclasses.replace(f, payload={"app": "web"})
        assert isinstance(f2.payload, MappingProxyType)
        assert f2.payload["app"] == "web"

    def test_replace_preserves_original(self):
        f = Fact.of("heartbeat", service="api")
        dataclasses.replace(f, kind="deploy")
        assert f.kind == "heartbeat"
