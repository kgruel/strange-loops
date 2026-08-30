"""Tests for migrate refusals hierarchy and properties."""

from __future__ import annotations

from engine.arrival_body import ArrivalBodyError

from migrate.refusals import (
    LegacySourceRefused,
    MigrationRefused,
)


def test_refusal_hierarchy_roots_in_migration_refused() -> None:
    """Refusals must root in MigrationRefused, distinct from
    ArrivalBodyError and ContractRefusal."""
    assert issubclass(LegacySourceRefused, MigrationRefused)

    # Must NOT subclass or wrap ArrivalBodyError
    assert not issubclass(MigrationRefused, ArrivalBodyError)
    assert not issubclass(LegacySourceRefused, ArrivalBodyError)

    # Subclass of Exception
    assert issubclass(MigrationRefused, Exception)


def test_legacy_source_refused_mixed_observer_structured_data_and_message() -> None:
    """LegacySourceRefused carries structured mixed_observer_lines and advisory prose."""
    mixed = [
        (10, ("alice", "bob"), 0),
        (25, ("kyle", "someone-else", "third"), 0),
    ]
    exc = LegacySourceRefused(mixed_observer_lines=mixed, source="/path/to/legacy.jsonl")

    assert exc.source == "/path/to/legacy.jsonl"
    assert exc.mixed_observer_lines == (
        (10, ("alice", "bob"), 0),
        (25, ("kyle", "someone-else", "third"), 0),
    )

    msg = str(exc)
    assert "GF-3 violation" in msg or "GF-3" in msg
    assert "line 10: observers 'alice', 'bob'" in msg
    assert "line 25: observers 'kyle', 'someone-else', 'third'" in msg
    assert "Advisory: repair the source line(s) by hand or re-run migration" in msg


def test_legacy_source_refused_absent_observer_structured_data_and_message() -> None:
    """LegacySourceRefused carries structured absent_observer_lines and advisory prose."""
    absent = [
        (12, 1, ("alice",)),
        (14, 2, ()),
    ]
    exc = LegacySourceRefused(absent_observer_lines=absent, source="/path/to/legacy.jsonl")

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


def test_legacy_source_refused_multi_class_structured_data_and_message() -> None:
    """LegacySourceRefused carries all 3 condition classes distinctly in structured data and message."""
    exc = LegacySourceRefused(
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


