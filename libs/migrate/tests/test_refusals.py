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
    assert "GF-3 violation" in msg or "GF-3" in msg
    assert "line 10: observers 'alice', 'bob'" in msg
    assert "line 25: observers 'kyle', 'someone-else', 'third'" in msg
    assert "Advisory: repair the source line(s) by hand or re-run migration" in msg


def test_absent_observer_refusal_structured_data_and_message() -> None:
    """AbsentObserverBatchRefused carries structured offending_lines and advisory prose."""
    offending = [
        (12, 1, ("alice",)),
        (14, 2, ()),
    ]
    exc = AbsentObserverBatchRefused(offending, source="/path/to/legacy.jsonl")

    assert exc.source == "/path/to/legacy.jsonl"
    assert exc.absent_observer_lines == (
        (12, 1, ("alice",)),
        (14, 2, ()),
    )

    msg = str(exc)
    assert "missing the required 'observer' field" in msg
    assert "line 12: 1 row(s) missing 'observer' field (remaining observers: 'alice')" in msg
    assert "line 14: 2 row(s) missing 'observer' field" in msg
    assert "Advisory: repair the source line(s) by hand" in msg


def test_migration_refused_multi_class_structured_data_and_message() -> None:
    """MigrationRefused carries all 3 condition classes distinctly in structured data and message."""
    exc = MigrationRefused(
        codec_invalid_lines=[(2, "unknown field(s) in batch line: ['bad']")],
        mixed_observer_lines=[(4, ("kyle", "someone-else"), 0), (5, ("alice", "bob"), 1)],
        absent_observer_lines=[(6, 1, ("carol",))],
        source="/path/to/source.jsonl",
    )

    assert exc.source == "/path/to/source.jsonl"
    assert exc.codec_invalid_lines == ((2, "unknown field(s) in batch line: ['bad']"),)
    assert exc.mixed_observer_lines == (
        (4, ("kyle", "someone-else"), 0),
        (5, ("alice", "bob"), 1),
    )
    assert exc.absent_observer_lines == ((6, 1, ("carol",)),)

    msg = str(exc)
    assert "line 2: unknown field(s) in batch line: ['bad']" in msg
    assert "line 4: observers 'kyle', 'someone-else'" in msg
    assert "line 5: observers 'alice', 'bob' (1 row(s) missing 'observer' field)" in msg
    assert "line 6: 1 row(s) missing 'observer' field (remaining observers: 'carol')" in msg
    assert "Advisory: repair the source line(s) by hand or re-run migration after a ruled re-ceremony." in msg

