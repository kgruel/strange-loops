"""Tests for the streaming topology primitives."""

import asyncio
import json
from dataclasses import dataclass
from pathlib import Path

import pytest

from framework.stream import Stream, Consumer, Tap
from framework.projection import Projection
from framework.store import EventStore
from framework.file_writer import FileWriter
from framework.forward import Forward


# --- Helpers ---


class Collector:
    """Simple consumer that collects events into a list."""

    def __init__(self):
        self.events: list = []

    async def consume(self, event) -> None:
        self.events.append(event)


@dataclass
class Tick:
    n: int


@dataclass
class Msg:
    text: str


# --- Core Stream tests ---


@pytest.mark.asyncio
async def test_fan_out():
    """One emit reaches N consumers."""
    stream: Stream[int] = Stream()
    c1, c2, c3 = Collector(), Collector(), Collector()
    stream.tap(c1)
    stream.tap(c2)
    stream.tap(c3)

    await stream.emit(42)

    assert c1.events == [42]
    assert c2.events == [42]
    assert c3.events == [42]


@pytest.mark.asyncio
async def test_filter():
    """Consumer only receives matching events."""
    stream: Stream[int] = Stream()
    evens = Collector()
    stream.tap(evens, filter=lambda x: x % 2 == 0)

    await stream.emit(1)
    await stream.emit(2)
    await stream.emit(3)
    await stream.emit(4)

    assert evens.events == [2, 4]


@pytest.mark.asyncio
async def test_transform():
    """Consumer receives transformed values."""
    stream: Stream[int] = Stream()
    doubled = Collector()
    stream.tap(doubled, transform=lambda x: x * 2)

    await stream.emit(5)
    await stream.emit(10)

    assert doubled.events == [10, 20]


@pytest.mark.asyncio
async def test_filter_and_transform():
    """Filter applies before transform."""
    stream: Stream[int] = Stream()
    c = Collector()
    stream.tap(c, filter=lambda x: x > 3, transform=lambda x: x * 10)

    await stream.emit(1)
    await stream.emit(5)
    await stream.emit(2)
    await stream.emit(7)

    assert c.events == [50, 70]


@pytest.mark.asyncio
async def test_multi_consumer_different_filters():
    """Different filters/transforms on same stream."""
    stream: Stream[int] = Stream()
    low = Collector()
    high = Collector()
    stream.tap(low, filter=lambda x: x < 5)
    stream.tap(high, filter=lambda x: x >= 5, transform=lambda x: -x)

    for i in range(10):
        await stream.emit(i)

    assert low.events == [0, 1, 2, 3, 4]
    assert high.events == [-5, -6, -7, -8, -9]


@pytest.mark.asyncio
async def test_detach():
    """Removed tap stops receiving."""
    stream: Stream[int] = Stream()
    c = Collector()
    tap = stream.tap(c)

    await stream.emit(1)
    stream.detach(tap)
    await stream.emit(2)

    assert c.events == [1]


@pytest.mark.asyncio
async def test_detach_idempotent():
    """Double detach is a no-op."""
    stream: Stream[int] = Stream()
    c = Collector()
    tap = stream.tap(c)
    stream.detach(tap)
    stream.detach(tap)  # should not raise
    assert stream.tap_count == 0


@pytest.mark.asyncio
async def test_consumer_protocol():
    """Collector satisfies Consumer protocol."""
    c = Collector()
    assert isinstance(c, Consumer)


# --- Projection as Consumer ---


class SumProjection(Projection[int, int]):
    def apply(self, state: int, event: int) -> int:
        return state + event


@pytest.mark.asyncio
async def test_projection_as_consumer():
    """Projection folds events directly from stream, state Signal updates."""
    stream: Stream[int] = Stream()
    proj = SumProjection(0)
    stream.tap(proj)

    await stream.emit(10)
    await stream.emit(20)
    await stream.emit(5)

    assert proj.state() == 35
    assert proj.cursor == 3


@pytest.mark.asyncio
async def test_projection_advance_still_works():
    """Existing advance-from-store mode still works."""
    store: EventStore[int] = EventStore()
    proj = SumProjection(0)

    store.add(1)
    store.add(2)
    store.add(3)
    proj.advance(store)

    assert proj.state() == 6
    assert proj.cursor == 3


