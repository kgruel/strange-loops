"""Tests for the Tick atom."""

from dataclasses import FrozenInstanceError, dataclass
from datetime import datetime, timezone

from engine import Tick


NOW = datetime(2025, 6, 1, 12, 0, 0, tzinfo=timezone.utc)
EARLIER = datetime(2025, 6, 1, 11, 0, 0, tzinfo=timezone.utc)


# -- Construction --


def test_construct_with_name():
    tick = Tick(name="my-loop", ts=NOW, payload=42)
    assert tick.name == "my-loop"
    assert tick.ts == NOW
    assert tick.payload == 42


def test_construct_with_int_payload():
    tick = Tick(name="test", ts=NOW, payload=42)
    assert tick.ts == NOW
    assert tick.payload == 42


def test_construct_with_str_payload():
    tick = Tick(name="test", ts=NOW, payload="snapshot")
    assert tick.payload == "snapshot"


def test_construct_with_dict_payload():
    state = {"count": 5, "total": 100}
    tick = Tick(name="test", ts=NOW, payload=state)
    assert tick.payload == state


def test_construct_with_list_payload():
    events = [1, 2, 3]
    tick = Tick(name="test", ts=NOW, payload=events)
    assert tick.payload == events


def test_construct_with_dataclass_payload():
    @dataclass(frozen=True)
    class Snapshot:
        value: int

    snap = Snapshot(value=7)
    tick = Tick(name="test", ts=NOW, payload=snap)
    assert tick.payload.value == 7


# -- Tick.since (fidelity traversal) --


def test_since_defaults_to_none():
    tick = Tick(name="test", ts=NOW, payload=42)
    assert tick.since is None


def test_since_can_be_set():
    tick = Tick(name="test", ts=NOW, payload=42, since=EARLIER)
    assert tick.since == EARLIER


def test_since_included_in_equality():
    a = Tick(name="test", ts=NOW, payload=42, since=EARLIER)
    b = Tick(name="test", ts=NOW, payload=42, since=EARLIER)
    c = Tick(name="test", ts=NOW, payload=42, since=None)
    assert a == b
    assert a != c


def test_since_included_in_hash():
    a = Tick(name="test", ts=NOW, payload=42, since=EARLIER)
    b = Tick(name="test", ts=NOW, payload=42, since=None)
    # Different since values should produce different hashes
    assert hash(a) != hash(b)


def test_since_frozen():
    tick = Tick(name="test", ts=NOW, payload=0, since=EARLIER)
    try:
        tick.since = None  # type: ignore[misc]
        assert False, "Should have raised"
    except FrozenInstanceError:
        pass


# -- Frozen --


def test_frozen_name():
    tick = Tick(name="test", ts=NOW, payload=0)
    try:
        tick.name = "other"  # type: ignore[misc]
        assert False, "Should have raised"
    except FrozenInstanceError:
        pass


def test_frozen_ts():
    tick = Tick(name="test", ts=NOW, payload=0)
    try:
        tick.ts = datetime.now(tz=timezone.utc)  # type: ignore[misc]
        assert False, "Should have raised"
    except FrozenInstanceError:
        pass


def test_frozen_payload():
    tick = Tick(name="test", ts=NOW, payload=0)
    try:
        tick.payload = 1  # type: ignore[misc]
        assert False, "Should have raised"
    except FrozenInstanceError:
        pass


# -- Equality --


def test_equal_ticks():
    a = Tick(name="test", ts=NOW, payload="x")
    b = Tick(name="test", ts=NOW, payload="x")
    assert a == b


def test_unequal_payload():
    a = Tick(name="test", ts=NOW, payload="x")
    b = Tick(name="test", ts=NOW, payload="y")
    assert a != b


def test_unequal_ts():
    other = datetime(2025, 1, 1, tzinfo=timezone.utc)
    a = Tick(name="test", ts=NOW, payload=1)
    b = Tick(name="test", ts=other, payload=1)
    assert a != b


