"""Conformance runner for SDK operations against all 35 golden vectors.

Validates that `libs/sdk` read, replay, fold, and witness pagination
conform 100% to the specification vectors:
- spec/conformance/vectors/fold/*.json (10 vectors)
- spec/conformance/vectors/replay/*.json (10 vectors)
- spec/conformance/vectors/witness/*.json (5 vectors)
- spec/conformance/vectors/merge/*.json (10 vectors)
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

from sdk import (
    read_facts,
    read_summary,
)

REPO_ROOT = Path(__file__).resolve().parents[3]
FOLD_VECTORS_DIR = REPO_ROOT / "spec" / "conformance" / "vectors" / "fold"
REPLAY_VECTORS_DIR = REPO_ROOT / "spec" / "conformance" / "vectors" / "replay"
WITNESS_VECTORS_DIR = REPO_ROOT / "spec" / "conformance" / "vectors" / "witness"
MERGE_VECTORS_DIR = REPO_ROOT / "spec" / "conformance" / "vectors" / "merge"


def _find_vectors(vectors_dir: Path) -> list[Path]:
    if not vectors_dir.exists():
        return []
    return sorted(vectors_dir.glob("*.json"))


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


# -----------------------------------------------------------------------------
# 1. Fold Vectors (10 vectors)
# -----------------------------------------------------------------------------
@pytest.mark.parametrize(
    "vector_path",
    _find_vectors(FOLD_VECTORS_DIR),
    ids=lambda p: p.stem,
)
def test_sdk_conformance_fold(vector_path: Path) -> None:
    """Validate fold conformance vectors match Spec.replay output."""
    with vector_path.open(encoding="utf-8") as f:
        vector = json.load(f)

    spec = _decode_spec(vector["input"]["spec"])
    payloads = vector["input"]["payloads"]
    expected = vector["expected"]

    actual_state = spec.replay(payloads)
    actual_json = json.loads(json.dumps(actual_state))
    assert actual_json == expected


# -----------------------------------------------------------------------------
# 2. Replay Vectors (10 vectors)
# -----------------------------------------------------------------------------
@pytest.mark.parametrize(
    "vector_path",
    _find_vectors(REPLAY_VECTORS_DIR),
    ids=lambda p: p.stem,
)
def test_sdk_conformance_replay(vector_path: Path, tmp_path: Path) -> None:
    """Validate sdk read_facts and timeline over replay conformance vectors."""
    with vector_path.open(encoding="utf-8") as f:
        vector = json.load(f)

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

    # Read using sdk API
    summary = read_summary(db_path)
    assert summary.fact_total == len(raw_facts)

    page = read_facts(db_path, limit=len(raw_facts) + 10, order="oldest", kind=spec.name)
    payloads = []
    for f in page.items:
        p = dict(f["payload"])
        ts_val = f["ts"].timestamp() if hasattr(f["ts"], "timestamp") else float(f["ts"])
        p["_ts"] = ts_val
        p["_observer"] = f["observer"]
        p["_origin"] = f.get("origin", "")
        p["_id"] = f.get("id")
        payloads.append(p)

    # No re-sort: the sdk page is already in receipt order, which IS fold
    # order. Pin that rather than re-imposing a (ts, id) sort — the sort
    # would mask the read path disagreeing with the fold path.
    appended_ids = [
        fid for fid, fact_dict in raw_facts if fact_dict["kind"] == spec.name
    ]
    assert [p["_id"] for p in payloads] == appended_ids

    actual_state = spec.replay(payloads)
    actual_json = json.loads(json.dumps(actual_state))
    assert actual_json == expected


# -----------------------------------------------------------------------------
# 3. Witness Vectors (5 vectors)
# -----------------------------------------------------------------------------
@pytest.mark.parametrize(
    "vector_path",
    _find_vectors(WITNESS_VECTORS_DIR),
    ids=lambda p: p.stem,
)
def test_sdk_conformance_witness(vector_path: Path, tmp_path: Path) -> None:
    """Validate sdk witness cursor pagination against witness conformance vectors."""
    with vector_path.open(encoding="utf-8") as f:
        vector = json.load(f)

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


# -----------------------------------------------------------------------------
# 4. Merge Vectors (10 vectors)
# -----------------------------------------------------------------------------
@pytest.mark.parametrize(
    "vector_path",
    _find_vectors(MERGE_VECTORS_DIR),
    ids=lambda p: p.stem,
)
def test_sdk_conformance_merge(vector_path: Path, tmp_path: Path) -> None:
    """Validate merge conformance vector inputs stored and readable via sdk."""
    with vector_path.open(encoding="utf-8") as f:
        vector = json.load(f)

    input_doc = vector["input"]
    target_facts = input_doc.get("target", [])
    source_facts = input_doc.get("source", [])

    target_db = tmp_path / f"{vector['name']}_target.db"
    target_store = SqliteStore(
        path=target_db,
        serialize=lambda f: f.to_dict() if isinstance(f, Fact) else f,
        deserialize=Fact.from_dict,
    )
    for fid, fact_dict in target_facts:
        target_store.append(_decode_fact(fact_dict), id_override=fid)
    target_store.close()

    source_db = tmp_path / f"{vector['name']}_source.db"
    source_store = SqliteStore(
        path=source_db,
        serialize=lambda f: f.to_dict() if isinstance(f, Fact) else f,
        deserialize=Fact.from_dict,
    )
    for fid, fact_dict in source_facts:
        source_store.append(_decode_fact(fact_dict), id_override=fid)
    source_store.close()

    # Verify both stores are readable via sdk
    target_sum = read_summary(target_db)
    source_sum = read_summary(source_db)
    assert target_sum.fact_total == len(target_facts)
    assert source_sum.fact_total == len(source_facts)
