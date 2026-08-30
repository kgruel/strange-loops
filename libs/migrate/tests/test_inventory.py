"""Tests for inventory pass over legacy JSONL and SQLite sources."""

from __future__ import annotations

import hashlib
import json
import sqlite3
from pathlib import Path

import pytest

from migrate.inventory import SourceInventory, inventory
from migrate.refusals import (
    LegacySourceRefused,
    MigrationRefused,
)

from ._fixtures import (
    EXPECTED_HAND_COMPUTED_COUNTS,
    build_absent_observer_jsonl,
    build_both_aspects_batch_jsonl,
    build_combined_defects_jsonl,
    build_flat_equivalent_jsonl,
    build_mixed_observer_jsonl,
    build_synthetic_jsonl,
    build_synthetic_sqlite,
    build_type_error_batch_jsonl,
)


def _snapshot_dir(dir_path: Path) -> dict[str, tuple[int, int]]:
    """Recursive snapshot of a directory: {rel_path: (size, mtime_ns)}."""
    snapshot: dict[str, tuple[int, int]] = {}
    for p in sorted(dir_path.rglob("*")):
        rel = str(p.relative_to(dir_path))
        stat = p.stat()
        snapshot[rel] = (stat.st_size, stat.st_mtime_ns)
    return snapshot


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
    assert inv.total_rows == expected["total_rows"]
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


def test_jsonl_content_hash_stability_and_sensitivity(tmp_path: Path) -> None:
    """JSONL arm content hash: stable on re-inventory, sensitive to row mutation,
    and invariant to batch grouping (2-row batch and flat rows hash identically)."""
    jsonl_path = build_synthetic_jsonl(tmp_path / "store.jsonl")
    flat_path = build_flat_equivalent_jsonl(tmp_path / "flat.jsonl")

    inv1 = inventory(jsonl_path)
    inv2 = inventory(jsonl_path)
    inv_flat = inventory(flat_path)

    # Stability: same source -> same hash
    assert inv1.content_hash == inv2.content_hash
    # Batch grouping invariance: batch envelope does NOT alter row content hash
    assert inv1.content_hash == inv_flat.content_hash

    # Sensitivity: mutate a single row in JSONL -> content hash changes
    mutated_path = tmp_path / "mutated.jsonl"
    lines = jsonl_path.read_text(encoding="utf-8").splitlines()
    first_obj = json.loads(lines[0])
    first_obj["payload"] = '{"text":"mutated fact"}'
    lines[0] = json.dumps(first_obj, separators=(",", ":"))
    mutated_path.write_text("\n".join(lines) + "\n", encoding="utf-8")

    inv_mutated = inventory(mutated_path)
    assert inv_mutated.content_hash != inv1.content_hash


def test_sqlite_content_hash_stability_and_sensitivity(tmp_path: Path) -> None:
    """SQLite arm content hash: stable on re-inventory and across VACUUM,
    and sensitive to row mutation."""
    sqlite_path = build_synthetic_sqlite(tmp_path / "store.sqlite")

    inv1 = inventory(sqlite_path)
    inv2 = inventory(sqlite_path)

    # Stability: same source -> same hash
    assert inv1.content_hash == inv2.content_hash

    # Invariant to VACUUM: file hash changes, content hash stable
    conn = sqlite3.connect(sqlite_path)
    try:
        conn.execute("PRAGMA auto_vacuum = FULL")
        conn.execute("VACUUM")
        conn.commit()
    finally:
        conn.close()

    inv_vac = inventory(sqlite_path)
    assert inv_vac.content_hash == inv1.content_hash

    # Sensitivity: mutate a single row in SQLite -> content hash changes
    mut_conn = sqlite3.connect(sqlite_path)
    try:
        mut_conn.execute("UPDATE facts SET payload = '{\"text\":\"mutated\"}' WHERE rowid = 1")
        mut_conn.commit()
    finally:
        mut_conn.close()

    inv_mut = inventory(sqlite_path)
    assert inv_mut.content_hash != inv1.content_hash


def test_mixed_observer_batch_refuses_and_enumerates_every_offending_line(tmp_path: Path) -> None:
    """GF-3 refusal: A JSONL source holding TWO mixed-observer batch lines raises
    LegacySourceRefused, enumerating BOTH lines with their observer sets."""
    source_file = build_mixed_observer_jsonl(tmp_path / "mixed.jsonl")

    with pytest.raises(LegacySourceRefused) as exc_info:
        inventory(source_file)

    exc = exc_info.value
    assert len(exc.mixed_observer_lines) == 2
    assert exc.mixed_observer_lines == (
        (2, ("kyle", "someone-else"), 0),
        (4, ("alice", "bob"), 0),
    )

    msg = str(exc)
    assert "line 2: observers 'kyle', 'someone-else'" in msg
    assert "line 4: observers 'alice', 'bob'" in msg
    assert "Advisory: repair the source line(s) by hand or re-run migration" in msg


