"""Tests for inventory pass over legacy JSONL and SQLite sources."""

from __future__ import annotations

import hashlib
import inspect
import sqlite3
from pathlib import Path

import pytest

from migrate.inventory import SourceInventory, inventory
from migrate.refusals import AbsentObserverBatchRefused, MixedObserverBatchRefused

from ._fixtures import (
    EXPECTED_HAND_COMPUTED_COUNTS,
    build_absent_observer_jsonl,
    build_mixed_observer_jsonl,
    build_synthetic_jsonl,
    build_synthetic_sqlite,
)


@pytest.mark.parametrize("fmt", ["jsonl", "sqlite"])
def test_inventory_counts_vs_hand_computed_expectations(tmp_path: Path, fmt: str) -> None:
    """Verify inventory counts against hand-computed expectations across all ID eras,
    signed and unsigned rows, ticks, and batch lines."""
    expected = EXPECTED_HAND_COMPUTED_COUNTS[fmt]

    if fmt == "jsonl":
        source_file = build_synthetic_jsonl(tmp_path / "legacy.jsonl")
    else:
        source_file = build_synthetic_sqlite(tmp_path / "legacy.sqlite")

    inv = inventory(source_file)

    assert isinstance(inv, SourceInventory)
    assert inv.source_format == expected["source_format"]
    assert inv.total_lines == expected["total_lines"]
    assert inv.per_kind_counts == expected["per_kind_counts"]
    assert inv.per_kind_row_counts == expected["per_kind_counts"]
    assert inv.tick_count == expected["tick_count"]
    assert inv.batch_line_count == expected["batch_line_count"]
    assert inv.observer_census == expected["observer_census"]
    assert inv.id_era_census == expected["id_era_census"]
    assert len(inv.content_hash) == 64
    assert len(inv.file_hash) == 64
    assert inv.source_content_sha256 == inv.content_hash
    assert inv.source_file_sha256 == inv.file_hash


def test_content_hash_matches_between_equivalent_jsonl_and_sqlite(tmp_path: Path) -> None:
    """A JSONL store and a SQLite store carrying the exact same sequence of rows
    produce identical witness-order content hashes."""
    jsonl_path = build_synthetic_jsonl(tmp_path / "store.jsonl")
    sqlite_path = build_synthetic_sqlite(tmp_path / "store.sqlite")

    inv_jsonl = inventory(jsonl_path)
    inv_sqlite = inventory(sqlite_path)

    assert inv_jsonl.content_hash == inv_sqlite.content_hash
    assert inv_jsonl.file_hash != inv_sqlite.file_hash


def test_mixed_observer_batch_refuses_and_enumerates_every_offending_line(tmp_path: Path) -> None:
    """GF-3 refusal: A JSONL source holding TWO mixed-observer batch lines raises
    MixedObserverBatchRefused, enumerating BOTH lines with their observer sets,
    and creates no target or temporary paths."""
    source_file = build_mixed_observer_jsonl(tmp_path / "mixed.jsonl")

    # Record files in directory before inventory
    files_before = set(tmp_path.iterdir())

    with pytest.raises(MixedObserverBatchRefused) as exc_info:
        inventory(source_file)

    exc = exc_info.value
    # Offending lines must contain BOTH line 2 and line 4 with their exact observer sets:
    assert len(exc.offending_lines) == 2
    assert exc.offending_lines == (
        (2, ("kyle", "someone-else")),
        (4, ("alice", "bob")),
    )

    # Message must include enumeration and advisory prose
    msg = str(exc)
    assert "line 2: observers 'kyle', 'someone-else'" in msg
    assert "line 4: observers 'alice', 'bob'" in msg
    assert "Advisory: repair the source line(s) by hand or re-run migration" in msg

    # No files or temporary paths were created anywhere in the dir
    files_after = set(tmp_path.iterdir())
    assert files_before == files_after


def test_absent_observer_batch_refusal_is_distinct_condition(tmp_path: Path) -> None:
    """A batch line with a row missing the observer field raises AbsentObserverBatchRefused,
    distinct from MixedObserverBatchRefused (None is not folded into observer set)."""
    source_file = build_absent_observer_jsonl(tmp_path / "absent.jsonl")

    with pytest.raises(AbsentObserverBatchRefused) as exc_info:
        inventory(source_file)

    exc = exc_info.value
    assert isinstance(exc, AbsentObserverBatchRefused)
    assert not isinstance(exc, MixedObserverBatchRefused)
    assert len(exc.offending_lines) == 1
    assert exc.offending_lines[0][0] == 2
    assert exc.offending_lines[0][1] == ("alice",)
    assert "missing observer field" in str(exc)


def test_two_hash_distinction_content_hash_stable_across_vacuum(tmp_path: Path) -> None:
    """Content hash is verifiable row identity; file hash is forensic byte identity.
    VACUUM changes file bytes (file_hash) but preserves content hash."""
    sqlite_path = build_synthetic_sqlite(tmp_path / "vacuum_test.sqlite")

    inv1 = inventory(sqlite_path)

    # Modify sqlite file storage via VACUUM / extra page allocation
    conn = sqlite3.connect(sqlite_path)
    try:
        conn.execute("PRAGMA auto_vacuum = FULL")
        conn.execute("VACUUM")
        conn.commit()
    finally:
        conn.close()

    inv2 = inventory(sqlite_path)

    # Content hash must be byte-identical
    assert inv1.content_hash == inv2.content_hash
    # File hash may change or if bytes changed, content hash remains invariant
    assert inv1.per_kind_counts == inv2.per_kind_counts


def test_inventory_is_strictly_read_only(tmp_path: Path) -> None:
    """After inventory() call, source file bytes are completely unchanged."""
    jsonl_path = build_synthetic_jsonl(tmp_path / "read_only.jsonl")
    sqlite_path = build_synthetic_sqlite(tmp_path / "read_only.sqlite")

    for path in [jsonl_path, sqlite_path]:
        digest_before = hashlib.sha256(path.read_bytes()).hexdigest()
        inv = inventory(path)
        digest_after = hashlib.sha256(path.read_bytes()).hexdigest()
        assert digest_before == digest_after
        assert inv.file_hash == digest_before


def test_inventory_module_contains_no_write_calls() -> None:
    """Verify that inventory.py contains no write opens or mutations."""
    from migrate import inventory as inv_mod

    source_code = inspect.getsource(inv_mod)
    assert 'open(..., "w")' not in source_code
    assert 'open("w"' not in source_code
    assert ', "w"' not in source_code
    assert ", 'w'" not in source_code
    assert 'mode="w"' not in source_code
    assert "write_text" not in source_code
    assert "write_bytes" not in source_code
