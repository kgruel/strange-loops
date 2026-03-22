"""Tests for the Fact atom."""

import dataclasses
import time
from types import MappingProxyType

import pytest

from atoms import Fact


# --- Construction ---


class TestConstruction:
    def test_direct_construction(self):
        ts = time.time()
        f = Fact(kind="heartbeat", ts=ts, payload={"service": "api"}, observer="alice")
        assert f.kind == "heartbeat"
        assert f.ts == ts
        assert f.payload["service"] == "api"
        assert f.observer == "alice"

    def test_str_payload(self):
        ts = time.time()
        f = Fact(kind="log", ts=ts, payload="hello", observer="bob")
        assert f.payload == "hello"

    def test_int_payload(self):
        ts = time.time()
        f = Fact(kind="metric", ts=ts, payload=42, observer="sensor")
        assert f.payload == 42

    def test_dataclass_payload(self):
        @dataclasses.dataclass(frozen=True)
        class Info:
            name: str
            value: int

        ts = time.time()
        info = Info(name="cpu", value=80)
        f = Fact(kind="metric", ts=ts, payload=info, observer="monitor")
        assert f.payload.name == "cpu"
        assert f.payload.value == 80


# --- Factory ---


class TestFactory:
    def test_of_creates_dict_payload(self):
        f = Fact.of("heartbeat", "alice", service="api", latency=42)
        assert f.kind == "heartbeat"
        assert f.observer == "alice"
        assert f.payload["service"] == "api"
        assert f.payload["latency"] == 42

    def test_of_auto_timestamps(self):
        before = time.time()
        f = Fact.of("deploy", "bob", app="web")
        after = time.time()
        assert before <= f.ts <= after
        assert isinstance(f.ts, float)

    def test_of_empty_payload(self):
        f = Fact.of("ping", "sensor")
        assert f.payload == {}

    def test_of_explicit_ts(self):
        f = Fact.of("exchange", "siftd", ts=1234567890.0, prompt="hello")
        assert f.ts == 1234567890.0
        assert f.payload["prompt"] == "hello"

    def test_of_ts_none_uses_current_time(self):
        before = time.time()
        f = Fact.of("exchange", "siftd", ts=None, prompt="hello")
        after = time.time()
        assert before <= f.ts <= after

    def test_of_ts_not_in_payload(self):
        f = Fact.of("exchange", "siftd", ts=1234567890.0, prompt="hello")
        assert "ts" not in f.payload


# --- Tick factory ---


class TestTickFactory:
    def test_tick_prefixes_kind(self):
        f = Fact.tick("hourly", "vertex-a", count=42)
        assert f.kind == "tick.hourly"

    def test_tick_payload(self):
        f = Fact.tick("hourly", "vertex-a", count=42)
        assert f.payload["count"] == 42

    def test_tick_auto_timestamps(self):
        before = time.time()
        f = Fact.tick("daily", "vertex-a")
        after = time.time()
        assert before <= f.ts <= after
        assert isinstance(f.ts, float)

    def test_tick_empty_payload(self):
        f = Fact.tick("midnight", "vertex-a")
        assert f.payload == {}

    def test_tick_payload_wrapped_in_mapping_proxy(self):
        f = Fact.tick("hourly", "vertex-a", count=42)
        assert isinstance(f.payload, MappingProxyType)

    def test_tick_round_trip(self):
        original = Fact.tick("hourly", "vertex-a", count=42, source="cron")
        rebuilt = Fact.from_dict(original.to_dict())
        assert rebuilt.kind == original.kind
        assert rebuilt.ts == original.ts
        assert rebuilt.observer == original.observer
        assert dict(rebuilt.payload) == dict(original.payload)

    def test_tick_explicit_ts(self):
        f = Fact.tick("hourly", "vertex-a", ts=1234567890.0, count=42)
        assert f.ts == 1234567890.0
        assert f.kind == "tick.hourly"
        assert f.payload["count"] == 42

    def test_tick_is_kind(self):
        f = Fact.tick("hourly", "vertex-a")
        assert f.is_kind("tick.hourly") is True
        assert f.is_kind("hourly") is False


# --- Frozen ---


class TestFrozen:
    def test_cannot_reassign_kind(self):
        f = Fact.of("heartbeat", "alice")
        with pytest.raises(dataclasses.FrozenInstanceError):
            f.kind = "other"  # type: ignore[misc]

    def test_cannot_reassign_ts(self):
        f = Fact.of("heartbeat", "alice")
        with pytest.raises(dataclasses.FrozenInstanceError):
            f.ts = time.time()  # type: ignore[misc]

    def test_cannot_reassign_payload(self):
        f = Fact.of("heartbeat", "alice", x=1)
        with pytest.raises(dataclasses.FrozenInstanceError):
            f.payload = {}  # type: ignore[misc]

    def test_cannot_reassign_observer(self):
        f = Fact.of("heartbeat", "alice")
        with pytest.raises(dataclasses.FrozenInstanceError):
            f.observer = "bob"  # type: ignore[misc]


