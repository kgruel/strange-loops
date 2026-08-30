"""Tests for migrate refusals hierarchy and properties."""

from __future__ import annotations

from engine.arrival_body import ArrivalBodyError

from migrate.refusals import (
    AbsentObserverBatchRefused,
    MigrationRefused,
    MissingObserverBatchRefused,
    MixedObserverBatchRefused,
)


def test_refusal_hierarchy_roots_in_migration_refused() -> None:
    """Refusals must root in MigrationRefused, distinct from
    ArrivalBodyError and ContractRefusal."""
    assert issubclass(MixedObserverBatchRefused, MigrationRefused)
    assert issubclass(AbsentObserverBatchRefused, MigrationRefused)
    assert MissingObserverBatchRefused is AbsentObserverBatchRefused

    # Must NOT subclass or wrap ArrivalBodyError
    assert not issubclass(MigrationRefused, ArrivalBodyError)
    assert not issubclass(MixedObserverBatchRefused, ArrivalBodyError)
    assert not issubclass(AbsentObserverBatchRefused, ArrivalBodyError)

    # Subclass of Exception
    assert issubclass(MigrationRefused, Exception)


def test_mixed_observer_refusal_structured_data_and_message() -> None:
    """MixedObserverBatchRefused carries structured offending_lines and advisory prose."""
    offending = [
        (10, ("alice", "bob")),
        (25, ("kyle", "someone-else", "third")),
    ]
    exc = MixedObserverBatchRefused(offending, source="/path/to/legacy.jsonl")

    assert exc.source == "/path/to/legacy.jsonl"
    assert exc.offending_lines == (
        (10, ("alice", "bob")),
        (25, ("kyle", "someone-else", "third")),
    )

    msg = str(exc)
    assert "GF-3: mixed-observer batch lines found" in msg
    assert "line 10: observers 'alice', 'bob'" in msg
    assert "line 25: observers 'kyle', 'someone-else', 'third'" in msg
    assert "Advisory: repair the source line(s) by hand or re-run migration" in msg


def test_absent_observer_refusal_structured_data_and_message() -> None:
    """AbsentObserverBatchRefused carries structured offending_lines and advisory prose."""
    offending = [
        (12, ("alice",)),
        (14, ()),
    ]
    exc = AbsentObserverBatchRefused(offending, source="/path/to/legacy.jsonl")

    assert exc.source == "/path/to/legacy.jsonl"
    assert exc.offending_lines == (
        (12, ("alice",)),
        (14, ()),
    )

    msg = str(exc)
    assert "batch rows missing observer field" in msg
    assert "line 12: missing observer field (found observers: 'alice')" in msg
    assert "line 14: missing observer field" in msg
    assert "Advisory: repair the source line(s) by hand" in msg
