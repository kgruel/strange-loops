"""Conformance runner for store replay and witness cursor semantics.

Loads all vectors dynamically from:
- spec/conformance/vectors/replay/*.json
- spec/conformance/vectors/witness/*.json

Validates exact parity between stored replay / witness fold outputs and golden vectors.
"""

from __future__ import annotations

import json
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

REPO_ROOT = Path(__file__).resolve().parents[3]
REPLAY_VECTORS_DIR = REPO_ROOT / "spec" / "conformance" / "vectors" / "replay"
WITNESS_VECTORS_DIR = REPO_ROOT / "spec" / "conformance" / "vectors" / "witness"


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


def _load_vectors(vectors_dir: Path) -> list[Path]:
    return sorted(vectors_dir.glob("*.json"))


@pytest.mark.parametrize("vector_path", _load_vectors(REPLAY_VECTORS_DIR), ids=lambda p: p.stem)
def test_conformance_replay(vector_path: Path, tmp_path: Path) -> None:
    with open(vector_path, encoding="utf-8") as f:
        vector = json.load(f)

    assert "name" in vector, f"Vector {vector_path} missing 'name'"
    assert "description" in vector, f"Vector {vector_path} missing 'description'"
    assert "input" in vector, f"Vector {vector_path} missing 'input'"
    assert "expected" in vector, f"Vector {vector_path} missing 'expected'"

    spec = _decode_spec(vector["input"]["spec"])
    raw_facts = vector["input"]["facts"]
    expected = vector["expected"]

    db_path = tmp_path / f"{vector['name']}.db"
    store = SqliteStore(
        path=db_path,
        serialize=lambda f: f.to_dict() if isinstance(f, Fact) else f,
        deserialize=Fact.from_dict,
    )
    for fid, fact_dict in raw_facts:
        store.append(_decode_fact(fact_dict), id_override=fid)
    store.close()

    with StoreReader(db_path) as reader:
        stored_facts = reader.facts_by_kind(spec.name)
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

    assert actual_json == expected


@pytest.mark.parametrize("vector_path", _load_vectors(WITNESS_VECTORS_DIR), ids=lambda p: p.stem)
def test_conformance_witness(vector_path: Path, tmp_path: Path) -> None:
    with open(vector_path, encoding="utf-8") as f:
        vector = json.load(f)

    assert "name" in vector, f"Vector {vector_path} missing 'name'"
    assert "description" in vector, f"Vector {vector_path} missing 'description'"
    assert "input" in vector, f"Vector {vector_path} missing 'input'"
    assert "expected" in vector, f"Vector {vector_path} missing 'expected'"

    spec = _decode_spec(vector["input"]["spec"])
    raw_facts = vector["input"]["facts"]
    cursors = vector["input"]["cursors"]
    expected_by_cursor = vector["expected"]

    db_path = tmp_path / f"{vector['name']}.db"
    store = SqliteStore(
        path=db_path,
        serialize=lambda f: f.to_dict() if isinstance(f, Fact) else f,
        deserialize=Fact.from_dict,
    )
    for fid, fact_dict in raw_facts:
        store.append(_decode_fact(fact_dict), id_override=fid)
    store.close()

    for label, cursor_addr in cursors.items():
        pos = resolve_witness_position(db_path, cursor_addr)
        with StoreReader(db_path) as reader:
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

        assert actual_json == expected_by_cursor[label], f"Mismatch for cursor {label!r}"
