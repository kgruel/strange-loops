"""Tests for the JSONL tailer."""

import json
from dataclasses import dataclass, asdict
from pathlib import Path

import pytest

from framework.tailer import Tailer


@dataclass
class Event:
    kind: str
    value: int


def serialize(e: Event) -> dict:
    return asdict(e)


def deserialize(d: dict) -> Event:
    return Event(**d)


def write_events(path: Path, events: list[Event]) -> None:
    with path.open("a") as f:
        for e in events:
            f.write(json.dumps(serialize(e)) + "\n")


# --- Basic operation ---


def test_poll_empty_file(tmp_path):
    """Poll on empty file returns nothing."""
    path = tmp_path / "events.jsonl"
    path.touch()
    tailer: Tailer[Event] = Tailer(path, deserialize)
    assert tailer.poll() == []


def test_poll_nonexistent_file(tmp_path):
    """Poll on missing file returns nothing (file not yet created)."""
    path = tmp_path / "events.jsonl"
    tailer: Tailer[Event] = Tailer(path, deserialize)
    assert tailer.poll() == []


def test_poll_reads_all_lines(tmp_path):
    """First poll reads all existing content."""
    path = tmp_path / "events.jsonl"
    events = [Event("a", 1), Event("b", 2), Event("c", 3)]
    write_events(path, events)

    tailer: Tailer[Event] = Tailer(path, deserialize)
    result = tailer.poll()
    assert result == events


def test_poll_incremental(tmp_path):
    """Second poll only returns new events."""
    path = tmp_path / "events.jsonl"
    write_events(path, [Event("a", 1), Event("b", 2)])

    tailer: Tailer[Event] = Tailer(path, deserialize)
    first = tailer.poll()
    assert len(first) == 2

    # Write more
    write_events(path, [Event("c", 3)])
    second = tailer.poll()
    assert second == [Event("c", 3)]


def test_poll_no_new_data(tmp_path):
    """Poll with no new data returns empty list."""
    path = tmp_path / "events.jsonl"
    write_events(path, [Event("a", 1)])

    tailer: Tailer[Event] = Tailer(path, deserialize)
    tailer.poll()
    assert tailer.poll() == []


# --- Incomplete lines ---


def test_incomplete_line_skipped(tmp_path):
    """Incomplete trailing line (no newline) is left for next poll."""
    path = tmp_path / "events.jsonl"
    write_events(path, [Event("a", 1)])
    # Append incomplete line (no trailing newline)
    with path.open("a") as f:
        f.write('{"kind": "b", "value": 2}')

    tailer: Tailer[Event] = Tailer(path, deserialize)
    result = tailer.poll()
    assert result == [Event("a", 1)]  # incomplete line not returned

    # Complete the line
    with path.open("a") as f:
        f.write("\n")

    result = tailer.poll()
    assert result == [Event("b", 2)]


# --- Offset tracking ---


def test_offset_advances(tmp_path):
    """Offset tracks byte position correctly."""
    path = tmp_path / "events.jsonl"
    write_events(path, [Event("a", 1)])

    tailer: Tailer[Event] = Tailer(path, deserialize)
    assert tailer.offset == 0
    tailer.poll()
    assert tailer.offset > 0


def test_reset(tmp_path):
    """Reset replays from beginning."""
    path = tmp_path / "events.jsonl"
    write_events(path, [Event("a", 1), Event("b", 2)])

    tailer: Tailer[Event] = Tailer(path, deserialize)
    first = tailer.poll()
    assert len(first) == 2

    tailer.reset()
    replayed = tailer.poll()
    assert replayed == first


def test_offset_setter(tmp_path):
    """Can set offset to resume from a stored checkpoint."""
    path = tmp_path / "events.jsonl"
    write_events(path, [Event("a", 1), Event("b", 2), Event("c", 3)])

    # Read all to get final offset
    tailer: Tailer[Event] = Tailer(path, deserialize)
    tailer.poll()
    checkpoint = tailer.offset

    # New tailer starting from checkpoint sees nothing
    tailer2: Tailer[Event] = Tailer(path, deserialize)
    tailer2.offset = checkpoint
    assert tailer2.poll() == []

    # But new events after checkpoint are visible
    write_events(path, [Event("d", 4)])
    assert tailer2.poll() == [Event("d", 4)]


# --- Composition with FileWriter ---


@pytest.mark.asyncio
async def test_filewriter_tailer_roundtrip(tmp_path):
    """FileWriter writes, Tailer reads — the full producer/consumer loop."""
    from framework.file_writer import FileWriter

    path = tmp_path / "events.jsonl"
    writer: FileWriter[Event] = FileWriter(path, serialize)
    tailer: Tailer[Event] = Tailer(path, deserialize)

    # Write some events
    await writer.consume(Event("x", 10))
    await writer.consume(Event("y", 20))

    # Tailer picks them up
    result = tailer.poll()
    assert result == [Event("x", 10), Event("y", 20)]

    # Write more
    await writer.consume(Event("z", 30))
    result = tailer.poll()
    assert result == [Event("z", 30)]

    writer.close()


# --- Composition with Projection ---


def test_tailer_feeds_projection(tmp_path):
    """Tailer events can drive a Projection's fold."""
    from framework.projection import Projection

    class SumProjection(Projection[int, Event]):
        def apply(self, state: int, event: Event) -> int:
            return state + event.value

    path = tmp_path / "events.jsonl"
    write_events(path, [Event("a", 1), Event("b", 2), Event("c", 3)])

    tailer: Tailer[Event] = Tailer(path, deserialize)
    proj = SumProjection(initial=0)

    # Feed tailer output to projection
    for event in tailer.poll():
        proj._state = proj.apply(proj._state, event)
        proj._version += 1

    assert proj.state == 6
    assert proj.version == 3
