"""Tests for the Tick atom."""

from dataclasses import FrozenInstanceError, dataclass
from datetime import datetime, timezone

from ticks import Tick


NOW = datetime(2025, 6, 1, 12, 0, 0, tzinfo=timezone.utc)


# -- Construction --


def test_construct_with_int_payload():
    tick = Tick(ts=NOW, payload=42)
    assert tick.ts == NOW
    assert tick.payload == 42


def test_construct_with_str_payload():
    tick = Tick(ts=NOW, payload="snapshot")
    assert tick.payload == "snapshot"


def test_construct_with_dict_payload():
    state = {"count": 5, "total": 100}
    tick = Tick(ts=NOW, payload=state)
    assert tick.payload == state


def test_construct_with_list_payload():
    events = [1, 2, 3]
    tick = Tick(ts=NOW, payload=events)
    assert tick.payload == events


def test_construct_with_dataclass_payload():
    @dataclass(frozen=True)
    class Snapshot:
        value: int

    snap = Snapshot(value=7)
    tick = Tick(ts=NOW, payload=snap)
    assert tick.payload.value == 7


# -- Frozen --


def test_frozen_ts():
    tick = Tick(ts=NOW, payload=0)
    try:
        tick.ts = datetime.now(tz=timezone.utc)  # type: ignore[misc]
        assert False, "Should have raised"
    except FrozenInstanceError:
        pass


def test_frozen_payload():
    tick = Tick(ts=NOW, payload=0)
    try:
        tick.payload = 1  # type: ignore[misc]
        assert False, "Should have raised"
    except FrozenInstanceError:
        pass


# -- Equality --


def test_equal_ticks():
    a = Tick(ts=NOW, payload="x")
    b = Tick(ts=NOW, payload="x")
    assert a == b


def test_unequal_payload():
    a = Tick(ts=NOW, payload="x")
    b = Tick(ts=NOW, payload="y")
    assert a != b


def test_unequal_ts():
    other = datetime(2025, 1, 1, tzinfo=timezone.utc)
    a = Tick(ts=NOW, payload=1)
    b = Tick(ts=other, payload=1)
    assert a != b


# -- Hashing --


def test_hashable():
    tick = Tick(ts=NOW, payload=42)
    assert hash(tick) == hash(Tick(ts=NOW, payload=42))


def test_usable_in_set():
    a = Tick(ts=NOW, payload=1)
    b = Tick(ts=NOW, payload=1)
    c = Tick(ts=NOW, payload=2)
    assert len({a, b, c}) == 2


# -- Generic annotation --


def test_generic_annotation():
    """Tick[T] is usable as a type annotation."""
    t: Tick[int] = Tick(ts=NOW, payload=10)
    assert t.payload == 10


# -- Repr --


def test_repr():
    tick = Tick(ts=NOW, payload=42)
    r = repr(tick)
    assert "Tick" in r
    assert "42" in r