def test_absent_observer_batch_refusal_is_distinct_condition(tmp_path: Path) -> None:
    """A batch line with a row missing the observer field raises LegacySourceRefused
    with absent_observer_lines populated."""
    source_file = build_absent_observer_jsonl(tmp_path / "absent.jsonl")

    with pytest.raises(LegacySourceRefused) as exc_info:
        inventory(source_file)

    exc = exc_info.value
    assert isinstance(exc, LegacySourceRefused)
    assert len(exc.mixed_observer_lines) == 0
    assert len(exc.absent_observer_lines) == 1
    assert exc.absent_observer_lines[0] == (2, 1, ("alice",))
    assert "1 row(s) missing 'observer' field" in str(exc)


def test_combined_defects_scan_collects_all_three_classes_without_preemption(tmp_path: Path) -> None:
    """Combined defect fixture with codec-invalid + mixed + absent lines together.
    Whole source is scanned before raising, and all 3 classes are enumerated without preemption."""
    source_file = build_combined_defects_jsonl(tmp_path / "combined.jsonl")

    with pytest.raises(MigrationRefused) as exc_info:
        inventory(source_file)

    exc = exc_info.value
    # Assert line 2 is codec-invalid
    assert len(exc.codec_invalid_lines) == 1
    assert exc.codec_invalid_lines[0][0] == 2
    assert "unknown field(s) in batch line" in exc.codec_invalid_lines[0][1]

    # Assert line 4 is mixed-observer
    assert len(exc.mixed_observer_lines) == 1
    assert exc.mixed_observer_lines[0][0] == 4
    assert exc.mixed_observer_lines[0][1] == ("kyle", "someone-else")

    # Assert line 6 is absent-observer
    assert len(exc.absent_observer_lines) == 1
    assert exc.absent_observer_lines[0][0] == 6
    assert exc.absent_observer_lines[0][1] == 1  # 1 absent row
    assert exc.absent_observer_lines[0][2] == ("alice",)

    # Check formatted message presents all classes
    msg = str(exc)
    assert "line 2: unknown field(s) in batch line" in msg
    assert "line 4: observers 'kyle', 'someone-else'" in msg
    assert "line 6: 1 row(s) missing 'observer' field (remaining observers: 'alice')" in msg


def test_both_aspects_batch_reported_once_under_mixed_class(tmp_path: Path) -> None:
    """A batch line exhibiting BOTH mixed and absent aspects (alice, bob, 1 observerless row)
    is reported ONCE under mixed class with both aspects visible, never hidden under absent."""
    source_file = build_both_aspects_batch_jsonl(tmp_path / "both.jsonl")

    with pytest.raises(MigrationRefused) as exc_info:
        inventory(source_file)

    exc = exc_info.value
    assert len(exc.codec_invalid_lines) == 0
    assert len(exc.absent_observer_lines) == 0
    assert len(exc.mixed_observer_lines) == 1
    assert exc.mixed_observer_lines[0] == (1, ("alice", "bob"), 1)

    msg = str(exc)
    assert "line 1: observers 'alice', 'bob' (1 row(s) missing 'observer' field)" in msg


def test_type_error_in_observer_lands_in_codec_invalid_class(tmp_path: Path) -> None:
    """A batch with a non-string observer (e.g. dict) is caught by validation-first
    and lands in codec-invalid class without raising an unhandled TypeError."""
    source_file = build_type_error_batch_jsonl(tmp_path / "type_err.jsonl")

    with pytest.raises(MigrationRefused) as exc_info:
        inventory(source_file)

    exc = exc_info.value
    assert len(exc.codec_invalid_lines) == 1
    assert exc.codec_invalid_lines[0][0] == 1
    assert "fact field 'observer' must be a string, got dict" in exc.codec_invalid_lines[0][1]
    assert len(exc.mixed_observer_lines) == 0
    assert len(exc.absent_observer_lines) == 0


def test_inventory_is_behaviorally_read_only_on_success_and_refusal(tmp_path: Path) -> None:
    """Behavioral read-only test: snapshot parent directory (recursive relative paths,
    sizes, and mtimes) before and after inventory() on BOTH success and refusal paths."""
    # 1. Success path (JSONL and SQLite)
    jsonl_dir = tmp_path / "success_jsonl"
    jsonl_dir.mkdir()
    jsonl_file = build_synthetic_jsonl(jsonl_dir / "store.jsonl")

    snap_before_jsonl = _snapshot_dir(jsonl_dir)
    inventory(jsonl_file)
    snap_after_jsonl = _snapshot_dir(jsonl_dir)
    assert snap_before_jsonl == snap_after_jsonl

    sqlite_dir = tmp_path / "success_sqlite"
    sqlite_dir.mkdir()
    sqlite_file = build_synthetic_sqlite(sqlite_dir / "store.sqlite")

    snap_before_sqlite = _snapshot_dir(sqlite_dir)
    inventory(sqlite_file)
    snap_after_sqlite = _snapshot_dir(sqlite_dir)
    assert snap_before_sqlite == snap_after_sqlite

    # 2. Refusal path
    refusal_dir = tmp_path / "refusal_dir"
    refusal_dir.mkdir()
    refusal_file = build_combined_defects_jsonl(refusal_dir / "combined.jsonl")

    snap_before_refusal = _snapshot_dir(refusal_dir)
    with pytest.raises(MigrationRefused):
        inventory(refusal_file)
    snap_after_refusal = _snapshot_dir(refusal_dir)
    assert snap_before_refusal == snap_after_refusal