# --- Payload immutability ---


class TestPayloadImmutability:
    def test_dict_payload_wrapped_in_mapping_proxy(self):
        f = Fact.of("heartbeat", "alice", service="api")
        assert isinstance(f.payload, MappingProxyType)

    def test_dict_payload_mutation_raises(self):
        f = Fact.of("heartbeat", "alice", service="api")
        with pytest.raises(TypeError):
            f.payload["service"] = "other"  # type: ignore[index]

    def test_original_dict_mutation_does_not_affect_fact(self):
        data = {"service": "api"}
        ts = time.time()
        f = Fact(kind="heartbeat", ts=ts, payload=data, observer="alice")
        data["service"] = "changed"
        assert f.payload["service"] == "api"

    def test_non_dict_payload_not_wrapped(self):
        ts = time.time()
        f = Fact(kind="metric", ts=ts, payload=42, observer="sensor")
        assert not isinstance(f.payload, MappingProxyType)


# --- Serialization ---


FIXED_TS = 1736942400.0  # 2025-01-15T12:00:00 UTC


class TestSerialization:
    def test_to_dict(self):
        f = Fact(kind="deploy", ts=FIXED_TS, payload={"app": "web"}, observer="alice")
        d = f.to_dict()
        assert d == {
            "kind": "deploy",
            "ts": FIXED_TS,
            "payload": {"app": "web"},
            "observer": "alice",
            "origin": "",
        }

    def test_to_dict_with_origin(self):
        f = Fact(kind="deploy", ts=FIXED_TS, payload={"app": "web"}, observer="alice", origin="my-vertex")
        d = f.to_dict()
        assert d == {
            "kind": "deploy",
            "ts": FIXED_TS,
            "payload": {"app": "web"},
            "observer": "alice",
            "origin": "my-vertex",
        }

    def test_to_dict_returns_plain_dict_payload(self):
        f = Fact.of("heartbeat", "alice", service="api")
        d = f.to_dict()
        assert isinstance(d["payload"], dict)
        assert not isinstance(d["payload"], MappingProxyType)

    def test_to_dict_non_dict_payload(self):
        f = Fact(kind="count", ts=FIXED_TS, payload=42, observer="sensor")
        d = f.to_dict()
        assert d["payload"] == 42

    def test_from_dict(self):
        d = {
            "kind": "deploy",
            "ts": FIXED_TS,
            "payload": {"app": "web"},
            "observer": "alice",
        }
        f = Fact.from_dict(d)
        assert f.kind == "deploy"
        assert f.ts == FIXED_TS
        assert f.payload["app"] == "web"
        assert f.observer == "alice"

    def test_round_trip(self):
        original = Fact.of("heartbeat", "alice", service="api", latency=42)
        rebuilt = Fact.from_dict(original.to_dict())
        assert rebuilt.kind == original.kind
        assert rebuilt.ts == original.ts
        assert rebuilt.observer == original.observer
        assert dict(rebuilt.payload) == dict(original.payload)

    def test_round_trip_non_dict_payload(self):
        original = Fact(kind="count", ts=FIXED_TS, payload=99, observer="sensor")
        rebuilt = Fact.from_dict(original.to_dict())
        assert rebuilt.kind == original.kind
        assert rebuilt.ts == original.ts
        assert rebuilt.observer == original.observer
        assert rebuilt.payload == original.payload


# --- Kind predicate ---


class TestIsKind:
    def test_single_match(self):
        f = Fact.of("heartbeat", "alice")
        assert f.is_kind("heartbeat") is True

    def test_multiple_match(self):
        f = Fact.of("heartbeat", "alice")
        assert f.is_kind("heartbeat", "deploy") is True

    def test_no_match(self):
        f = Fact.of("heartbeat", "alice")
        assert f.is_kind("deploy", "rollback") is False


# --- Equality and hashing ---


class TestEqualityAndHashing:
    def test_equal_facts(self):
        f1 = Fact(kind="heartbeat", ts=FIXED_TS, payload={"x": 1}, observer="alice")
        f2 = Fact(kind="heartbeat", ts=FIXED_TS, payload={"x": 1}, observer="alice")
        assert f1 == f2

    def test_unequal_facts(self):
        f1 = Fact(kind="heartbeat", ts=FIXED_TS, payload={"x": 1}, observer="alice")
        f2 = Fact(kind="deploy", ts=FIXED_TS, payload={"x": 1}, observer="alice")
        assert f1 != f2

    def test_unequal_observers(self):
        f1 = Fact(kind="heartbeat", ts=FIXED_TS, payload={"x": 1}, observer="alice")
        f2 = Fact(kind="heartbeat", ts=FIXED_TS, payload={"x": 1}, observer="bob")
        assert f1 != f2

    def test_usable_in_set(self):
        f1 = Fact(kind="heartbeat", ts=FIXED_TS, payload="a", observer="alice")
        f2 = Fact(kind="heartbeat", ts=FIXED_TS, payload="a", observer="alice")
        f3 = Fact(kind="deploy", ts=FIXED_TS, payload="b", observer="alice")
        s = {f1, f2, f3}
        assert len(s) == 2