# --- EventStore as Consumer ---


@pytest.mark.asyncio
async def test_store_as_consumer():
    """consume() appends, .since() still works."""
    stream: Stream[Tick] = Stream()
    store: EventStore[Tick] = EventStore()
    stream.tap(store)

    await stream.emit(Tick(1))
    await stream.emit(Tick(2))
    await stream.emit(Tick(3))

    assert store.events == [Tick(1), Tick(2), Tick(3)]
    assert store.since(1) == [Tick(2), Tick(3)]
    assert store.version() == 3


@pytest.mark.asyncio
async def test_store_add_still_works():
    """Existing add() API is unchanged."""
    store: EventStore[int] = EventStore()
    store.add(10)
    store.add(20)
    assert store.events == [10, 20]
    assert store.version() == 2


# --- Forward ---


@pytest.mark.asyncio
async def test_forward():
    """Events bridge between typed streams."""
    source: Stream[Tick] = Stream()
    target: Stream[str] = Stream()
    collector = Collector()
    target.tap(collector)

    fwd = Forward(target, transform=lambda t: f"tick-{t.n}")
    source.tap(fwd)

    await source.emit(Tick(1))
    await source.emit(Tick(2))

    assert collector.events == ["tick-1", "tick-2"]


@pytest.mark.asyncio
async def test_forward_chain():
    """Forward can chain through multiple streams."""
    s1: Stream[int] = Stream()
    s2: Stream[str] = Stream()
    s3: Stream[str] = Stream()
    end = Collector()
    s3.tap(end)

    s1.tap(Forward(s2, transform=lambda x: str(x)))
    s2.tap(Forward(s3, transform=lambda s: s + "!"))

    await s1.emit(42)
    assert end.events == ["42!"]


# --- FileWriter ---


@pytest.mark.asyncio
async def test_file_writer(tmp_path):
    """Serializes events to JSONL file correctly."""
    path = tmp_path / "events.jsonl"
    stream: Stream[Tick] = Stream()

    writer = FileWriter(path, serialize=lambda t: {"n": t.n})
    stream.tap(writer)

    await stream.emit(Tick(1))
    await stream.emit(Tick(2))
    await stream.emit(Tick(3))

    writer.close()

    lines = path.read_text().strip().split("\n")
    assert len(lines) == 3
    assert json.loads(lines[0]) == {"n": 1}
    assert json.loads(lines[1]) == {"n": 2}
    assert json.loads(lines[2]) == {"n": 3}


@pytest.mark.asyncio
async def test_file_writer_context_manager(tmp_path):
    """FileWriter works as context manager."""
    path = tmp_path / "out.jsonl"
    with FileWriter(path, serialize=lambda x: {"v": x}) as fw:
        await fw.consume(10)
        await fw.consume(20)

    lines = path.read_text().strip().split("\n")
    assert json.loads(lines[0]) == {"v": 10}
    assert json.loads(lines[1]) == {"v": 20}


# --- Integration: full pipeline ---


@pytest.mark.asyncio
async def test_full_pipeline(tmp_path):
    """Stream -> [Store, Projection, FileWriter] all receive events."""
    stream: Stream[int] = Stream()

    store: EventStore[int] = EventStore()
    proj = SumProjection(0)
    path = tmp_path / "log.jsonl"
    writer = FileWriter(path, serialize=lambda x: {"val": x})

    stream.tap(store)
    stream.tap(proj)
    stream.tap(writer)

    for i in range(1, 6):
        await stream.emit(i)

    writer.close()

    assert store.events == [1, 2, 3, 4, 5]
    assert proj.state() == 15
    lines = path.read_text().strip().split("\n")
    assert len(lines) == 5


@pytest.mark.asyncio
async def test_detach_during_emit():
    """Detaching during emit doesn't crash (snapshot iteration)."""
    stream: Stream[int] = Stream()
    c1 = Collector()
    c2 = Collector()

    tap1 = stream.tap(c1)
    stream.tap(c2)

    # After first emit, detach c1
    await stream.emit(1)
    stream.detach(tap1)
    await stream.emit(2)

    assert c1.events == [1]
    assert c2.events == [1, 2]