def test_unequal_name():
    a = Tick(name="loop-a", ts=NOW, payload=1)
    b = Tick(name="loop-b", ts=NOW, payload=1)
    assert a != b


# -- Hashing --


def test_hashable():
    tick = Tick(name="test", ts=NOW, payload=42)
    assert hash(tick) == hash(Tick(name="test", ts=NOW, payload=42))


def test_usable_in_set():
    a = Tick(name="test", ts=NOW, payload=1)
    b = Tick(name="test", ts=NOW, payload=1)
    c = Tick(name="test", ts=NOW, payload=2)
    assert len({a, b, c}) == 2


# -- Generic annotation --


def test_generic_annotation():
    """Tick[T] is usable as a type annotation."""
    t: Tick[int] = Tick(name="test", ts=NOW, payload=10)
    assert t.payload == 10


# -- Repr --


def test_repr():
    tick = Tick(name="test", ts=NOW, payload=42)
    r = repr(tick)
    assert "Tick" in r
    assert "42" in r
    assert "test" in r


# -- Projection fold callable --

import pytest
from engine import EventStore
from engine.projection import Projection


class TestProjectionFoldCallable:
    """Tests for Projection with a fold callable instead of subclassing."""

    async def test_fold_callable_via_consume(self):
        def add(state: int, event: int) -> int:
            return state + event

        proj = Projection(0, fold=add)
        await proj.consume(5)
        await proj.consume(3)
        assert proj.state == 8
        assert proj.version == 2

    def test_fold_callable_via_advance(self):
        def add(state: int, event: int) -> int:
            return state + event

        store: EventStore[int] = EventStore()
        store.append(10)
        store.append(20)

        proj = Projection(0, fold=add)
        proj.advance(store)
        assert proj.state == 30
        assert proj.version == 1
        assert proj.cursor == 2

    def test_fold_callable_advance_incremental(self):
        def add(state: int, event: int) -> int:
            return state + event

        store: EventStore[int] = EventStore()
        store.append(1)
        store.append(2)

        proj = Projection(0, fold=add)
        proj.advance(store)
        assert proj.state == 3

        store.append(3)
        proj.advance(store)
        assert proj.state == 6
        assert proj.cursor == 3

    async def test_no_fold_raises_not_implemented(self):
        proj = Projection(0)
        with pytest.raises(NotImplementedError):
            await proj.consume(1)

    async def test_subclass_still_works(self):
        class SumProjection(Projection[int, int]):
            def apply(self, state: int, event: int) -> int:
                return state + event

        proj = SumProjection(0)
        await proj.consume(7)
        assert proj.state == 7


# -- Serialization (to_dict / from_dict) --


class TestTickSerialization:
    def test_to_dict_round_trip(self):
        tick = Tick(name="my-loop", ts=NOW, payload={"count": 5}, origin="v1")
        d = tick.to_dict()
        restored = Tick.from_dict(d)
        assert restored.name == tick.name
        assert restored.ts == tick.ts
        assert restored.payload == tick.payload
        assert restored.origin == tick.origin
        assert restored.since is None

    def test_to_dict_with_since(self):
        tick = Tick(name="loop", ts=NOW, payload=42, origin="v1", since=EARLIER)
        d = tick.to_dict()
        assert isinstance(d["ts"], float)
        assert isinstance(d["since"], float)

        restored = Tick.from_dict(d)
        assert restored.since == EARLIER
        assert restored.ts == NOW

    def test_to_dict_since_none_stays_none(self):
        tick = Tick(name="loop", ts=NOW, payload="x")
        d = tick.to_dict()
        assert d["since"] is None
        restored = Tick.from_dict(d)
        assert restored.since is None

    def test_from_dict_missing_origin_defaults_empty(self):
        d = {"name": "test", "ts": NOW.timestamp(), "payload": 1, "since": None}
        restored = Tick.from_dict(d)
        assert restored.origin == ""