# --- Generic typing ---


class TestGeneric:
    def test_fact_int(self):
        ts = time.time()
        f: Fact[int] = Fact(kind="count", ts=ts, payload=42, observer="sensor")
        assert f.payload == 42

    def test_fact_str(self):
        ts = time.time()
        f: Fact[str] = Fact(kind="label", ts=ts, payload="hello", observer="sensor")
        assert f.payload == "hello"

    def test_fact_dict(self):
        ts = time.time()
        f: Fact[dict] = Fact(kind="data", ts=ts, payload={"a": 1}, observer="sensor")
        assert f.payload["a"] == 1


# --- dataclasses.replace ---


class TestReplace:
    def test_replace_kind(self):
        f = Fact.of("heartbeat", "alice", service="api")
        f2 = dataclasses.replace(f, kind="deploy")
        assert f2.kind == "deploy"
        assert f2.payload["service"] == "api"

    def test_replace_payload_rewraps_dict(self):
        f = Fact.of("heartbeat", "alice", service="api")
        f2 = dataclasses.replace(f, payload={"app": "web"})
        assert isinstance(f2.payload, MappingProxyType)
        assert f2.payload["app"] == "web"

    def test_replace_preserves_original(self):
        f = Fact.of("heartbeat", "alice", service="api")
        dataclasses.replace(f, kind="deploy")
        assert f.kind == "heartbeat"

    def test_replace_observer(self):
        f = Fact.of("heartbeat", "alice", service="api")
        f2 = dataclasses.replace(f, observer="bob")
        assert f2.observer == "bob"
        assert f.observer == "alice"


# --- Origin ---


class TestOrigin:
    def test_default_origin_is_empty(self):
        f = Fact.of("heartbeat", "alice")
        assert f.origin == ""

    def test_explicit_origin(self):
        f = Fact(kind="tick.metric", ts=FIXED_TS, payload={"x": 1}, observer="v1", origin="my-vertex")
        assert f.origin == "my-vertex"

    def test_of_with_origin(self):
        f = Fact.of("tick.metric", "v1", origin="my-vertex", x=1)
        assert f.origin == "my-vertex"
        assert f.payload["x"] == 1

    def test_tick_with_origin(self):
        f = Fact.tick("hourly", "v1", origin="my-vertex", count=42)
        assert f.origin == "my-vertex"
        assert f.payload["count"] == 42

    def test_round_trip_preserves_origin(self):
        original = Fact(kind="metric", ts=FIXED_TS, payload={"x": 1}, observer="alice", origin="loop-a")
        rebuilt = Fact.from_dict(original.to_dict())
        assert rebuilt.origin == "loop-a"

    def test_round_trip_empty_origin(self):
        original = Fact.of("heartbeat", "alice")
        rebuilt = Fact.from_dict(original.to_dict())
        assert rebuilt.origin == ""

    def test_from_dict_missing_origin_defaults_empty(self):
        """Backward compat: old dicts without origin still work."""
        d = {"kind": "deploy", "ts": FIXED_TS, "payload": {"app": "web"}, "observer": "alice"}
        f = Fact.from_dict(d)
        assert f.origin == ""

    def test_frozen_origin(self):
        f = Fact.of("heartbeat", "alice")
        with pytest.raises(dataclasses.FrozenInstanceError):
            f.origin = "other"  # type: ignore[misc]


# --- Protocol edges (immutability, eq, hash) ---


class TestProtocolEdges:
    def test_delattr_raises_frozen(self):
        f = Fact.of("heartbeat", "alice")
        with pytest.raises(dataclasses.FrozenInstanceError):
            del f.kind

    def test_eq_returns_not_implemented_for_non_fact(self):
        f = Fact.of("heartbeat", "alice")
        assert f.__eq__("not a fact") is NotImplemented

    def test_hash_with_unhashable_payload(self):
        f = Fact(kind="data", ts=1.0, payload={"a": [1, 2]}, observer="x")
        # MappingProxyType with list values is unhashable — falls back to id()
        h = hash(f)
        assert isinstance(h, int)

    def test_class_getitem(self):
        assert Fact[str] is Fact
        assert Fact[int] is Fact

    def test_repr(self):
        f = Fact(kind="heartbeat", ts=1.0, payload="x", observer="a")
        r = repr(f)
        assert "kind='heartbeat'" in r
        assert "observer='a'" in r

    def test_dunder_replace(self):
        f = Fact(kind="heartbeat", ts=1.0, payload="x", observer="a")
        f2 = f.__replace__(kind="deploy")
        assert f2.kind == "deploy"
        assert f2.observer == "a"
