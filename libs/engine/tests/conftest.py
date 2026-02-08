"""Shared fixtures for ticks tests.

Fixtures follow the principle: provide building blocks, not pre-wired scenarios.
Tests compose fixtures to express their specific intent.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from engine import EventStore, FileWriter, Stream, Tailer

from tests.helpers import (
    CountProjection,
    Event,
    SumProjection,
    deserialize_event,
    serialize_event,
)


@pytest.fixture
def tmp_jsonl(tmp_path: Path) -> Path:
    """Temporary JSONL file path (not created yet)."""
    return tmp_path / "events.jsonl"


@pytest.fixture
def stream() -> Stream[Event]:
    """Fresh Stream[Event]."""
    return Stream[Event]()


@pytest.fixture
def event_store() -> EventStore[Event]:
    """In-memory EventStore (no persistence)."""
    return EventStore[Event]()


@pytest.fixture
def sum_projection() -> SumProjection:
    """SumProjection starting at 0."""
    return SumProjection(initial=0)


@pytest.fixture
def count_projection() -> CountProjection:
    """CountProjection starting at 0."""
    return CountProjection(initial=0)


@pytest.fixture
def file_writer(tmp_jsonl: Path) -> FileWriter[Event]:
    """FileWriter that serializes Event to JSONL."""
    return FileWriter(tmp_jsonl, serialize_event)


@pytest.fixture
def tailer(tmp_jsonl: Path) -> Tailer[Event]:
    """Tailer that deserializes Event from JSONL."""
    return Tailer(tmp_jsonl, deserialize_event)
