"""Golden log fixtures — the cross-language contract for batch ceremonies.

Oracle #9 of design:architecture/jsonl-declaration-ceremony-encoding. The
committed files under ``fixtures/jsonl/`` are what the future Go conformance
oracle (thread:loops-go-conformance-oracle) consumes; these tests pin the
Python side. The positive golden was generated ONCE (``generate_golden.py``
is provenance, not a test — ids/ts are minted, so it is never re-run here);
the negatives are deterministic (``generate_negatives.py``).
"""

from __future__ import annotations

import json
import shutil
import sqlite3
from pathlib import Path

import pytest
from atoms import Fact

from engine.canonical_audit import audit_deep
from engine.jsonl_codec import JsonlCodecError, deserialize_records
from engine.jsonl_store import JsonlStore

FIXTURES = Path(__file__).parent / "fixtures" / "jsonl"
GOLDEN = FIXTURES / "golden-ceremonies.jsonl"


def _open(tmp_path: Path, log: Path) -> JsonlStore:
    """A store over a COPY of the fixture — fixtures are read-only evidence."""
    copied = tmp_path / log.name
    shutil.copyfile(log, copied)
    return JsonlStore(
        path=tmp_path / (log.stem + ".db"),
        log_path=copied,
        serialize=lambda f: f.to_dict(),
        deserialize=Fact.from_dict,
    )


def _lines(path: Path) -> list[str]:
    return [ln for ln in path.read_text(encoding="utf-8").split("\n") if ln]


# --- positive ---------------------------------------------------------------


def test_golden_decodes_to_the_exact_record_sequence():
    lines = _lines(GOLDEN)
    discriminators = [json.loads(ln)["t"] for ln in lines]
    assert discriminators == ["fact", "fact", "fact", "batch", "batch", "tick"]

    per_line = [deserialize_records(ln) for ln in lines]
    assert [len(records) for records in per_line] == [1, 1, 1, 2, 3, 1]

    flat = [rec for records in per_line for rec in records]
    assert [t for t, _ in flat] == ["fact"] * 8 + ["tick"]
    kinds = [row[1] for t, row in flat if t == "fact"]
    assert kinds[0] == "_decl.genesis"
    assert kinds[1] == kinds[2] == "note"
    assert all(k.startswith("_decl.kind-") for k in kinds[3:])
    # each ceremony stamps ONE effective ts (D1's ceremony half)
    for records in per_line[3:5]:
        assert len({row[2] for _, row in records}) == 1
    # every ceremony (_decl.*) row is signed; ids unique across the log
    assert all(
        row[-1] is not None
        for t, row in flat
        if t == "fact" and row[1].startswith("_decl.")
    )
    ids = [row[0] for _, row in flat]
    assert len(set(ids)) == len(ids)


def test_golden_indexes_with_expected_counts_and_audit_deep_passes(tmp_path):
    store = _open(tmp_path, GOLDEN)
    conn = sqlite3.connect(str(store._path))
    try:
        facts = conn.execute("SELECT COUNT(*) FROM facts").fetchone()[0]
        ticks = conn.execute("SELECT COUNT(*) FROM ticks").fetchone()[0]
        order = [r[0] for r in conn.execute("SELECT kind FROM facts ORDER BY rowid")]
    finally:
        conn.close()
    assert (facts, ticks) == (8, 1)
    # rowid order == log order, batch rows expanded in array order
    flat_kinds = [
        row[1]
        for ln in _lines(store.log_path)
        for t, row in deserialize_records(ln)
        if t == "fact"
    ]
    assert order == flat_kinds
    store.close()
    report = audit_deep(store.log_path)
    assert report.ok, report.summary()


# --- negatives: codec refusals, pinned classes ------------------------------


@pytest.mark.parametrize(
    ("fixture", "pattern"),
    [
        ("batch-empty-rows.jsonl", "at least 2 rows"),
        ("batch-one-row.jsonl", "at least 2 rows"),
        ("batch-nested.jsonl", "nested batch"),
        ("batch-tick-inside.jsonl", "tick record"),
        ("batch-dup-id.jsonl", "duplicate id"),
        ("batch-unknown-key.jsonl", "unknown field"),
    ],
)
def test_negative_fixture_refuses_at_the_codec_gate(fixture, pattern):
    (line,) = _lines(FIXTURES / fixture)
    with pytest.raises(JsonlCodecError, match=pattern):
        deserialize_records(line)


# --- negatives: recovery and audit boundaries -------------------------------


def test_torn_batch_tail_truncates_not_errors(tmp_path):
    store = _open(tmp_path, FIXTURES / "batch-torn-tail.jsonl")
    # The torn ceremony never happened: only the intact plain line survives.
    assert _lines(store.log_path) == _lines(FIXTURES / "batch-torn-tail.jsonl")[:1]
    conn = sqlite3.connect(str(store._path))
    try:
        ids = [r[0] for r in conn.execute("SELECT id FROM facts ORDER BY rowid")]
    finally:
        conn.close()
    assert len(ids) == 1 and not any("01JNEG00000000000000000001" in i for i in ids)
    store.close()
    assert audit_deep(store.log_path).ok


def test_mixed_ts_decl_batch_is_audit_divergence_not_codec_error(tmp_path):
    """D1's boundary: the codec admits it (transport stays structural);
    audit_deep names the ceremony-invariant violation."""
    (line,) = _lines(FIXTURES / "batch-mixed-ts-decl.jsonl")
    assert len(deserialize_records(line)) == 2  # codec-valid

    store = _open(tmp_path, FIXTURES / "batch-mixed-ts-decl.jsonl")
    store.close()
    report = audit_deep(store.log_path)
    assert not report.ok
    assert any("distinct ts" in c.detail for c in report.divergences)
