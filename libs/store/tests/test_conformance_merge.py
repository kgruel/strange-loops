"""Conformance runner for store merge semantics.

Loads all vectors dynamically from:
- spec/conformance/vectors/merge/*.json

Validates exact parity between merge outcomes (counters, rowid sequence, surviving content, witness invariance) and golden vectors.
"""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path
from typing import Any

import pytest
from atoms import (
    Avg,
    Collect,
    Count,
    Fact,
    Field,
    FoldOp,
    Latest,
    Max,
    Min,
    Spec,
    Sum,
    TopN,
    Upsert,
    Window,
)
from engine.sqlite_store import SqliteStore
from engine.store_reader import StoreReader
from engine.witness import resolve_witness_position
from store.merge import merge_store

REPO_ROOT = Path(__file__).resolve().parents[3]
MERGE_VECTORS_DIR = REPO_ROOT / "spec" / "conformance" / "vectors" / "merge"


def _decode_field(data: dict[str, Any]) -> Field:
    return Field(
        name=data["name"],
        kind=data["kind"],
        optional=data.get("optional", False),
    )


def _decode_fold(data: dict[str, Any]) -> FoldOp:
    op = data["op"]
    if op == "latest":
        return Latest(target=data["target"])
    elif op == "count":
        return Count(target=data["target"])
    elif op == "sum":
        return Sum(target=data["target"], field=data["field"])
    elif op == "collect":
        return Collect(target=data["target"], max=data.get("max", 0))
    elif op == "upsert":
        return Upsert(target=data["target"], key=data["key"])
    elif op == "top_n":
        return TopN(
            target=data["target"],
            key=data["key"],
            by=data["by"],
            n=data["n"],
            desc=data.get("desc", True),
        )
    elif op == "min":
        return Min(target=data["target"], field=data["field"])
    elif op == "max":
        return Max(target=data["target"], field=data["field"])
    elif op == "avg":
        return Avg(target=data["target"], field=data["field"])
    elif op == "window":
        return Window(target=data["target"], field=data["field"], size=data["size"])
    else:
        raise ValueError(f"Unknown fold op: {op}")


def _decode_spec(data: dict[str, Any]) -> Spec:
    return Spec(
        name=data["name"],
        about=data.get("about", ""),
        input_fields=tuple(_decode_field(f) for f in data.get("input_fields", ())),
        state_fields=tuple(_decode_field(f) for f in data.get("state_fields", ())),
        folds=tuple(_decode_fold(f) for f in data.get("folds", ())),
    )


def _decode_fact(data: dict[str, Any]) -> Fact:
    return Fact(
        kind=data["kind"],
        ts=float(data["ts"]),
        payload=data["payload"],
        observer=data.get("observer", ""),
        origin=data.get("origin", ""),
    )


def _populate_store(db_path: Path, raw_facts: list[tuple[str, dict[str, Any]] | list[Any]]) -> None:
    store = SqliteStore(
        path=db_path,
        serialize=lambda f: f.to_dict() if isinstance(f, Fact) else f,
        deserialize=Fact.from_dict,
    )
    for fid, fact_dict in raw_facts:
        store.append(_decode_fact(fact_dict), id_override=fid)
    store.close()


def _load_vectors(vectors_dir: Path) -> list[Path]:
    return sorted(vectors_dir.glob("*.json"))


@pytest.mark.parametrize("vector_path", _load_vectors(MERGE_VECTORS_DIR), ids=lambda p: p.stem)
def test_conformance_merge(vector_path: Path, tmp_path: Path) -> None:
    """Validate merge conformance golden vector."""
    with open(vector_path, encoding="utf-8") as f:
        vector = json.load(f)

    assert "name" in vector, f"Vector {vector_path} missing 'name'"
    assert "description" in vector, f"Vector {vector_path} missing 'description'"
    assert "input" in vector, f"Vector {vector_path} missing 'input'"
    assert "expected" in vector, f"Vector {vector_path} missing 'expected'"

    input_doc = vector["input"]
    expected_doc = vector["expected"]

    target_db = tmp_path / f"{vector['name']}_target.db"
    _populate_store(target_db, input_doc["target"])

    is_self_merge = input_doc.get("self_merge", False)
    if is_self_merge:
        merge_result = merge_store(target_db, target_db)
    else:
        source_db = tmp_path / f"{vector['name']}_source.db"
        _populate_store(source_db, input_doc.get("source", []))
        merge_result = merge_store(target_db, source_db)

    # 1. Validate MergeResult counters
    expected_result = expected_doc["result"]
    assert merge_result.facts_added == expected_result["facts_added"]
    assert merge_result.facts_skipped == expected_result["facts_skipped"]
    if "ticks_added" in expected_result:
        assert merge_result.ticks_added == expected_result["ticks_added"]
    if "ticks_skipped" in expected_result:
        assert merge_result.ticks_skipped == expected_result["ticks_skipped"]

    # 2. Validate post-merge rowid sequence (fact IDs)
    conn = sqlite3.connect(str(target_db))
    rows = conn.execute(
        "SELECT id, kind, ts, observer, origin, payload FROM facts ORDER BY rowid ASC"
    ).fetchall()
    conn.close()

    actual_post_merge_ids = [r[0] for r in rows]
    assert actual_post_merge_ids == expected_doc["post_merge_ids"]

    # 3. Validate post_merge_facts if present
    if "post_merge_facts" in expected_doc:
        actual_post_merge_facts = [
            [
                r[0],
                {
                    "kind": r[1],
                    "ts": r[2],
                    "payload": json.loads(r[5]),
                    "observer": r[3],
                    "origin": r[4],
                },
            ]
            for r in rows
        ]
        assert actual_post_merge_facts == expected_doc["post_merge_facts"]

    # 4. Validate witness folds if specified
    if "witness_folds" in expected_doc:
        spec = _decode_spec(input_doc["spec"])
        cursors = input_doc["cursors"]
        expected_witness_folds = expected_doc["witness_folds"]

        for label, cursor_addr in cursors.items():
            pos = resolve_witness_position(target_db, cursor_addr)
            with StoreReader(target_db) as reader:
                stored_facts = reader.facts_by_kind(spec.name, at_rowid=pos.rowid)
                payloads = []
                for f in stored_facts:
                    p = dict(f["payload"])
                    p["_ts"] = f["ts"]
                    p["_observer"] = f["observer"]
                    p["_origin"] = f.get("origin", "")
                    p["_id"] = f.get("id")
                    payloads.append(p)

                actual_state = spec.replay(payloads)
                actual_json = json.loads(json.dumps(actual_state))

            assert actual_json == expected_witness_folds[label], f"Mismatch for cursor {label!r}"
