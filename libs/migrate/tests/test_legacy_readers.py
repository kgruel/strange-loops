"""Tests for frozen legacy readers and legacy ID migrations."""

from __future__ import annotations

from pathlib import Path

import pytest

from migrate.legacy_ids import (
    FactRow,
    classify_id_era,
    deterministic_ulid,
    identity,
    is_ulid,
    ulid_migration,
)
from migrate.legacy_jsonl import (
    JsonlCodecError,
    deserialize_records,
    deserialize_row,
    load_line,
)
from migrate.legacy_sqlite import (
    _chain_head,
    _content_sha256,
    _facts_have_signature,
    _tick_columns,
    open_legacy_sqlite,
    read_facts,
    read_ticks,
)

from ._fixtures import build_synthetic_jsonl, build_synthetic_sqlite


def test_legacy_ids_classification_and_transform() -> None:
    """Test ID era classification and deterministic ULID transforms."""
    canonical_id = "01ARZ3NDEKTSV4RRFFQ69G5FA0"
    lower_id = "01arz3ndektsv4rrffq69g5fav"
    uuid4_id = "c56a4180-65aa-42ec-a945-5fd21dec0538"
    short_id = "01A"

    assert classify_id_era(canonical_id) == "canonical-ulid"
    assert classify_id_era(lower_id) == "lowercase-ulid"
    assert classify_id_era(uuid4_id) == "uuid4"
    assert classify_id_era(short_id) == "uuid4"

    assert is_ulid(canonical_id) is True
    assert is_ulid(lower_id) is False
    assert is_ulid(uuid4_id) is False

    # Determinism
    ulid1 = deterministic_ulid(1000.0, "seed-1")
    ulid2 = deterministic_ulid(1000.0, "seed-1")
    ulid3 = deterministic_ulid(1000.0, "seed-2")
    assert ulid1 == ulid2
    assert ulid1 != ulid3
    assert is_ulid(ulid1)

    # Identity transform
    ident = identity()
    row = FactRow(id=uuid4_id, kind="c", ts=1.0, observer="o", origin="or", payload="{}")
    assert ident.map_fact(row) == row

    # ULID migration transform: canonical passes untouched; others migrate deterministically
    mig = ulid_migration()
    row_canon = FactRow(id=canonical_id, kind="c", ts=1.0, observer="o", origin="or", payload="{}")
    assert mig.map_fact(row_canon).id == canonical_id

    row_uuid = FactRow(id=uuid4_id, kind="c", ts=1.0, observer="o", origin="or", payload="{}")
    mig_row = mig.map_fact(row_uuid)
    assert mig_row.id != uuid4_id
    assert is_ulid(mig_row.id)
    assert mig_row.id == deterministic_ulid(1.0, uuid4_id)


def test_legacy_jsonl_decode(tmp_path: Path) -> None:
    """Test legacy JSONL decoder on lines and objects."""
    jsonl_path = build_synthetic_jsonl(tmp_path / "test.jsonl")

    with jsonl_path.open("r", encoding="utf-8") as f:
        lines = [line.strip() for line in f if line.strip()]

    # First line is a single fact
    t, row = deserialize_row(lines[0])
    assert t == "fact"
    assert row[0] == "c56a4180-65aa-42ec-a945-5fd21dec0538"
    assert row[1] == "concept"
    assert row[6] == "sig-alice-1"

    # Line 6 is a batch line
    batch_line = lines[5]
    with pytest.raises(JsonlCodecError, match="batch line carries multiple records"):
        deserialize_row(batch_line)

    records = deserialize_records(batch_line)
    assert len(records) == 2
    assert records[0][0] == "fact"
    assert records[1][0] == "fact"

    # Load line checks duplicate keys
    with pytest.raises(JsonlCodecError, match="duplicate key"):
        load_line('{"t":"fact","id":"A","id":"B"}')

    # Load line checks non-JSON literals
    with pytest.raises(JsonlCodecError, match="non-JSON literal"):
        load_line('{"t":"fact","id":"A","ts":NaN}')


def test_legacy_sqlite_read(tmp_path: Path) -> None:
    """Test legacy SQLite reader functions."""
    sqlite_path = build_synthetic_sqlite(tmp_path / "test.sqlite")

    conn = open_legacy_sqlite(sqlite_path)
    try:
        assert _facts_have_signature(conn) is True
        cols = _tick_columns(conn)
        assert "id" in cols
        assert "name" in cols
        assert "window_hash" in cols

        facts = read_facts(conn)
        assert len(facts) == 7
        assert facts[0].id == "c56a4180-65aa-42ec-a945-5fd21dec0538"
        assert facts[0].signature == "sig-alice-1"

        ticks = read_ticks(conn)
        assert len(ticks) == 2
        assert ticks[0]["id"] == "01ARZ3NDEKTSV4RRFFQ69G5FT1"
        assert ticks[1]["name"] == "checkpoint"

        head = _chain_head(conn)
        assert head is not None
        assert isinstance(head, str)
        assert len(head) == 64

        sha = _content_sha256(conn)
        assert isinstance(sha, str)
        assert len(sha) == 64
    finally:
        conn.close()
